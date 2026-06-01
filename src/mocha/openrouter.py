"""
OpenRouter client — async + streaming via the openai SDK.

Why this file:
- Single place to list candidate models + provider order.
- Two public functions:
    * api_complete_stream() — streams chat replies (used by /api/chat)
    * api_complete()        — non-streaming utility call (used by memory compaction)
- OpenRouter does in-request fallback for us via extra_body={"models": [...],
  "route": "fallback"}. So one HTTP call handles model failover server-side.
  We keep a thin python-side try/except around the whole call only for total
  network/auth failures.

Switch active model:
    Set MODEL in .env to one of the slugs below (or any OpenRouter slug).

Tune the fallback list:
    Edit FALLBACK_MODELS — these are passed to OpenRouter as the in-request
    fallback chain (server-side, fast). Order matters.
"""

import asyncio
import os
import random
import time
from typing import AsyncIterator, List, Literal

import httpx
import structlog
from dotenv import load_dotenv
from openai import AsyncOpenAI
from mocha import settings

load_dotenv()

logger = structlog.get_logger(__name__)

# Why an explicit timeout: OpenRouter's server-side `route=fallback` walks the
# `models` array one-by-one if upstream providers are slow/refusing. That can
# take 20-60s before any bytes flow — especially for niche RP finetunes
# (sao10k, drummer) that run on small providers with cold starts. The openai
# SDK's default is too aggressive for streaming through that chain.
#   connect: 10s  — should be fast; if not, network is down
#   read   : 120s — allow OR fallback chain + slow first-byte to finish
REQUEST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=10.0, pool=10.0)

# Out-of-band error sentinel. The frontend strips anything wrapped in these
# markers from the visible chat and surfaces it as a toast notification.
# Using \x00 keeps it safe from collisions with normal model output.
ERR_OPEN = "\x00MOCHA_ERR\x00"
ERR_CLOSE = "\x00/MOCHA_ERR\x00"


def _err(msg: str) -> str:
    """Wrap an error string so the UI can extract and toast it."""
    return f"{ERR_OPEN}{msg}{ERR_CLOSE}"

async_client = AsyncOpenAI(
    base_url=settings.OPENROUTER_BASE_URL,
    api_key=settings.OPENROUTER_API_KEY,
    timeout=REQUEST_TIMEOUT,
)


# ---- Model catalog ----------------------------------------------------------
# Best Models for Moca (no-mod - Validated by Test)
lunaris = "sao10k/l3-lunaris-8b"                    # 0.04/0.05 zero-mod cheap RP
nemo = "mistralai/mistral-nemo"                     # 0.02/0.03 ⭐ HammerAI top model
gemma = "google/gemma-4-26b-a4b-it"                 # 0.06/0.33 best in banglish

# RP-tuned / less-filtered picks. Prices noted as "input/output USD per 1M".
cydonia = "thedrummer/cydonia-24b-v4.1"             # 0.30/0.50 mistral-small RP
euryale = "sao10k/l3.3-euryale-70b"                 # 0.65/0.75 quality RP
skyfall = "thedrummer/skyfall-36b-v2"               # 0.55/0.80 nuanced RP

# Cheap workhorses (HammerAI's real-world top picks for RP volume).
mistral_small = "mistralai/mistral-small-24b-instruct-2501"  # 0.05/0.08
mytho = "gryphe/mythomax-l2-13b"                    # 0.06/0.06 classic RP
qwen2 = "qwen/qwen-2.5-7b-instruct"                 # 0.04/0.10
deepseek_flash = "deepseek/deepseek-v4-flash"       # 0.10/0.20

# High-moderation (kept for ref / utility tasks like compaction).
mimo = "xiaomi/mimo-v2-flash"                       # 0.10/0.30
qwen = "qwen/qwen3.6-flash"                         # 0.10/0.30
grok = "x-ai/grok-4.1-fast"                         # 0.20/0.50
gpt_oss_20b = "openai/gpt-oss-20b"
owl_alpha = "openrouter/owl-alpha"                  # free

# TESTING BN+MOD
# qwen3_22b = "qwen/qwen3-235b-a22b-2507"             # 0.07/0.1
gemma_31b_free = "google/gemma-4-31b-it:free"
gpt_oss_free = "openai/gpt-oss-120b:free"
deepseek_v4_flash = "deepseek/deepseek-v4-flash" # 0.1/0.2

