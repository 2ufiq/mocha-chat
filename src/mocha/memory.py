"""
Conversation compaction.

Why this exists:
- Full history sent every turn = O(N²) token cost.
- We fold older turns into a short "memory" summary and keep only the recent
  ones verbatim. Wire payload becomes: system + memory + last KEEP_RECENT msgs.

Public function:
    summarize(messages, prior_memory, persona_name) -> new_memory_str

The frontend calls /api/compact when its local history grows past
COMPACT_THRESHOLD and stores the returned memory string in localStorage,
keyed per-persona slug.
"""

import os
from typing import List

import structlog

from mocha.openrouter import UTILITY_MODEL, api_complete

logger = structlog.get_logger(__name__)

# Which model summarizes. Cheap/fast is fine — accuracy isn't critical.
COMPACT_MODEL = os.getenv("COMPACT_MODEL", UTILITY_MODEL)

# Templated so each persona's summary uses their actual name. Same shape
# works across Mocha, Caroline, Moco, Wukong, Joseph — the persona doesn't
# need a tailored summarizer prompt; the chat content carries the vibe.
SUMMARIZER_PROMPT_TEMPLATE = """You are a memory writer for an ongoing chat between {name}
(an AI character) and a user. Given the prior memory (may be empty) and a new
conversation chunk, write an UPDATED memory in third person, ≤200 tokens,
plain prose, no headings.

Capture:
- key facts about the user (name, where they're from, work, anything shared)
- the vibe/tone so far (cold, warm, flirty, joking) and how things progressed
- any callbacks {name} should remember (inside jokes, things teased, plans floated)

Do NOT include:
- verbatim quotes
- the raw greeting / small talk filler
- meta commentary about being an AI

Output just the memory text. No preamble."""


async def summarize(
    messages: List[dict],
    prior_memory: str = "",
    persona_name: str = "the assistant",
) -> str:
    """
    Fold a chunk of older messages into an updated memory string.

    Args:
        messages: the older portion of history being compacted (NOT the recent tail).
        prior_memory: previous memory string, or "" if first compaction.
        persona_name: display name of the character — used in the summary
            so the memory reads naturally and labels turns correctly.

    Returns:
        New memory string (≤~200 tokens). Falls back to prior_memory on failure.
    """
    if not messages:
        return prior_memory

    # Render the chunk as a labelled transcript so the summarizer sees turns clearly.
    transcript_lines = []
    for m in messages:
        who = "User" if m.get("role") == "user" else persona_name
        transcript_lines.append(f"{who}: {m.get('content', '')}")
    transcript = "\n".join(transcript_lines)

    user_block = (
        f"Prior memory:\n{prior_memory or '(none yet)'}\n\n"
        f"New conversation chunk to fold in:\n{transcript}\n\n"
        "Write the updated memory now."
    )

    out = await api_complete(
        messages=[
            {
                "role": "system",
                "content": SUMMARIZER_PROMPT_TEMPLATE.format(name=persona_name),
            },
            {"role": "user", "content": user_block},
        ],
        model=COMPACT_MODEL,
        temperature=0.2,
        max_tokens=300,
    )
    logger.info(
        "Compacted",
        persona=persona_name,
        folded_msgs=len(messages),
        prior_len=len(prior_memory),
        new_len=len(out),
    )
    return out or prior_memory
