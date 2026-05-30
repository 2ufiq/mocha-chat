import os
import time

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from mocha.utils import get_datetime_ctx

load_dotenv()
logger = structlog.get_logger(__name__)

from mocha.memory import summarize  # noqa: E402
from mocha.openrouter import api_complete_stream  # noqa: E402
from mocha.prompts.instructions import GREETING
from mocha.prompts.persona import (
    mocha,
)

KEEP_RECENT = int(os.getenv("KEEP_RECENT", "20"))

app = FastAPI()


@app.get("/healthz")
@app.get("/healthz/")
def healthz():
    from mocha import settings  # local import — avoids circulars + cold-start cost
    return {
        "status": "ok",
        "service": "mocha-chat",
        "timestamp": int(time.time()),
        "openrouter_configured": bool(settings.OPENROUTER_API_KEY),
    }


@app.get("/api/greeting")
def greeting():
    return {"greeting": GREETING}


def _build_messages(history: list, memory: str) -> list:
    """
    Build the wire payload for the LLM:
        system_prompt + (optional memory-as-system) + last KEEP_RECENT history
    """
    time_ctx = get_datetime_ctx()
    msgs = [{"role": "system", "content": mocha.SYSTEM_PROMPT.format(time_ctx=time_ctx)}]
    if memory:
        msgs.append({
            "role": "system",
            "content": f"What you remember from earlier in this chat:\n{memory}",
        })
    # Slice to recent tail. Older context is already folded into memory.
    msgs.extend(history[-KEEP_RECENT:])
    logger.info(
        "build_messages", 
        total_history=len(history), 
        included_history=min(len(history), KEEP_RECENT),
        memory_chars=len(memory),
        time_ctx=time_ctx,
    )
    return msgs


@app.post("/api/chat")
async def chat(request: Request):
    """
    Body: {"history": [...], "memory": "..."}
    Streams the assistant reply as plain text.
    """
    body = await request.json()
    history = body.get("history", [])
    memory = body.get("memory", "") or ""
    last_user = next(
        (m["content"] for m in reversed(history) if m.get("role") == "user"), ""
    )
    logger.info(
        "POST /api/chat",
        turns=len(history),
        mem_chars=len(memory),
        sent_turns=min(len(history), KEEP_RECENT),
        last_user=last_user[:80],
    )
    messages = _build_messages(history, memory)
    return StreamingResponse(api_complete_stream(messages), media_type="text/plain")


@app.post("/api/compact")
async def compact(request: Request):
    """
    Body: {"messages": [...older history chunk...], "prior_memory": "..."}
    Returns: {"memory": "...updated memory..."}
    Frontend calls this when its history grows past COMPACT_THRESHOLD.
    """
    body = await request.json()
    older = body.get("messages", [])
    prior = body.get("prior_memory", "") or ""
    logger.info(
        "POST /api/compact",
        folding_msgs=len(older),
        prior_mem_chars=len(prior),
    )
    new_memory = await summarize(older, prior_memory=prior)
    return {"memory": new_memory}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
