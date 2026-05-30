"""
Tiny OpenRouter client with fallback.

Why this file:
- One place to list the models you want to try.
- If the active model errors, refuses, or times out → fall back to the next.
- `stream_chat()` is what app.py calls — yields text chunks as they arrive.

Switch active model:
    Set MODEL in .env to one of the slugs below (e.g. MODEL=z-ai/glm-4.5-air:free)
    OR just edit DEFAULT_MODEL.

Change the fallback order:
    Edit FALLBACK_MODELS.
"""

import asyncio
import json
import os
import random
import time
from typing import AsyncIterator, List

import httpx
import structlog
from dotenv import load_dotenv

load_dotenv()

logger = structlog.get_logger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ---- Model catalog ----------------------------------------------------------
# Paid (cheap — built for roleplay, light filtering):
cydonia = "thedrummer/cydonia-24b-v4.1"           # 0.30/0.50
lunaris = "sao10k/l3-lunaris-8b"                  # 0.04/0.05 # zero mod
euryale = "sao10k/l3.3-euryale-70b"               # 0.65/0.75
skyfall = "thedrummer/skyfall-36b-v2"             # 0.55/0.80
# ----------------------------High Moderation------------------------------------
mimo = "xiaomi/mimo-v2-flash"                     # 0.10/0.30
qwen = "qwen/qwen3.6-flash"                       # 0.10/0.30
groq = "x-ai/grok-4.1-fast"                       # 0.20/0.50
stepfun = "stepfun/step-3.5-flash"                # 0.10/0.30
hy3 = "tencent/hy3-preview"                       # 0.66/0.26
# ------------- Unecplored----------
nemo = "mistralai/mistral-nemo" # 0.02/0.03
mistral_small = "mistralai/mistral-small-24b-instruct-2501" # 0.05/0.08
deepseek = "deepseek/deepseek-v3.2" # 0.25/0.40
mytho = "gryphe/mythomax-l2-13b" # 0.06/0.06
qwen2 = "qwen/qwen-2.5-7b-instruct" # 0.04/0.10
deepseek_flash = "deepseek/deepseek-v4-flash" # 0.10/0.20

DEFAULT_MODEL = os.getenv("MODEL", lunaris)

FALLBACK_MODELS: List[str] = [
    lunaris,
    nemo,
    mytho,
    qwen2,
    deepseek_flash,
    mistral_small,
]

EXTRA_HEADERS = {
    "HTTP-Referer": "http://localhost:8765",
    "X-Title": "Mocha Chat",
}


PACING_ENABLED = os.getenv("PACING_ENABLED", "1") == "1"
READ_DELAY_MIN = float(os.getenv("READ_DELAY_MIN", "1.2"))
READ_DELAY_MAX = float(os.getenv("READ_DELAY_MAX", "2.8"))
TYPE_DELAY_PER_CHAR = float(os.getenv("TYPE_DELAY_PER_CHAR", "0.045"))


def _build_chain(model: str) -> List[str]:
    """Active model first, then fallbacks. Dedupes while preserving order."""
    seen = set()
    chain = []
    for m in [model, *FALLBACK_MODELS]:
        if m and m not in seen:
            chain.append(m)
            seen.add(m)
    return chain


