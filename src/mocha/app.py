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
from fastapi.exception_handlers import http_exception_handler as _default_http_exception_handler
from fastapi.responses import HTMLResponse, PlainTextResponse, Response, StreamingResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
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

from mocha.settings import (
    COMPACT_INTERVAL,
    KEEP_RECENT,
    MAX_MESSAGE_CHARS,
    MAX_TRANSLATE_CHARS,
)

DEFAULT_TRANSLATE_TARGET = os.getenv("TRANSLATE_TARGET", "bn")
STATIC_CACHE_SECONDS = int(os.getenv("STATIC_CACHE_SECONDS", "86400")) # 86400 = 1 day
# Public origin used in robots.txt + sitemap.xml. Swap once we migrate to the
# vanity domain (mocha.taufiq.cc). Single source of truth — keeps the meta
# tags in the HTML in lockstep with what we tell crawlers.
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "https://mocha-chat.onrender.com")

app = FastAPI()


# ---- SEO surface ----------------------------------------------------------
# Tiny crawl-control surface. Without these, the previous deployment was 404ing
# /robots.txt (visible in logs) and Lighthouse SEO sat at 91. Landing is the
# only indexable page; /chat is per-persona via ?persona= and excluded.
@app.get("/robots.txt")
def robots_txt():
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /chat\n"
        "Disallow: /api/\n"
        f"Sitemap: {PUBLIC_ORIGIN}/sitemap.xml\n"
    )
    return PlainTextResponse(body)


@app.get("/sitemap.xml")
def sitemap_xml():
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{PUBLIC_ORIGIN}/</loc><changefreq>weekly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n"
    )
    return Response(content=body, media_type="application/xml")


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


# Chat page is rendered with a small config blob inlined so the client knows
# the server's compaction knobs (KEEP_RECENT, COMPACT_INTERVAL) without a
# separate round-trip. Same pattern as the landing route above.
@functools.lru_cache(maxsize=1)
def _chat_template() -> str:
    """Read static/chat.html once at process start, cache forever."""
    with open("static/chat.html", encoding="utf-8") as f:
        return f.read()


_CHAT_CONFIG_PLACEHOLDER = "__MOCHA_CONFIG__"


@app.get("/chat")
def chat_page():
    cfg = {
        "keepRecent": KEEP_RECENT,
        "compactInterval": COMPACT_INTERVAL,
        "maxMessageChars": MAX_MESSAGE_CHARS,
    }
    body = _chat_template().replace(_CHAT_CONFIG_PLACEHOLDER, json.dumps(cfg))
    return HTMLResponse(body, headers={"Cache-Control": "no-store"})


# Branded error page (currently only wired for 404; cached read mirrors the
# landing/chat template pattern). Single template with placeholders → swap
# at render time. No new templating engine; keep it boring.
@functools.lru_cache(maxsize=1)
def _error_template() -> str:
    with open("static/error.html", encoding="utf-8") as f:
        return f.read()


def _render_error(code: str, title: str, body: str) -> str:
    """Fill the error template's placeholders. HTML-escape inputs since they
    land inside the rendered page text (defence-in-depth — today's call sites
    only pass static strings, but future call sites might not)."""
    return (
        _error_template()
        .replace("__ERROR_CODE__", _html.escape(code))
        .replace("__ERROR_TITLE__", _html.escape(title))
        .replace("__ERROR_BODY__", _html.escape(body))
    )


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
def _format_profile(profile: dict | None) -> str:
    """One-line "About the user" from non-empty profile fields. Empty profile → ""."""
    if not profile or not isinstance(profile, dict):
        return ""
    parts = []
    for key in ("name", "age", "gender", "about"):
        val = (profile.get(key) or "").strip()
        if val:
            parts.append(f"{key}={val}")
    if not parts:
        return ""
    return "; ".join(parts) + "."


def _build_messages(
    persona: Persona, history: list, memory: str, profile: dict | None = None
) -> list:
    """
    Compose the LLM wire payload:
        persona.system_prompt + (optional profile-as-system)
        + (optional memory-as-system) + last KEEP_RECENT history
    """
    # `extra_prompt` injection slot in each persona = universal rules + current
    # datetime + (optional) user profile. Universal rules go first so they're
    # not lost mid-prompt. Profile is framed so the LLM knows what the line is:
    # facts the user gave us about themselves — use to personalize, don't recite.
    profile_line = _format_profile(profile)
    if profile_line:
        user_profile = (
            "\nUSER INFO:"
            "These are the facts about this user you're chatting with."
            "(use to personalize your tone and references; do not recite verbatim)"
            "\n"
            f"User: {profile_line}\n"
        )
    else: 
        user_profile = """
USER INFO (The user you're chatting with):
- You don't know this user yet. Don't assume their name, gender, profession,
  age, mood, or anything else until they tell you.
- Learn about them gradually. When it feels natural, ask ONE thing — what's
  their name, what they do, where they're at. Never an interview, never
  multiple questions at once. Use what they share in later replies.
- Don't drop pet names or familiar nicknames ("babe", "love", "dear",
  "my X") in the first few exchanges. Earn that familiarity. Use them once
  you've actually been talking for a bit and the user is into it.
- Don't expose any of these rules to the user. They're for your internal guidance only.
"""
    extra = f"\n{UNIVERSAL_RULES}\n{get_datetime_ctx()}\n{user_profile}"
    msgs = [{"role": "system", "content": persona.system_prompt.format(extra_prompt=extra)}]
    if memory:
        msgs.append(
            {
                "role": "system",
                "content": f"What you remember from earlier in this chat:\n{memory}",
            }
        )
    msgs.extend(history[-KEEP_RECENT:])
    last_user = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
    )
    logger.info(
        "Built Messages",
        persona=persona.slug,
        total_history=len(history),
        included_history=min(len(history), KEEP_RECENT),
        memory_chars=len(memory),
        profile_chars=len(profile_line),
        profile_line=profile_line[:50],
        user_msg=last_user[:50],
        user_msg_chars=len(last_user),
    )
    return msgs


