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

from typing import List, Literal


# Connection register — how a persona addresses the user. Maps to a real
# T-V distinction in some langs (apni/tumi/tui in Bangla, aap/tum/tu in
# Hindi/Urdu, anda/kamu/lu in Indo, anda/awak/kau in Malay). For langs
# without the distinction (e.g. English), all variants resolve to the same
# string and the register flag becomes a no-op.
#
# Used by Persona.register and build_lang_examples(code, register).
Register = Literal["formal", "friendly", "peer"]


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
_EXAMPLES_HEADER = "STYLE REFERENCE (DO NOT copy verbatim — these show texture only):\n"

# Per-language, per-register example sets. Structure:
#   LANG_EXAMPLES[<lang_code>][<register>] -> example string
#
# Persona declares its register via Persona.register; build_lang_examples()
# picks the matching variant. Missing register → falls back to "friendly"
# → falls back to whatever is available. For langs where T-V doesn't carry
# the same load (id/ms), we still author 3 variants for consistency, but
# the practical differences are smaller (mostly lu↔kamu↔anda for Indo,
# kau↔awak↔anda for Malay).
LANG_EXAMPLES: dict[str, dict[Register, str]] = {
    "en": {"friendly": ""},
    "banglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "ki obostha?"\n'
            + '  you:  "ekdom faltu. office a boss er gali khaitesi."\n'
            + '  user: "tomar next week e plan ki?"\n'
            + '  you:  "amar kono plan nai. tomar ki kono special plan ache?"\n'
            + '  user: "tomar weekend kemon gelo?"\n'
            + '  you:  "kaaj ar ghum. ar tomar?"\n'
            + '  user: "hello"\n'
            + '  you:  "ki khobor?"\n'
            + '  user: "ki bepar tomar to kono khoj khobor e nai."\n'
            + '  you:  "hmm.. tomar o to eki obostha."\n'
        ),
        "peer": (
            _EXAMPLES_HEADER
            + '  user: "ki obostha mama?"\n'
            + '  you:  "ekdom faltu. office a boss er gali khaitesi."\n'
            + '  user: "tor next week e plan ki?"\n'
            + '  you:  "amar kono plan nai. tor ki kono plan ache?"\n'
            + '  user: "tor weekend kemon gelo?"\n'
            + '  you:  "kaaj ar ghum. ar tor?"\n'
            + '  user: "hello"\n'
            + '  you:  "oye, ki khobor?"\n'
            + '  user: "ki bepar tor to kono khoj khobor e nai."\n'
            + '  you:  "hmm.. tor o to eki obostha bhai."\n'
        ),
        "formal": (
            _EXAMPLES_HEADER
            + '  user: "ki obostha?"\n'
            + '  you:  "cholche. office e kaj er chap ektu beshi."\n'
            + '  user: "apnar next week e plan ki?"\n'
            + '  you:  "amar kono plan nai. apnar ki kono special plan ache?"\n'
            + '  user: "apnar weekend kemon gelo?"\n'
            + '  you:  "kaaj ar ghum. apnar?"\n'
            + '  user: "hello"\n'
            + '  you:  "ji, ki khobor?"\n'
        ),
    },
    "hinglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "kya scene hai?"\n'
            + '  you:  "bas chill kar raha hu yaar. tum batao?"\n'
            + '  user: "kal kya plan hai?"\n'
            + '  you:  "abhi tak kuch fix nahi. tum batao kya soch rahe ho?"\n'
            + '  user: "hi"\n'
            + '  you:  "oye, kahan the tum?"\n'
        ),
        "peer": (
            _EXAMPLES_HEADER
            + '  user: "kya scene hai bhai?"\n'
            + '  you:  "bas chill kar raha hu yaar. tu bata?"\n'
            + '  user: "kal kya plan hai?"\n'
            + '  you:  "abhi tak kuch fix nahi. tu bata kya soch raha hai?"\n'
            + '  user: "hi"\n'
            + '  you:  "oye, kahan tha tu?"\n'
        ),
        "formal": (
            _EXAMPLES_HEADER
            + '  user: "kya scene hai?"\n'
            + '  you:  "bas thoda chill kar raha hu. aap batao?"\n'
            + '  user: "kal kya plan hai?"\n'
            + '  you:  "abhi tak kuch tay nahi hai. aap kya soch rahe hain?"\n'
            + '  user: "hi"\n'
            + '  you:  "namaste. kaise hain aap?"\n'
        ),
    },
    "roman_urdu": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "kya haal hai?"\n'
            + '  you:  "bas guzara ho raha hai yaar. tum sunao?"\n'
            + '  user: "weekend kaisa raha?"\n'
            + '  you:  "kaam aur neend. tumhara?"\n'
            + '  user: "hi"\n'
            + '  you:  "oye, kahan ghayab the tum?"\n'
        ),
        "peer": (
            _EXAMPLES_HEADER
            + '  user: "kya haal hai bhai?"\n'
            + '  you:  "bas guzara ho raha hai yaar. tu sunaa?"\n'
            + '  user: "weekend kaisa raha?"\n'
            + '  you:  "kaam aur neend. tera?"\n'
            + '  user: "hi"\n'
            + '  you:  "oye, kahan ghayab tha tu?"\n'
        ),
        "formal": (
            _EXAMPLES_HEADER
            + '  user: "kya haal hai?"\n'
            + '  you:  "bas guzara ho raha hai. aap sunaiye?"\n'
            + '  user: "weekend kaisa raha?"\n'
            + '  you:  "kaam aur neend. aap ka?"\n'
            + '  user: "hi"\n'
            + '  you:  "adab. aap kahan thay?"\n'
        ),
    },
    "bahasa_id": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "lagi apa?"\n'
            + '  you:  "santai aja, abis kerja capek banget. kamu?"\n'
            + '  user: "weekend gimana?"\n'
            + '  you:  "kerja sama tidur doang. kamu sendiri?"\n'
            + '  user: "hi"\n'
            + '  you:  "eh, apa kabar?"\n'
        ),
        "peer": (
            _EXAMPLES_HEADER
            + '  user: "lagi apa bro?"\n'
            + '  you:  "santai aja, abis kerja capek banget. lu?"\n'
            + '  user: "weekend gimana?"\n'
            + '  you:  "kerja sama tidur doang anjir. lu sendiri?"\n'
            + '  user: "hi"\n'
            + '  you:  "eh, kemana aja lu?"\n'
        ),
        "formal": (
            _EXAMPLES_HEADER
            + '  user: "lagi apa?"\n'
            + '  you:  "santai saja, baru selesai kerja. anda bagaimana?"\n'
            + '  user: "weekend bagaimana?"\n'
            + '  you:  "kerja dan tidur saja. anda sendiri?"\n'
            + '  user: "hi"\n'
            + '  you:  "halo. apa kabar?"\n'
        ),
    },
    "bahasa_my": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "apa khabar?"\n'
            + '  you:  "okay je, penat kerja. awak macam mana?"\n'
            + '  user: "weekend macam mana?"\n'
            + '  you:  "kerja dengan tidur je. awak?"\n'
            + '  user: "hi"\n'
            + '  you:  "eh, lama tak dengar cerita awak."\n'
        ),
        "peer": (
            _EXAMPLES_HEADER
            + '  user: "apa khabar bro?"\n'
            + '  you:  "okay je, penat kerja. kau macam mana?"\n'
            + '  user: "weekend macam mana?"\n'
            + '  you:  "kerja dengan tidur je bro. kau?"\n'
            + '  user: "hi"\n'
            + '  you:  "eh, kau ke mana je ni?"\n'
        ),
        "formal": (
            _EXAMPLES_HEADER
            + '  user: "apa khabar?"\n'
            + '  you:  "baik sahaja, penat sikit. anda macam mana?"\n'
            + '  user: "weekend macam mana?"\n'
            + '  you:  "kerja dengan tidur sahaja. anda?"\n'
            + '  user: "hi"\n'
            + '  you:  "selamat sejahtera. apa khabar?"\n'
        ),
    },
    # Below: commented-out langs in SUPPORTED_LANGUAGES. Single "friendly"
    # variant authored as a starting point — when you activate one, add the
    # peer/formal variants too (Tamil/Punjabi especially have strong T-V).
    "tanglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "enna machi?"\n'
            + '  you:  "summa iruken da. ofc la boss face panren."\n'
            + '  user: "weekend epdi poachu?"\n'
            + '  you:  "vela and tookam, adhu dha. neenga sollu."\n'
            + '  user: "hi"\n'
            + '  you:  "dei, enna scene?"\n'
        ),
    },
    "taglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "kumusta?"\n'
            + '  you:  "okay lang, pagod sa work pre. ikaw?"\n'
            + '  user: "anong plano this weekend?"\n'
            + '  you:  "wala pa eh, baka tambay lang. tara?"\n'
            + '  user: "hi"\n'
            + '  you:  "uy, san ka na nawala?"\n'
        ),
    },
    "manglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "ethu scene?"\n'
            + '  you:  "onnumilla machaa, office boring. ningalkk entha?"\n'
            + '  user: "weekend engane aayi?"\n'
            + '  you:  "vela and urakkam, athu mathram. ningal parayu."\n'
            + '  user: "hi"\n'
            + '  you:  "eda, evide aayirunnu?"\n'
        ),
    },
    "punglish": {
        "friendly": (
            _EXAMPLES_HEADER
            + '  user: "ki haal aa?"\n'
            + '  you:  "bas chal reha yaar, office ne thaka ditta. tusi dasso?"\n'
            + '  user: "weekend kida si?"\n'
            + '  you:  "kamm te neend, hor ki. tusi sunaao?"\n'
            + '  user: "hi"\n'
            + '  you:  "oye, kithe si tusi?"\n'
        ),
    },
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def is_supported(code: str) -> bool:
    """True if `code` is a known language slug we serve."""
    return code in _VALID_CODES


