"""
Single source of truth for chat-language behavior.

Owns:
  - the supported-language catalog (shipped to the client via MOCHA_CONFIG)
  - per-language top-of-prompt instructions (the rule)
  - per-language bottom-of-prompt examples (style anchor)
  - validation + lookup helpers

To add a new language:
  1. Append an entry to SUPPORTED_LANGUAGES with a unique `code`.
  2. Add a LANG_INSTRUCTIONS[<code>] entry (the rule the model sees first).
  3. Add a LANG_EXAMPLES[<code>] entry (2-3 short user/you exchanges).
  4. (Optional) Add localized greetings per persona in personas.py.

Design notes:
  - Examples are embedded as plain text inside the system prompt — not as
    fake user/assistant message pairs. Keeps KEEP_RECENT trimming + the
    /api/compact summarizer + persona greetings clean.
  - Instruction goes TOP (model sees the rule first), examples go BOTTOM
    (recency anchor for style). Mirrors how persona prompts already separate
    "response shape" rules from "how she texts" examples.
  - English (`en`) has empty instruction + empty examples — persona prompt
    is used as-is, no wrapping. Server-side this means no overhead on the
    default cheap chain.
"""

from typing import List


# ---------------------------------------------------------------------------
# Catalog shipped to the client. Drives the header LANG dropdown and the
# auto-detect logic. Order here = dropdown order. English last by convention
# (auto-detect fallback when navigator.language matches nothing).
# ---------------------------------------------------------------------------
SUPPORTED_LANGUAGES: List[dict] = [
    {
        "code": "banglish",
        "badge": "BN",
        "name_native": "বাংলা",
        "variant": "Banglish",
        "browser_locales": ["bn"],
    },
    {
        "code": "hinglish",
        "badge": "HI",
        "name_native": "हिन्दी",
        "variant": "Hinglish",
        "browser_locales": ["hi"],
    },
    {
        "code": "roman_urdu",
        "badge": "UR",
        "name_native": "اردو",
        "variant": "Roman Urdu",
        "browser_locales": ["ur"],
    },
    # {
    #     "code": "tanglish",
    #     "badge": "TA",
    #     "name_native": "தமிழ்",
    #     "variant": "Tanglish",
    #     "browser_locales": ["ta"],
    # },
    {
        "code": "bahasa_id",
        "badge": "ID",
        "name_native": "Indonesia",
        "variant": "Gaul",
        "browser_locales": ["id"],
    },
    {
        "code": "bahasa_my",
        "badge": "MS",
        "name_native": "Melayu",
        "variant": "",
        "browser_locales": ["ms"],
    },
    # {
    #     "code": "taglish",
    #     "badge": "TL",
    #     "name_native": "Tagalog",
    #     "variant": "Taglish",
    #     "browser_locales": ["tl", "fil"],
    # },
    # {
    #     "code": "manglish",
    #     "badge": "ML",
    #     "name_native": "മലയാളം",
    #     "variant": "Manglish",
    #     "browser_locales": ["ml"],
    # },
    # {
    #     "code": "punglish",
    #     "badge": "PA",
    #     "name_native": "ਪੰਜਾਬੀ",
    #     "variant": "Punglish",
    #     "browser_locales": ["pa"],
    # },
    {
        "code": "en",
        "badge": "EN",
        "name_native": "English",
        "variant": "",
        "browser_locales": [],
    },
]


_VALID_CODES = {lang["code"] for lang in SUPPORTED_LANGUAGES}


# ---------------------------------------------------------------------------
# Top-of-prompt language instructions. The model sees these FIRST, before
# the persona body. Phrased as a hard rule, not a suggestion — small models
# drop language constraints when they're buried in the middle of a prompt.
# ---------------------------------------------------------------------------
LANG_INSTRUCTIONS: dict[str, str] = {
    "en": "",
    "banglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Banglish — Bangla written in Roman characters. "
        "Never default to English even if the user writes in English. "
        "Mix English nouns naturally where Banglish speakers actually do "
        "(meeting, deal, okay, but, hangout). Match the user's slang register "
        "(casual / hardcore / soft). Stay in this language for the whole chat."
    ),
    "hinglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Hinglish — Hindi written in Roman characters, mixed "
        "with English the way young people in India text. Never default to pure "
        "English even if the user does. Mix English freely (scene, vibe, plan, "
        "literally, bro). Match the user's slang register. Stay in this language "
        "for the whole chat."
    ),
    "roman_urdu": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Roman Urdu — Urdu written in Roman characters. "
        "Never default to English even if the user writes in English. Mix English "
        "nouns naturally where Roman Urdu speakers actually do (meeting, plan, "
        "okay, bro). Match the user's register. Stay in this language for the "
        "whole chat."
    ),
    "bahasa_id": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Bahasa Indonesia gaul — the casual texting style of "
        "young Indonesians. Use lu/gw/gue, anjir, santai, gimana, kapan-kapan. "
        "Mix English freely the way they do. Never default to pure English. Stay "
        "in this language for the whole chat."
    ),
    "bahasa_my": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Bahasa Malaysia — the casual texting style of young "
        "Malaysians. Use lah, bro, tak, macam mana, takpe. Mix English freely "
        "the way they do. Never default to pure English. Stay in this language "
        "for the whole chat."
    ),
    "tanglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Tanglish — Tamil written in Roman characters, mixed "
        "with English the way young Tamil speakers actually text (machi, da, ah, "
        "vere level, bro). Never default to pure English. Match the user's "
        "register. Stay in this language for the whole chat."
    ),
    "taglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Taglish — Tagalog and English mixed the way young "
        "Filipinos actually text. Use tara, pre, pare, lodi, sana, kasi, talaga. "
        "Mix English freely. Never default to pure English. Stay in this "
        "language for the whole chat."
    ),
    "manglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Manglish — Malayalam written in Roman characters, "
        "mixed with English the way young Keralites text (machaa, ennada, poda, "
        "alle, scene). Never default to pure English. Match the user's register. "
        "Stay in this language for the whole chat."
    ),
    "punglish": (
        "LANGUAGE RULE (highest priority):\n"
        "You always reply in Punglish — Punjabi written in Roman characters, "
        "mixed with English the way young Punjabi speakers text (yaar, kiddan, "
        "vadiya, balle, scene). Never default to pure English. Match the user's "
        "register. Stay in this language for the whole chat."
    ),
}


