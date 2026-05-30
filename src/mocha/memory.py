"""
Conversation compaction.

Why this exists:
- Full history sent every turn = O(N²) token cost.
- We fold older turns into a short "memory" summary and keep only the recent
  ones verbatim. Wire payload becomes: system + memory + last KEEP_RECENT msgs.

Public function:
    summarize(messages, prior_memory) -> new_memory_str

The frontend calls /api/compact when its local history grows past
COMPACT_THRESHOLD and stores the returned memory string in localStorage.
"""

import os
from typing import List

import structlog

from mocha.openrouter import UTILITY_MODEL, api_complete

logger = structlog.get_logger(__name__)

# Which model summarizes. Cheap/fast is fine — accuracy doesn't need to be perfect.
COMPACT_MODEL = os.getenv("COMPACT_MODEL", UTILITY_MODEL)

SUMMARIZER_PROMPT = """You are a memory writer for an ongoing chat between Mocha
(a sylheti girl in dhaka) and a user she just met online.

Given the prior memory (may be empty) and the new conversation chunk, write an
UPDATED memory in third person, ≤200 tokens, plain prose, no headings.

Capture:
- key facts about the user (name, where they're from, work, anything they shared)
- the vibe/tone so far (cold, warm, flirty, joking) and how things have progressed
- any callbacks Mocha should remember (inside jokes, things teased, plans floated)

Do NOT include:
- verbatim quotes
- the raw greeting / small talk filler
- meta commentary about being an AI

Output just the memory text. No preamble."""


async def summarize(messages: List[dict], prior_memory: str = "") -> str:
    """
    Fold a chunk of older messages into an updated memory string.

    Args:
        messages: list of {"role": "user"|"assistant", "content": str} —
            the older portion of history being compacted (NOT the recent verbatim tail).
        prior_memory: the previous memory string, or "" if this is the first compaction.

    Returns:
        New memory string (≤~200 tokens). Empty string on LLM failure.

    Example:
        new_mem = await summarize(history[:-10], prior_memory=existing_memory)
    """
    if not messages:
        return prior_memory

    # Render the chunk as a transcript so the summarizer sees turn structure clearly.
    transcript_lines = []
    for m in messages:
        who = "User" if m.get("role") == "user" else "Mocha"
        transcript_lines.append(f"{who}: {m.get('content', '')}")
    transcript = "\n".join(transcript_lines)

    user_block = (
        f"Prior memory:\n{prior_memory or '(none yet)'}\n\n"
        f"New conversation chunk to fold in:\n{transcript}\n\n"
        "Write the updated memory now."
    )

    out = await api_complete(
        messages=[
            {"role": "system", "content": SUMMARIZER_PROMPT},
            {"role": "user", "content": user_block},
        ],
        model=COMPACT_MODEL,
        temperature=0.2,
        max_tokens=300,
    )
    logger.info(
        "Compacted",
        folded_msgs=len(messages),
        prior_len=len(prior_memory),
        new_len=len(out),
    )
    return out or prior_memory
