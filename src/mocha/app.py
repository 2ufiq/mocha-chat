"""
FastAPI entry point for mocha-chat.

Routes:
    GET  /                    → landing gallery (static/index.html)
    GET  /chat                → chat page (static/chat.html, reads ?persona= in JS)
    GET  /healthz             → liveness probe
    GET  /api/personas        → public metadata for the landing cards
    GET  /api/persona/{slug}  → single persona meta + greeting
    POST /api/chat            → stream a reply for {persona, history, memory}
    POST /api/compact         → fold older history into a memory string

Stateless. All history + memory lives in the browser's localStorage,
keyed per-persona slug so each character has its own conversation.
"""

import functools
import html as _html
import json
import os
import time

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mocha.utils import get_datetime_ctx

load_dotenv()

# Force colors so Render's log viewer renders ANSI (default ConsoleRenderer
# strips them when stdout isn't a TTY — i.e. always, in prod).
structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="%b %d %I:%M:%S %p", utc=False),
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
        structlog.dev.ConsoleRenderer(colors=True),
    ],
)

logger = structlog.get_logger(__name__)

from mocha.memory import summarize  # noqa: E402
from mocha.openrouter import api_complete_stream  # noqa: E402
from mocha.personas import (  # noqa: E402
    UNIVERSAL_RULES,
    Persona,
    get as get_persona,
    public_list,
)
from mocha.translation import translate

DEFAULT_TRANSLATE_TARGET = os.getenv("TRANSLATE_TARGET", "bn")
KEEP_RECENT = int(os.getenv("KEEP_RECENT", "20"))
STATIC_CACHE_SECONDS = int(os.getenv("STATIC_CACHE_SECONDS", "86400")) # 86400 = 1 day

app = FastAPI()


# ---- Liveness -------------------------------------------------------------
@app.get("/healthz")
@app.get("/healthz/")
def healthz():
    # Local import keeps cold-start path lean and avoids any circular risk.
    from mocha import settings

    return {
        "status": "ok",
        "service": "mocha-chat",
        "timestamp": int(time.time()),
        "openrouter_configured": bool(settings.OPENROUTER_API_KEY),
    }


# ---- Pages ----------------------------------------------------------------
# Landing page is rendered with persona data inlined directly into the HTML
# so the browser can paint cards on first parse — no /api/personas round-trip
# required. We also emit <link rel="preload"> tags for each persona image so
# the browser starts parallel-fetching them while it's still parsing HTML.
# Cold-load on a clean cache used to take ~600-1200ms before the first card
# appeared. With this it's ~150-300ms.
@functools.lru_cache(maxsize=1)
def _landing_template() -> str:
    """Read static/index.html once at process start, cache forever."""
    with open("static/index.html", encoding="utf-8") as f:
        return f.read()


_PERSONAS_PLACEHOLDER = "<!-- INLINE_PERSONAS -->"


@app.get("/", response_class=HTMLResponse)
def landing():
    tmpl = _landing_template()
    personas = public_list()
    inline_json = json.dumps(personas, ensure_ascii=False)
    # Image preloads run during HTML parse — before our JS even executes.
    # `fetchpriority=high` nudges the browser to send them ahead of other
    # subresources.
    preloads = "\n".join(
        f'<link rel="preload" as="image" href="/persona/{_html.escape(p["avatar"])}" fetchpriority="high">'
        for p in personas if p.get("avatar")
    )
    injected = (
        f"<script>window.MOCHA_PERSONAS={inline_json};</script>\n{preloads}"
    )
    body = tmpl.replace(_PERSONAS_PLACEHOLDER, injected)
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


# `/chat` needs its own route because StaticFiles wouldn't auto-serve
# chat.html from a path without the `.html` suffix.
@app.get("/chat")
def chat_page():
    return FileResponse("static/chat.html")


# ---- Persona metadata API -------------------------------------------------
@app.get("/api/personas")
def list_personas():
    """Public card-facing metadata for all personas. No system prompts leaked."""
    return {"personas": public_list()}


@app.get("/api/persona/{slug}")
def get_persona_meta(slug: str):
    """Single persona's public metadata + greeting. Used by chat.html on load."""
    p = get_persona(slug)
    if not p:
        raise HTTPException(status_code=404, detail="persona not found")
    return {
        "slug": p.slug,
        "name": p.name,
        "age": p.age,
        "profession": p.profession,
        "tags": p.tags,
        "avatar": p.avatar,
        "emoji": p.emoji,
        "tagline": p.tagline,
        "greeting": p.greeting,
    }