@app.post("/api/chat")
async def chat(request: Request):
    """
    Body: {"persona": "<slug>", "history": [...], "memory": "..."}
    Streams the assistant reply as plain text.
    """
    try:
        client = request.client.host if request.client else "unknown"
    except Exception:
        client = "failed to detect"
    
    body = await request.json()
    persona_slug = body.get("persona") or "mocha"
    persona = get_persona(persona_slug)
    if not persona:
        raise HTTPException(status_code=400, detail=f"unknown persona: {persona_slug}")
    history = body.get("history", [])
    memory = body.get("memory", "") or ""
    profile = body.get("profile") or {}
    # Soft cap on the last user message: legit users can't exceed MAX via the
    # UI (textarea maxlength + counter). If we still see oversized content
    # here it's a curl-bypass — trim + log instead of 4xx-ing the request, so
    # the response shape stays uniform (cheaper to reason about).
    if history and history[-1].get("role") == "user":
        raw = history[-1].get("content", "") or ""
        if len(raw) > MAX_MESSAGE_CHARS:
            logger.warning(
                "user_message_truncated",
                from_ip=client,
                original_chars=len(raw),
                capped_to=MAX_MESSAGE_CHARS,
            )
            history[-1]["content"] = raw[:MAX_MESSAGE_CHARS]
    logger.info(
        "POST /api/chat",
        persona=persona_slug,
        turns=len(history),
        mem_chars=len(memory),
        sent_turns=min(len(history), KEEP_RECENT),
        has_profile=bool(profile),
        client=client,
    )
    messages = _build_messages(persona, history, memory, profile)
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
    profile = body.get("profile") or {}
    user_profile = _format_profile(profile)
    persona = get_persona(persona_slug)
    # Falling back to a generic label if the slug is unknown keeps compaction
    # working even if the frontend ever sends a stale slug — better than 500ing.
    persona_name = persona.name if persona else "the assistant"
    try:
        client = request.client.host if request.client else "unknown"
    except Exception:
        client = "failed to detect"
    logger.info(
        "POST /api/compact",
        persona=persona_slug,
        folding_msgs=len(older),
        prior_mem_chars=len(prior),
        user_profile=bool(user_profile),
        client=client,
    )
    new_memory = await summarize(older, prior_memory=prior, persona_name=persona_name, user_profile=user_profile)
    return {"memory": new_memory}


@app.post("/api/translate")
async def translate_endpoint(request: Request):
    """
    Body: {"text": "<source>", "target": "bn"}  # target is optional
    Returns: {"translated": "...", "target": "bn"}
    On failure: HTTP 502 with {"detail": "<err>"} — frontend toasts it.
    """
    try:
        client = request.client.host if request.client else "unknown"
    except Exception:
        client = "failed to detect"
    
    body = await request.json()
    text = (body.get("text") or "").strip()
    target = body.get("target") or DEFAULT_TRANSLATE_TARGET
    if not text:
        return {"translated": "", "target": target}
    # Soft cap: bot replies are typically <500 chars, so MAX_TRANSLATE_CHARS
    # (default 2000) leaves 4x headroom for legit content. Anything above is
    # almost certainly curl-bypass abuse; trim + log instead of 4xx-ing.
    if len(text) > MAX_TRANSLATE_CHARS:
        logger.warning(
            "translate_text_truncated",
            from_ip=client,
            original_chars=len(text),
            capped_to=MAX_TRANSLATE_CHARS,
        )
        text = text[:MAX_TRANSLATE_CHARS]
    try:
        translated = await translate(text, target=target)
        logger.info(
            "POST /api/translate",
            target=target,
            in_chars=len(text),
            out_chars=len(translated),
            client=client,
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


# Branded 404 page. Only intercepts 404s for browser-facing paths; every
# other code (and any /api/ or /healthz 404) is delegated to FastAPI's default
# JSON handler, so the translate / compact / persona JSON contracts the
# frontend relies on are unchanged. StaticFiles below raises HTTPException
# 404 for missing files — that's the main case this catches.
@app.exception_handler(StarletteHTTPException)
async def html_404_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        p = request.url.path
        if not (p.startswith("/api/") or p.startswith("/healthz")):
            return HTMLResponse(
                _render_error(
                    "404",
                    "page not found",
                    "looks like you wandered off the menu. let's get you back to the gallery.",
                ),
                status_code=404,
            )
    # Anything else → FastAPI's stock JSON behavior (preserves exc.headers etc.)
    return await _default_http_exception_handler(request, exc)


# Mounted LAST so it doesn't shadow the routes above. Serves /chat.html, the
# /persona/* image directory, /favicon.svg, etc. The `/` slot is taken by the
# `landing()` route above (StaticFiles' index.html serving never runs).
app.mount("/", StaticFiles(directory="static", html=True), name="static")