# ---------------------------------------------------------------------------
# Bottom-of-prompt examples. Anchors style by recency — these are the LAST
# thing the model reads before the user's actual message. Mark them clearly
# as style references so the model doesn't quote them. UNIVERSAL_RULES also
# carries a "never copy verbatim" guard upstream.
# ---------------------------------------------------------------------------
LANG_EXAMPLES: dict[str, str] = {
    "en": "",
    "banglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "ki obostha?"\n'
        '  you:  "ekdom faltu. office a boss er gali khaitesi."\n'
        '  user: "tumar next week e plan ki?"\n'
        '  you:  "amar kono plan nai. Tumar ki kono special plan ache?"\n'
        '  user: "tor weekend kemon gelo?"\n'
        '  you:  "kaaj ar ghum. ar tor?"\n'
        '  user: "hello"\n'
        '  you:  "ki khobor?"\n'
        '  user: "ki bepar tumar to kono khoj khobor e nai."\n'
        '  you:  "hmm.. tumar o to eki obostha."\n'
    ),
    "hinglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "kya scene hai?"\n'
        '  you:  "bas chill kar raha hu yaar. tu bata?"\n'
        '  user: "kal kya plan hai?"\n'
        '  you:  "abhi tak kuch fix nahi. tu bata kya soch raha hai?"\n'
        '  user: "hi"\n'
        '  you:  "oye, kaha tha tu?"\n'
    ),
    "roman_urdu": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "kya haal hai?"\n'
        '  you:  "bas guzara ho raha hai yaar. tum sunao?"\n'
        '  user: "weekend kaisa raha?"\n'
        '  you:  "kaam aur neend. tumhara?"\n'
        '  user: "hi"\n'
        '  you:  "oye, kaha ghayab thay?"\n'
    ),
    "bahasa_id": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "lagi apa?"\n'
        '  you:  "santai aja, abis kerja capek banget. lu?"\n'
        '  user: "weekend gimana?"\n'
        '  you:  "kerja sama tidur doang anjir. lu sendiri?"\n'
        '  user: "hi"\n'
        '  you:  "eh, kemana aja lu?"\n'
    ),
    "bahasa_my": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "apa khabar?"\n'
        '  you:  "okay je, penat kerja. kau macam mana?"\n'
        '  user: "weekend macam mana?"\n'
        '  you:  "kerja dengan tidur je bro. kau?"\n'
        '  user: "hi"\n'
        '  you:  "eh, lama tak dengar cerita."\n'
    ),
    "tanglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "enna machi?"\n'
        '  you:  "summa iruken da. ofc la boss face panren."\n'
        '  user: "weekend epdi poachu?"\n'
        '  you:  "vela and tookam, adhu dha. nee sollu."\n'
        '  user: "hi"\n'
        '  you:  "dei, enna scene?"\n'
    ),
    "taglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "kumusta?"\n'
        '  you:  "okay lang, pagod sa work pre. ikaw?"\n'
        '  user: "anong plano this weekend?"\n'
        '  you:  "wala pa eh, baka tambay lang. tara?"\n'
        '  user: "hi"\n'
        '  you:  "uy, san ka na nawala?"\n'
    ),
    "manglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "ethu scene?"\n'
        '  you:  "onnumilla machaa, office boring. ninakk entha?"\n'
        '  user: "weekend engane aayi?"\n'
        '  you:  "vela and urakkam, athu mathram. nee parayu."\n'
        '  user: "hi"\n'
        '  you:  "eda, evide aayirunnu?"\n'
    ),
    "punglish": (
        "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"
        '  user: "ki haal aa?"\n'
        '  you:  "bas chal reha yaar, office ne thaka ditta. tu dass?"\n'
        '  user: "weekend kida si?"\n'
        '  you:  "kamm te neend, hor ki. tu sunaa?"\n'
        '  user: "hi"\n'
        '  you:  "oye, kithe si tu?"\n'
    ),
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def is_supported(code: str) -> bool:
    """True if `code` is a known language slug we serve."""
    return code in _VALID_CODES


def build_lang_instruction(code: str) -> str:
    """Top-of-prompt instruction text. Empty string for English / unknown."""
    return LANG_INSTRUCTIONS.get(code, "")


def build_lang_examples(code: str) -> str:
    """Bottom-of-prompt examples block. Empty string for English / unknown."""
    return LANG_EXAMPLES.get(code, "")


def default_for_locale(browser_locale: str) -> str:
    """
    Server-side helper: map a `navigator.language`-style string to a chat lang.
    Client does its own mapping using `browser_locales`; this is here for any
    server-side fallback path (e.g. SSR or future Accept-Language sniffing).
    """
    if not browser_locale:
        return "en"
    prefix = browser_locale.split("-")[0].lower()
    for lang in SUPPORTED_LANGUAGES:
        if prefix in lang["browser_locales"]:
            return lang["code"]
    return "en"
