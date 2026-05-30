import os

import structlog
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

load_dotenv()
logger = structlog.get_logger(__name__)

from mocha.memory import summarize  # noqa: E402
from mocha.openrouter import stream_chat  # noqa: E402
from mocha.prompts import GREETING, SYSTEM_PROMPT  # noqa: E402

# How many recent history messages we keep verbatim in the wire payload.
# Older messages are represented by the memory string only.
KEEP_RECENT = int(os.getenv("KEEP_RECENT", "20"))

app = FastAPI()


@app.get("/api/greeting")
def greeting():
    return {"greeting": GREETING}


def _build_messages(history: list, memory: str) -> list:
    """
    Build the wire payload for the LLM:
        system_prompt + (optional memory-as-system) + last KEEP_RECENT history
    """
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    if memory:
        msgs.append({
            "role": "system",
            "content": f"What you remember from earlier in this chat:\n{memory}",
        })
    # Slice to recent tail. Older context is already folded into memory.
    msgs.extend(history[-KEEP_RECENT:])
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
        "POST /api/chat | turns=%d | mem_chars=%d | sent_turns=%d | last_user=%r",
        len(history), len(memory), min(len(history), KEEP_RECENT), last_user[:80],
    )
    messages = _build_messages(history, memory)
    return StreamingResponse(stream_chat(messages), media_type="text/plain")


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
        "POST /api/compact | folding=%d msgs | prior_mem_chars=%d",
        len(older), len(prior),
    )
    new_memory = await summarize(older, prior_memory=prior)
    return {"memory": new_memory}


app.mount("/", StaticFiles(directory="static", html=True), name="static")
