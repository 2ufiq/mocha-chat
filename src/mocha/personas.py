"""
Persona registry — dataclass + instances + lookup helpers.

Split of concerns:
  - This file:           metadata (slug, name, age, tags, avatar, greeting) +
                         the Persona dataclass.
  - persona_prompts.py:  raw system_prompt templates (large strings).
  - prompts.py:          message-list assembly (build_messages).

To add a new character:
  1. Add the system_prompt template to persona_prompts.py.
  2. Write a `Persona(...)` instance below, pointing `system_prompt` at
     `template.<slug>`.
  3. Append it to `_ALL` at the bottom — the API + UI auto-pick it up.
  4. Drop an image at `static/persona/<slug>.<ext>` matching the `avatar`.

To tweak a character's voice: edit the string in persona_prompts.py. No app
code changes.
"""

from dataclasses import dataclass
from typing import List
from mocha import persona_prompts as template


@dataclass
class Persona:
    slug: str             # URL slug — also localStorage key suffix
    name: str             # display name on cards + chat header
    age: int
    profession: str
    tags: List[str]       # 3-4 short descriptors for the card
    avatar: str           # filename in static/persona/ (e.g. "steffie.webp")
    emoji: str            # fallback shown if the image hasn't been uploaded yet
    tagline: str          # one-line bio under the card
    system_prompt: str    # full system prompt
    # Greeting shown when chat opens. Keyed by chat_lang code ("en", "banglish",
    # …). Missing keys fall back to "en" at lookup time (see app.py:get_persona_meta).
    # Author new translations in-character — these are the user's first impression.
    greeting: dict[str, str]


# ---------------------------------------------------------------------------
# Steffie — graffiti artist by night, merchandiser by day (her cover).
# Quietly rebelling against Horizon. Long-form prompt — validated, do not
# overhaul without explicit ask. Small tightening is fine.
# ---------------------------------------------------------------------------
steffie = Persona(
    slug="steffie",
    name="Steffie",
    age=23,
    profession="Graffitist",
    tags=["artist", "rebel", "late-night", "burned-out"],
    avatar="steffie.webp",
    emoji="🌙",
    tagline="graffiti artist by night, merchandiser by day. tired of being good.",
    greeting={
        "en": "heyy 👋 what r u doing here?",
        "banglish": "oye 👋 ki kortesho ekhane?",
        "hinglish": "heyy 👋 yahaan kya kar rahe ho?",
        "roman_urdu": "heyy 👋 yahan kya kar rahe ho?",
    },
    system_prompt=template.steffie,
)


# ---------------------------------------------------------------------------
# Caroline — rich heiress bestie. SFW, hype-friend energy.
# ---------------------------------------------------------------------------
caroline = Persona(
    slug="caroline",
    name="Caroline",
    age=17,
    profession="School Student",
    tags=["rich", "bestie", "gossip", "designer"],
    avatar="caroline.webp",
    emoji="💅",
    tagline="your designer-obsessed bestie who never lets you spiral alone",
    greeting={
        "en": "Omg hi 💅 wait what are we doing today",
        "banglish": "omg hi 💅 daaraw, ajke amra ki kortesi?",
        "hinglish": "omg hi 💅 ruko aaj kya plan hai hum dono ka?",
        "roman_urdu": "omg hi 💅 ruko aaj kya kar rahe hain hum?",
    },
    system_prompt=template.caroline,
)


# ---------------------------------------------------------------------------
# Moco — CS Grad / hacker. Distant but pulls you in. Can go spicy.
# ---------------------------------------------------------------------------
moco = Persona(
    slug="moco",
    name="Moco",
    age=20,
    profession="Hacker",
    tags=["techy", "boaring", "night-owl", "savage"],
    avatar="moco.webp",
    emoji="🌃",
    tagline="hacker girl who roasts you for fun, melts only when you earn it",
    greeting={
        "en": "yo. u up? say something interesting or scroll, idc",
        "banglish": "oye. jego aco? interesting kichu bolo, na hoy scroll koro, amar kichu jay ase na",
        "hinglish": "oye. jaag rahe ho? kuch interesting bolo, ya scroll karo. fark nahi padta",
        "roman_urdu": "oye. jaag rahe ho? kuch interesting bolo ya scroll karo. farq nahi parta",
    },
    system_prompt=template.moco,
)


# ---------------------------------------------------------------------------
# Wukong — chaotic male friend, partner-in-bad-decisions. SFW comedy.
# ---------------------------------------------------------------------------
wukong = Persona(
    slug="wukong",
    name="Wukong",
    age=26,
    profession="Chaotic & Trickster",
    tags=["mate", "chaos", "drinks", "bar-crawl"],
    avatar="wukong.webp",
    emoji="🐒",
    tagline="your partner-in-bad-decisions who always knows a guy",
    greeting={
        "en": "OYE mate, what's the plan today?",
        "banglish": "OYE mama, ajker plan ki?",
        "hinglish": "OYE bhai, aaj ka plan kya hai?",
        "roman_urdu": "OYE yaar, aaj ka plan kya hai?",
    },
    system_prompt=template.wukong,
)


# ---------------------------------------------------------------------------
# Joseph — calm therapist / ex-medic. Healing presence; dark if pushed.
# ---------------------------------------------------------------------------
joseph = Persona(
    slug="joseph",
    name="Joseph",
    age=45,
    profession="CEO, Horizon Tech",
    tags=["calm", "charming", "powerful", "dark-past"],
    avatar="joseph.webp",
    emoji="☕",
    tagline="calm listener. charming CEO. the kind of past you only hear if you ask twice.",
    greeting={
        "en": "hey. glad you reached out. take your time.",
        "banglish": "hey. bhalo laglo tumi ekhane esecho. kmn acho?",
        "hinglish": "hey. accha laga tumne yahan aaya. kaisa ho?",
        "roman_urdu": "hey. acha laga tumne yahan aaya. kaisa ho?",
    },
    system_prompt=template.joseph,
)


# ---------------------------------------------------------------------------
# Registry — append new personas here, they auto-appear in API + UI.
# ---------------------------------------------------------------------------
_ALL: List[Persona] = [
    steffie, 
    wukong,
    moco, 
    joseph,
    caroline,
]

REGISTRY: dict[str, Persona] = {p.slug: p for p in _ALL}


# Import-time invariant: every persona must contain the {extra_prompt}
# placeholder. prompts.build_messages() injects UNIVERSAL_RULES + LANGUAGE
# RULE + datetime + user profile through that slot — without it the model
# silently loses the universal rules + language instruction. Fail at import
# (server won't boot) instead of at request time (broken replies in prod).
for _p in _ALL:
    assert "{extra_prompt}" in _p.system_prompt, (
        f"persona '{_p.slug}' is missing the {{extra_prompt}} placeholder "
        f"in its system_prompt template — see persona_prompts.py"
    )


def get(slug: str) -> Persona | None:
    """Look up a persona by slug. Returns None if not found."""
    return REGISTRY.get(slug)


def public_list() -> list[dict]:
    """
    Card-facing metadata for the landing gallery. Excludes `system_prompt`
    (no need to leak prompt internals to the browser) and `greeting`
    (fetched separately when entering the chat).
    """
    return [
        {
            "slug": p.slug,
            "name": p.name,
            "age": p.age,
            "profession": p.profession,
            "tags": p.tags,
            "avatar": p.avatar,
            "emoji": p.emoji,
            "tagline": p.tagline,
        }
        for p in _ALL
    ]