DEFAULT_MODEL = os.getenv("MODEL", lunaris)
UTILITY_MODEL = os.getenv("UTILITY_MODEL", nemo)
DEFAULT_LOCAL_MODEL = os.getenv("MODEL_LOCAL", gemma_31b_free)

class RouterConfig:
    """Build the extra_body payload OpenRouter expects for routing control."""

    # Provider preference order (top → tried first). Empty = let OpenRouter pick.
    PROVIDERS_PRIORITY: List[str] = []
    PROVIDERS_IGNORED: List[str] = []
    ALLOW_FALLBACKS = True
    QUANTIZATIONS: List[str] = []
    FALLBACK_MODELS: List[str] = [
        lunaris,
        nemo,
        gemma_31b_free,
        deepseek_flash,
        gemma,
        cydonia,
    ]
    FALLBACK_MODELS_UTILITY: List[str] = [
        nemo,
        qwen2,
        deepseek_flash,
    ]
    FALLBACK_MODELS_LOCAL: List[str] = [
        gemma_31b_free,
        gemma,
        gpt_oss_free,
        deepseek_v4_flash,
        nemo,
    ]

    @classmethod
    def build(cls, primary_model: str, mode: Literal["chat", "utility", "local"] = "chat") -> dict:
        """
        Compose extra_body for an OpenRouter call.

        Args:
            primary_model: the model slug we're asking for first.
            mode: which fallback pool to use —
                "chat"    → RP fallback list (English chat).
                "utility" → small/cheap pool for non-streaming utility calls.
                "local"   → multilingual pool for non-English chat.

        Returns:
            dict shaped for `extra_body=` on the openai SDK.
        """
        pool = {
            "chat": cls.FALLBACK_MODELS,
            "utility": cls.FALLBACK_MODELS_UTILITY,
            "local": cls.FALLBACK_MODELS_LOCAL,
        }[mode]
        fallbacks = [m for m in pool if m and m != primary_model][:3]
        body = {
            "models": fallbacks,
            "route": "fallback",
        }
        if cls.PROVIDERS_PRIORITY or cls.PROVIDERS_IGNORED or cls.QUANTIZATIONS:
            body["provider"] = {
                "order": cls.PROVIDERS_PRIORITY,
                "ignore": cls.PROVIDERS_IGNORED,
                "allow_fallbacks": cls.ALLOW_FALLBACKS,
                "quantizations": cls.QUANTIZATIONS,
            }
        return body

    @classmethod
    def get_extra_headers(
        cls,
        url: str = "https://mocha-chat.onrender.com",
        title: str = "Mocha Chat",
    ) -> dict:
        return {
            "HTTP-Referer": url,
            "X-Title": title,
            "X-OpenRouter-Categories": "roleplay",
        }

async def api_complete(
    messages: List[dict],
    model: str = UTILITY_MODEL,
    temperature: float = 0.3,
    max_tokens: int = 400,
    response_format: Literal["text", "json_object"] = "text",
) -> str:
    """
    Non-streaming chat completion — used for utility calls (compaction, etc).

    OpenRouter handles server-side fallback through the `models` array in
    extra_body. We catch only total/network failures here.

    Args:
        messages: full chat-format messages incl. any system prompt.
        model: OpenRouter slug. Defaults to UTILITY_MODEL.
        temperature: low for deterministic-ish utility output.
        max_tokens: cap output.
        response_format: "text" or "json_object" (force-JSON mode).

    Returns:
        The assistant message content as a string. Empty string on failure.

    Example:
        text = await api_complete([
            {"role": "system", "content": "Summarize the chat."},
            {"role": "user", "content": "long history..."},
        ])
    """
    router_config = RouterConfig.build(model, mode="utility")
    t0 = time.time()
    try:
        completion = await async_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": response_format},
            extra_body=router_config,
            extra_headers=RouterConfig.get_extra_headers(),
        )
        content = completion.choices[0].message.content or ""
        logger.info(
            "Completion done",
            model_requested=model,
            model_completion=completion.model,
            provider=getattr(completion, "provider", None),
            usage=completion.usage,
            chars=len(content),
            elapsed=round(time.time() - t0, 2),
            router_config=router_config,
        )
        return content.strip()
    except Exception as exc:
        logger.warning(
            "Completion Failed",
            model=model,
            err=str(exc),
            elapsed=round(time.time() - t0, 2),
        )
        return ""