async def complete(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 400,
) -> str:
    """
    Non-streaming chat completion — used for short utility calls like compaction.

    Args:
        messages: chat-format messages incl. any system prompt.
        model: OpenRouter slug. Defaults to active model.
        temperature: low for utility calls (summaries should be deterministic-ish).
        max_tokens: cap output.

    Returns:
        The assistant message content as a single string. Empty string on failure.

    Example:
        text = await complete([
            {"role": "system", "content": "Summarize."},
            {"role": "user", "content": "long chat..."},
        ])
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        **EXTRA_HEADERS,
    }
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
            r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
            r.raise_for_status()
            completion = r.json()
        content = completion["choices"][0]["message"]["content"] or ""
        logger.info(
            "Completion Done", 
            model_requested=model, 
            model_completion=completion.get("model"),
            provider=completion.get("provider"), 
            usage=completion.get("usage"),
            chars=len(content), 
            elapsed=round(time.time() - t0, 2),
        )
        return content.strip()
    except Exception as exc:
        logger.warning("Completion Failed", model=model, err=exc)
        return ""


async def stream_chat(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.9,
    max_tokens: int = 1000,
) -> AsyncIterator[str]:
    """
    Stream a chat completion, falling back through FALLBACK_MODELS on failure.

    Args:
        messages: full chat history incl. the system prompt as first entry.
        model: primary model slug (OpenRouter).
        temperature: higher = more playful/varied (0.9 is a good chatty default).
        max_tokens: cap per response.

    Yields:
        Text chunks (str) as they arrive.

    Example:
        async for chunk in stream_chat([
            {"role": "system", "content": "be cheeky"},
            {"role": "user", "content": "hi"},
        ]):
            print(chunk, end="")
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        **EXTRA_HEADERS,
    }
    last_err: Exception | None = None
    chain = _build_chain(model)
    logger.info(
        "stream_chat start", 
        model_requested=model, 
        chain=chain, 
        temperature=temperature, 
        max_tokens=max_tokens, 
        pacing=PACING_ENABLED
    )

    if PACING_ENABLED:
        read_delay = random.uniform(READ_DELAY_MIN, READ_DELAY_MAX)
        logger.debug("read delay", seconds=round(read_delay, 2))
        await asyncio.sleep(read_delay)

    for candidate in chain:
        payload = {
            "model": candidate,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        got_any = False
        char_count = 0
        # Captured from stream chunks — populated as data arrives.
        completion_model: str | None = None  # what provider actually served
        completion_provider: str | None = None
        completion_id: str | None = None
        usage: dict | None = None
        finish_reason: str | None = None
        t0 = time.time()
        logger.info("trying model", model_requested=candidate)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                async with client.stream(
                    "POST", OPENROUTER_URL, headers=headers, json=payload
                ) as r:
                    if r.status_code >= 400:
                        body = await r.aread()
                        raise RuntimeError(
                            f"{candidate} HTTP {r.status_code}: {body[:200]!r}"
                        )

                    async for line in r.aiter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data = line[6:]
                        if data == "[DONE]":
                            break
                        try:
                            obj = json.loads(data)
                        except Exception:
                            continue

                        # These appear on every chunk; last-write-wins is fine.
                        completion_id = obj.get("id") or completion_id
                        completion_model = obj.get("model") or completion_model
                        completion_provider = obj.get("provider") or completion_provider
                        # Usage arrives in the final chunk when include_usage=True.
                        if obj.get("usage"):
                            usage = obj["usage"]

                        choices = obj.get("choices") or []
                        if not choices:
                            continue
                        choice0 = choices[0]
                        if choice0.get("finish_reason"):
                            finish_reason = choice0["finish_reason"]
                        delta = (choice0.get("delta") or {}).get("content", "")
                        if delta:
                            got_any = True
                            char_count += len(delta)
                            # Emit one char at a time at typing speed so the UI
                            # paints like a person typing, not a paste.
                            if PACING_ENABLED and TYPE_DELAY_PER_CHAR > 0:
                                for ch in delta:
                                    yield ch
                                    await asyncio.sleep(TYPE_DELAY_PER_CHAR)
                            else:
                                yield delta

            elapsed = round(time.time() - t0, 2)
            if got_any:
                logger.info(
                    "Completion Done",
                    model_requested=candidate,
                    model_completion=completion_model,
                    provider=completion_provider,
                    id=completion_id,
                    usage=usage,
                    finish=finish_reason,
                    chars=char_count,
                    elapsed=elapsed,
                )
                return  # success — don't try fallbacks
            last_err = RuntimeError(f"{candidate} returned empty stream")
            logger.warning(
                "Empty Stream",
                model_requested=candidate,
                model_completion=completion_model,
                provider=completion_provider,
                elapsed=elapsed,
            )
        except Exception as exc:
            last_err = exc
            elapsed = round(time.time() - t0, 2)
            logger.warning(
                "Stream Failed",
                model=candidate,
                elapsed=elapsed,
                err=exc,
            )

        # Reaching here means this candidate failed or gave nothing useful.
        # Tell the UI we're swapping so the user knows what's happening.
        yield f"\n_(swapping model... {candidate} didn't pour)_\n"

    logger.error("All Models Failed", last_err=last_err)
    yield f"\n💔 all models failed. last error: {last_err}"