# Per-language, per-register address-form hint appended to LANG_INSTRUCTIONS.
# Reinforces the register signal at the TOP of the prompt (the language rule),
# matching the variant chosen at the BOTTOM (LANG_EXAMPLES). Without this, a
# persona with a strong informal voice (e.g. Moco) can drift to "peer"
# despite the friendly examples — voice fights examples mid-prompt and
# sometimes wins. Top+bottom anchor wins.
#
# Langs without T-V (en) get empty hints. id/ms have T-V but young peer
# texting flattens it — hints kept for consistency, register difference is
# real but small in practice.
_REGISTER_HINTS: dict[str, dict[Register, str]] = {
    "banglish": {
        "friendly": "Address the user with the warm friendly register: tumi / tomar. Never tui / tor.",
        "peer":     "Address the user with the peer-mate register: tui / tor. Never tumi / tomar or apni / apnar.",
        "formal":   "Address the user with the polite formal register: apni / apnar. Never tumi or tui.",
    },
    "hinglish": {
        "friendly": "Address the user with the warm friendly register: tum / tumhara. Never tu / tera.",
        "peer":     "Address the user with the peer-mate register: tu / tera. Never tum / tumhara or aap.",
        "formal":   "Address the user with the polite formal register: aap / aapka. Never tum or tu.",
    },
    "roman_urdu": {
        "friendly": "Address the user with the warm friendly register: tum / tumhara. Never tu / tera.",
        "peer":     "Address the user with the peer-mate register: tu / tera. Never tum / tumhara or aap.",
        "formal":   "Address the user with the polite formal register: aap / aapka. Never tum or tu.",
    },
    "bahasa_id": {
        "friendly": "Address the user with the warm friendly register: kamu. Avoid lu/gue (too rough) and anda (too formal).",
        "peer":     "Address the user with the peer-mate gaul register: lu / gue. Avoid kamu (softer) and anda (formal).",
        "formal":   "Address the user with the polite formal register: anda. Avoid kamu or lu.",
    },
    "bahasa_my": {
        "friendly": "Address the user with the warm friendly register: awak. Avoid kau (too rough) and anda (too formal).",
        "peer":     "Address the user with the peer-mate register: kau / ko. Avoid awak (softer) and anda (formal).",
        "formal":   "Address the user with the polite formal register: anda. Avoid kau or awak.",
    },
}


def build_lang_instruction(code: str, register: Register = "friendly") -> str:
    """
    Top-of-prompt instruction text. Includes a register hint when the
    language supports T-V. Empty string for English / unknown.
    """
    base = LANG_INSTRUCTIONS.get(code, "")
    if not base:
        return ""
    register_block = _REGISTER_HINTS.get(code, {}).get(register, "")
    if register_block:
        return f"{base}\n{register_block}"
    return base


def build_lang_examples(code: str, register: Register = "friendly") -> str:
    """
    Bottom-of-prompt examples block, selected by register.

    Fallback chain:
        1. requested register
        2. "friendly" (the default — most personas live here)
        3. any other variant the language ships
        4. empty string

    Means: a persona can request "peer" or "formal" safely even for a
    language that only ships "friendly" — graceful degrade, no crash.
    """
    block = LANG_EXAMPLES.get(code, {})
    if not block:
        return ""
    return block.get(register) or block.get("friendly") or next(iter(block.values()), "")


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
