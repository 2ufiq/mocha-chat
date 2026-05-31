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

import os
import time

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from mocha.utils import get_datetime_ctx

load_dotenv()
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
# `/` is served by the StaticFiles mount at the bottom (default index.html).
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


# Mounted LAST so it doesn't shadow the routes above. Serves index.html at /
# plus any /static-style asset, including /persona/<file>.jpg.
app.mount("/", StaticFiles(directory="static", html=True), name="static")
