"""
Thin async wrapper around `googletrans`.

Why googletrans (vs LLM-based translation):
- LLMs (especially safety-tuned ones) refuse to translate explicit content,
  which is exactly when users need this button most in this app.
- googletrans is a dumb pipe — no content judgment, just text in/out.
- Tradeoff: it scrapes Google's web endpoint and is FLAKY. We retry once
  on transient failure, then surface the error.

Public function:
    translate(text, target) -> str   # raises on failure
"""

import asyncio
import structlog
from googletrans import Translator

logger = structlog.get_logger(__name__)


async def translate(text: str, target: str = "bn", source: str = "auto") -> str:
    """
    Translate `text` into `target` language. Retries once on failure because
    googletrans transient errors are common (Google web endpoint reshuffles).

    Args:
        text: source text. Up to ~5000 chars per call.
        target: ISO 639-1 destination code (e.g. "bn", "hi", "id", "ms").
        source: ISO 639-1 source code, or "auto" for autodetection.

    Returns:
        Translated string.

    Raises:
        RuntimeError with a useful message — caller (FastAPI route) surfaces
        it to the UI via toast.
    """
    if not text or not text.strip():
        return ""

    last_err: Exception | None = None
    for attempt in (1, 2):
        try:
            async with Translator() as translator:
                result = await translator.translate(text, src=source, dest=target)
            logger.info(
                "translate ok",
                attempt=attempt,
                target=target,
                source=source,
                in_chars=len(text),
                out_chars=len(result.text),
            )
            return result.text
        except Exception as exc:
            last_err = exc
            logger.warning(
                "translate attempt failed",
                attempt=attempt,
                err_type=type(exc).__name__,
                err=str(exc) or repr(exc),
            )
            if attempt == 1:
                await asyncio.sleep(0.4)

    # Both attempts failed — surface a useful message. Empty `str(exc)` is
    # common with googletrans internals, so we fall back to the class name.
    msg = str(last_err) or type(last_err).__name__ if last_err else "unknown error"
    raise RuntimeError(f"googletrans: {msg}")
