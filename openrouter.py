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
import logging
import os
import random
import time
from typing import AsyncIterator, List

import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("mocha.openrouter")

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ---- Model catalog ----------------------------------------------------------
# Picks chosen for light moderation + RP-tuned prose. Most provider-hosted
# "free" llamas/gemmas enforce their own filters and refuse mid-spice, so we
# anchor on RP-finetunes (cheap paid) and keep dolphin/venice as a free safety net.
#
# Paid (cheap — built for roleplay, light filtering):
cydonia = "thedrummer/cydonia-24b-v4.1"           # mistral-small uncensored, creative
lunaris = "sao10k/l3-lunaris-8b"                  # cheapest RP tune (~$0.04/M)
euryale = "sao10k/l3.3-euryale-70b"               # higher-quality RP, 131k ctx
lumimaid = "neversleep/llama-3-lumimaid-70b"      # serious RP/eRP balanced
skyfall = "thedrummer/skyfall-36b-v2"             # nuanced RP, mistral-small++

# # Xiomi
# MIMO_2_FLASH = "xiaomi/mimo-v2-flash"  # 0.1/0.3  # tiny brain
# # QWEN
# QWEN_FLASH = "qwen/qwen3.6-flash"  # 0.1/0.3 # reasoning too bad
# # X-AI
# GROK_4_1_FAST = "x-ai/grok-4.1-fast"  # 0.2/0.5
# # OTHERS
# STEP_3_5_FLASH = "stepfun/step-3.5-flash"  # 0.1/0.3
# TENCENT_HY3_PREVIEW = "tencent/hy3-preview"  # 0.66/0.26 # this is shit

#
# Free (rate-limited but truly uncensored):
#
# Old kept for reference / quick swap:
# llama_70b = "meta-llama/llama-3.3-70b-instruct"  # filtered hard by providers
# gemma = "google/gemma-4-31b-it:free"             # provider-filtered
# deepseek = "deepseek/deepseek-v4-flash:free"     # decent, lightly filtered

# Active model — overridable via .env MODEL=...
DEFAULT_MODEL = lunaris

# Tried in order if active fails. Cydonia first (best RP+uncensored),
# Lunaris cheap backup, Dolphin free safety net, Lumimaid as last resort.
FALLBACK_MODELS: List[str] = [
    cydonia,
    lunaris,
    euryale,
    lumimaid,
]

EXTRA_HEADERS = {
    "HTTP-Referer": "http://localhost:8765",
    "X-Title": "Mocha Chat",
}

# ---- Human pacing -----------------------------------------------------------
# Real people don't reply in 0.3s. We add a small "reading+thinking" pause
# before the first chunk goes out, then slow down inter-chunk emission so the
# text appears at roughly human typing speed instead of one firehose blob.
# All values are tunable via .env without touching code.
PACING_ENABLED = os.getenv("PACING_ENABLED", "1") == "1"
# Reading delay: how long to "look at" the user's message before replying.
READ_DELAY_MIN = float(os.getenv("READ_DELAY_MIN", "1.2"))
READ_DELAY_MAX = float(os.getenv("READ_DELAY_MAX", "2.8"))
# Per-character emission delay — ~50ms/char ≈ 200 chars/min ≈ relaxed typing.
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
            data = r.json()
        content = data["choices"][0]["message"]["content"] or ""
        logger.info(
            "complete done | model_requested=%s | model_completion=%s | "
            "provider=%s | usage=%s | chars=%d | elapsed=%ss",
            model, data.get("model"), data.get("provider"),
            data.get("usage"), len(content), round(time.time() - t0, 2),
        )
        return content.strip()
    except Exception as exc:
        logger.warning("complete failed | model=%s | err=%s", model, exc)
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
        "chat start | history_len=%d | chain=%s | temp=%.2f | max_tokens=%d | pacing=%s",
        len(messages), chain, temperature, max_tokens, PACING_ENABLED,
    )

    # Simulate "reading + thinking" before any text appears. Done ONCE per
    # request, before we even try the first model — so swapping models on
    # failure doesn't compound the delay.
    if PACING_ENABLED:
        read_delay = random.uniform(READ_DELAY_MIN, READ_DELAY_MAX)
        logger.debug("read delay=%.2fs", read_delay)
        await asyncio.sleep(read_delay)

    for candidate in chain:
        payload = {
            "model": candidate,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            # Ask OpenRouter to emit a final chunk carrying usage stats so we
            # can log token counts the same way salesbot does for non-stream calls.
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
        logger.info("trying model_requested=%s", candidate)
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
                    "completion done | model_requested=%s | model_completion=%s | "
                    "provider=%s | id=%s | usage=%s | finish=%s | chars=%d | elapsed=%ss",
                    candidate, completion_model, completion_provider, completion_id,
                    usage, finish_reason, char_count, elapsed,
                )
                return  # success — don't try fallbacks
            last_err = RuntimeError(f"{candidate} returned empty stream")
            logger.warning(
                "empty stream | model_requested=%s | model_completion=%s | "
                "provider=%s | elapsed=%ss",
                candidate, completion_model, completion_provider, elapsed,
            )
        except Exception as exc:
            last_err = exc
            elapsed = round(time.time() - t0, 2)
            logger.warning(
                "fail model=%s | elapsed=%ss | err=%s", candidate, elapsed, exc,
            )

        # Reaching here means this candidate failed or gave nothing useful.
        # Tell the UI we're swapping so the user knows what's happening.
        yield f"\n_(swapping model... {candidate} didn't pour)_\n"

    logger.error("all models failed | last_err=%s", last_err)
    yield f"\n💔 all models failed. last error: {last_err}"