# ---- Chat / compact -------------------------------------------------------
def _build_messages(persona: Persona, history: list, memory: str) -> list:
    """
    Compose the LLM wire payload:
        persona.system_prompt + (optional memory-as-system) + last KEEP_RECENT history
    """
    # `extra_prompt` injection slot in each persona = universal rules + current
    # datetime. Universal rules go first so they're not lost mid-prompt.
    extra = f"\n{UNIVERSAL_RULES}\nCurrent datetime: {get_datetime_ctx()}\n"
    msgs = [{"role": "system", "content": persona.system_prompt.format(extra_prompt=extra)}]
    if memory:
        msgs.append(
            {
                "role": "system",
                "content": f"What you remember from earlier in this chat:\n{memory}",
            }
        )
    msgs.extend(history[-KEEP_RECENT:])
    logger.info(
        "build_messages",
        persona=persona.slug,
        total_history=len(history),
        included_history=min(len(history), KEEP_RECENT),
        memory_chars=len(memory),
    )
    return msgs


@app.post("/api/chat")
async def chat(request: Request):
    """
    Body: {"persona": "<slug>", "history": [...], "memory": "..."}
    Streams the assistant reply as plain text.
    """
    body = await request.json()
    persona_slug = body.get("persona") or "mocha"
    persona = get_persona(persona_slug)
    if not persona:
        raise HTTPException(status_code=400, detail=f"unknown persona: {persona_slug}")
    history = body.get("history", [])
    memory = body.get("memory", "") or ""
    last_user = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
    )
    logger.info(
        "POST /api/chat",
        persona=persona_slug,
        turns=len(history),
        mem_chars=len(memory),
        sent_turns=min(len(history), KEEP_RECENT),
        last_user=last_user[:80],
    )
    messages = _build_messages(persona, history, memory)
    return StreamingResponse(api_complete_stream(messages), media_type="text/plain")


@app.post("/api/compact")
async def compact(request: Request):
    """
    Body: {"persona": "<slug>", "messages": [...older chunk...], "prior_memory": "..."}
    Returns: {"memory": "..."}
    """
    body = await request.json()
    older = body.get("messages", [])
    prior = body.get("prior_memory", "") or ""
    persona_slug = body.get("persona") or "mocha"
    persona = get_persona(persona_slug)
    # Falling back to a generic label if the slug is unknown keeps compaction
    # working even if the frontend ever sends a stale slug — better than 500ing.
    persona_name = persona.name if persona else "the assistant"
    logger.info(
        "POST /api/compact",
        persona=persona_slug,
        folding_msgs=len(older),
        prior_mem_chars=len(prior),
    )
    new_memory = await summarize(older, prior_memory=prior, persona_name=persona_name)
    return {"memory": new_memory}


@app.post("/api/translate")
async def translate_endpoint(request: Request):
    """
    Body: {"text": "<source>", "target": "bn"}  # target is optional
    Returns: {"translated": "...", "target": "bn"}
    On failure: HTTP 502 with {"detail": "<err>"} — frontend toasts it.
    """
    body = await request.json()
    text = (body.get("text") or "").strip()
    target = body.get("target") or DEFAULT_TRANSLATE_TARGET
    if not text:
        return {"translated": "", "target": target}
    try:
        translated = await translate(text, target=target)
        logger.info(
            "POST /api/translate",
            target=target,
            in_chars=len(text),
            out_chars=len(translated),
        )
        return {"translated": translated, "target": target}
    except Exception as exc:
        # googletrans is unofficial — when it breaks we return 502 with a
        # human-readable detail so the toast in the UI is informative. Empty
        # str(exc) is common with googletrans internals, so we also include
        # the exception type as a hint.
        msg = str(exc) or type(exc).__name__
        logger.warning("translate failed", err_type=type(exc).__name__, err=msg, in_chars=len(text))
        raise HTTPException(status_code=502, detail=f"translation unavailable ({msg})")


@app.middleware("http")
async def add_cache_headers(request: Request, call_next):
    response = await call_next(request)
    p = request.url.path
    if p.startswith("/persona/") or p == "/favicon.svg":
        response.headers["Cache-Control"] = f"public, max-age={STATIC_CACHE_SECONDS}"
    return response


# Mounted LAST so it doesn't shadow the routes above. Serves /chat.html, the
# /persona/* image directory, /favicon.svg, etc. The `/` slot is taken by the
# `landing()` route above (StaticFiles' index.html serving never runs).
app.mount("/", StaticFiles(directory="static", html=True), name="static")