async def api_complete_stream(
    messages: List[dict],
    model: str = DEFAULT_MODEL,
    temperature: float = 0.7,
    max_tokens: int = 500,
    mode: Literal["chat", "local"] = "chat",
) -> AsyncIterator[str]:
    """
    Streaming chat completion — used for the user-facing chat reply.

    OpenRouter handles model fallback server-side via the `models` array
    in extra_body, so this is a single HTTP request even if the primary
    model fails (no retry loop here). On a hard failure (network/auth),
    we yield a small error sentinel so the UI shows something.

    Args:
        messages: chat-format messages incl. system prompt as first entry.
        model: primary model slug (OpenRouter).
        temperature: higher = more playful/varied (0.9 chatty default).
        max_tokens: cap per response.
        mode: "chat" for English (cheap RP chain), "local" for non-English
            (multilingual chain led by Gemma). Caller picks based on chat_lang.

    Yields:
        Text chunks (str) as they arrive. Pacing is applied if enabled.
    """
    read_delay = 0
    router_config = RouterConfig.build(model, mode=mode)
    if settings.PACING_ENABLED:
        read_delay = random.uniform(settings.READ_DELAY_MIN, settings.READ_DELAY_MAX)
        await asyncio.sleep(read_delay)
    logger.info(
        "[Stream Completion] start",
        model_requested=model,
        fallbacks=router_config["models"],
        temperature=temperature,
        max_tokens=max_tokens,
        pacing=settings.PACING_ENABLED,
        read_delay=round(read_delay, 2),
        # messages=str(messages)[:500],
    )

    # Captured from stream chunks for the final summary log.
    completion_model: str | None = None
    completion_provider: str | None = None
    completion_id: str | None = None
    usage = None
    finish_reason: str | None = None
    got_any = False
    char_count = 0
    t0 = time.time()

    try:
        stream = await async_client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            # include_usage = OpenRouter emits a final chunk carrying token usage.
            stream_options={"include_usage": True},
            extra_body=router_config,
            extra_headers=RouterConfig.get_extra_headers(),
        )
        async for chunk in stream:
            # Metadata appears on every chunk; last-write-wins is fine.
            completion_id = chunk.id or completion_id
            completion_model = chunk.model or completion_model
            completion_provider = getattr(chunk, "provider", None) or completion_provider
            if chunk.usage:
                usage = chunk.usage

            if not chunk.choices:
                continue
            choice0 = chunk.choices[0]
            if choice0.finish_reason:
                finish_reason = choice0.finish_reason
            delta = (choice0.delta.content or "") if choice0.delta else ""
            if delta:
                got_any = True
                char_count += len(delta)
                # Emit char-by-char with a small sleep so the UI paints like a
                # person typing instead of a paste blob.
                if settings.PACING_ENABLED and settings.TYPE_DELAY_PER_CHAR > 0:
                    for ch in delta:
                        yield ch
                        await asyncio.sleep(settings.TYPE_DELAY_PER_CHAR)
                else:
                    yield delta

        elapsed = round(time.time() - t0, 2)
        if got_any:
            logger.info(
                "[Stream Completion] done",
                model_requested=model,
                model_completion=completion_model,
                provider=completion_provider,
                id=completion_id,
                # usage=usage,
                finish=finish_reason,
                chars=char_count,
                elapsed=elapsed,
            )
            return
        logger.warning(
            "[Stream Completion] Empty Stream",
            model_requested=model,
            model_completion=completion_model,
            provider=completion_provider,
            elapsed=elapsed,
        )
        yield _err("model returned empty. try again?")
    except Exception as exc:
        logger.error(
            "[Stream Completion] Failed",
            model=model,
            err=str(exc),
            elapsed=round(time.time() - t0, 2),
        )
        yield _err(f"stream failed — {exc}")


def show_ratelimit():
    import requests
    payload = {
        "url": "https://openrouter.ai/api/v1/key",
        "headers": {
            "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}"
        }
    }
    response = requests.get(**payload)
    return response.json()
