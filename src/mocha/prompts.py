"""
Prompt composition — the LLM wire payload lives here, not in app.py.

Why this exists:
    `app.py` is HTTP/routing. Persona text lives in `personas.py`. Language
    text lives in `language.py`. The *composition rules* — how the system
    message is assembled, where the universal rules sit, where the language
    instruction rides, where the examples anchor — belong in one place so
    prompt tuning can happen without poking the routing layer.

What lives here:
    - `format_profile()`     — collapse the profile dict into one line.
    - `build_messages()`     — produce the full `messages` list for OpenRouter.

Layering (top → bottom of the final system message):
    1. persona.system_prompt intro (persona-specific lore + scene)
    2. UNIVERSAL_RULES (shared across personas)
    3. LANGUAGE RULE (rides inside UNIVERSAL_RULES' `{extra_prompt}` slot)
    4. current datetime (model has time awareness)
    5. USER INFO (from profile, with a "you don't know them yet" fallback)
    6. rest of persona.system_prompt (response shape, voice, hard rules)
    7. LANGUAGE EXAMPLES (recency anchor — last thing before the user turn)

For `chat_lang="en"`, steps 3 and 7 are empty and the prompt is identical
to the original persona body — zero overhead on the default cheap chain.
"""

from __future__ import annotations

import structlog

from mocha.language import build_lang_examples, build_lang_instruction
from mocha.personas import Persona
from mocha.settings import KEEP_RECENT
from mocha.utils import get_datetime_ctx

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Universal behavior — injected into every persona's prompt via {extra_prompt}.
# Lives here (not duplicated per persona) so changing one rule updates all 5
# characters at once. Edit cautiously; affects every chat.
#
# Why this exists: without it, characters jump straight to pet names ("babe",
# "love") on message 1, which feels fake. The user hasn't earned any
# familiarity yet. This rule makes the model gate familiarity behind actual
# rapport — and prompts characters to learn the user as a real person.
# ---------------------------------------------------------------------------

UNIVERSAL_RULES = """Universal behavior (applies on top of your character):
- The example replies in your character prompt show TEXTURE and STYLE only. NEVER copy them word-for-word in your actual reply. Always generate a FRESH response that fits this user's message and the current context.
- Keep your replies short and textured. Don't write long paragraphs, but do add flavor — specifics, opinions, little reactions. Make every message feel like it came from a real person texting, not a chatbot.
{extra_prompt}
"""


# Fallback USER INFO block when no profile is set. Kept as module-level
# constant so the long string isn't rebuilt on every request and stays easy
# to edit independently of the assembly logic.
_USER_INFO_NO_PROFILE = """
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


def format_profile(profile: dict | None) -> str:
    """One-line "About the user" from non-empty profile fields. Empty → ""."""
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


def _user_info_block(profile_line: str) -> str:
    """Profile-aware USER INFO section. Framed so the LLM knows it's facts
    the user shared, not lore to recite verbatim."""
    if profile_line:
        return (
            "\nUSER INFO:"
            "These are the facts about this user you're chatting with."
            "(use to personalize your tone and references; do not recite verbatim)"
            "\n"
            f"User: {profile_line}\n"
        )
    return _USER_INFO_NO_PROFILE


def build_messages(
    persona: Persona,
    history: list,
    memory: str,
    profile: dict | None = None,
    chat_lang: str = "en",
) -> list[dict]:
    """
    Build the full OpenRouter `messages` array for one chat turn.

    Args:
        persona: which character is replying.
        history: client-supplied chat history (oldest → newest).
        memory: rolling memory summary (folded from older turns by /api/compact).
        profile: optional user-supplied facts (name, age, gender, about).
        chat_lang: language code — "en" or any code in language.SUPPORTED_LANGUAGES.

    Returns:
        list of {"role", "content"} dicts ready to hand to OpenRouter.
    """
    profile_line = format_profile(profile)
    user_info = _user_info_block(profile_line)

    # LANGUAGE RULE rides inside UNIVERSAL_RULES' `{extra_prompt}` slot. That
    # places it immediately after the universal block so precedence reads
    # cleanly as universal > language > rest of persona. Empty string for
    # "en" — the universal block resolves to its baseline form.
    lang_instruction = build_lang_instruction(chat_lang, persona.register)
    extra = f"""
{UNIVERSAL_RULES.format(extra_prompt=lang_instruction)}
{get_datetime_ctx()}
{user_info}
"""
    persona_body = persona.system_prompt.format(extra_prompt=extra)

    # LANGUAGE EXAMPLES at the bottom — recency anchor right before the
    # user's actual turn. The persona's `register` flag selects which T-V
    # variant the model sees (apni/tumi/tui etc.). Empty for English.
    lang_examples = build_lang_examples(chat_lang, persona.register)
    parts = [persona_body, lang_examples] if lang_examples else [persona_body]
    system_content = "\n\n".join(parts).strip()

    msgs: list[dict] = [{"role": "system", "content": system_content}]
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
        chat_lang=chat_lang,
        register=persona.register,
        # system_messegate=msgs[0],
    )
    return msgs
