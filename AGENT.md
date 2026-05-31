# AGENT.md — load this first

Tight snapshot for any new session. Read once → you're caught up.
Companions: **README.md** (run/deploy/extend), **CLAUDE.md** (coding conventions).

---

## What & why

**mocha-chat** — FastAPI + vanilla JS web app. Landing gallery of AI
characters → pick one → chat. Per-browser convo history.

Solo product by Taufiq (Dhaka). Target: 18-30 South Asians wanting a casual
AI companion. Brand stays *"AI friends for whatever mood you're in"* —
never *"AI girlfriend"*. NSFW lives inside specific personas, not on the
headline. Moat = localization (Sylheti/Dhaka texture, Free Fire character
anchors).

Live on Render free tier (0.1 vCPU / 512MB, cold-starts eliminated by
UptimeRobot HEAD req every 5min).

## Shape

```
Browser localStorage ──POST──▶ FastAPI ──▶ OpenRouter (server-side fallback)
  history.<slug>                 stateless         many models in 1 round-trip
  memory.<slug>                  (no DB)
```

**Invariant:** server stores nothing. Two browsers = two isolated worlds.
Compaction is client-triggered after 20 turns → POST `/api/compact`.

## File map

```
src/mocha/
├── app.py          FastAPI: pages, /api/{personas,persona/{slug},chat,compact,translate}, /healthz
├── personas.py     Persona dataclass + 5 instances + UNIVERSAL_RULES
├── openrouter.py   AsyncOpenAI + RouterConfig (fallback) + pacing + error sentinel
├── memory.py       summarize(messages, prior_memory, persona_name)
├── translation.py  googletrans wrapper with 1 retry
├── settings.py     env config (pacing, openrouter base)
├── utils.py        datetime helper for {extra_prompt}
└── prompts/        ⚠️ DEAD CODE — kept for reference (the bold mocha prompt)

static/
├── index.html      landing gallery
├── chat.html       per-persona chat page (reads ?persona=<slug>)
├── persona/        character images (mocha.webp, steffie.webp, …) — resized to ≤600×750
└── favicon.svg

scripts/
└── resize_personas.py   uvx-runnable maintenance: resize new persona webp to ≤600×750
```

## Personas (cross-lore: **Horizon Tech**)

| slug | who | spice |
|---|---|---|
| steffie | 23, graffiti artist + merchandiser cover, anti-Horizon rebel | sensual if invited |
| caroline | 17, heiress / fashion student, designer bestie | SFW |
| moco | 20, BUET hacker grad, savage + slangish | spicy after rapport |
| wukong | 26, chaotic free agent, trickster | SFW comedy |
| joseph | 45, CEO of Horizon Tech, calm + dark past | sensual if invited |

All persona are FreeFire inspired. Check FF reference to know more about charecters: https://freefireinfo.in/character/

## Each layer (compact)

**Backend** — Stateless FastAPI. Landing route inlines `window.MOCHA_PERSONAS`
+ `<link rel="preload">` for each image so cards paint instantly (no
`/api/personas` round-trip on first paint). Cache middleware sets
`STATIC_CACHE_SECONDS` (default 86400 = 1 day) on `/persona/*` and
`/favicon.svg`. `_build_messages()` composes `persona.system_prompt
.format(extra_prompt=…)` + optional memory + last 20 turns.

**Frontend** — Two HTML files, no build step, dark theme only. CSS tokens
in `:root` — never hex. Mobile keyboard fix needs **all four**: viewport
`interactive-widget=resizes-content` + `100svh` + `body overflow:hidden` +
`.chat overscroll-behavior:contain`. Per-message local-time timestamps
(stored client-side, stripped from wire payload via `forWire()`). Inline
translate button (icon-only) on each bot reply → `/api/translate`; lang
picker in header saves to localStorage. Error sentinels
`\x00MOCHA_ERR\x00…\x00/MOCHA_ERR\x00` are stripped and toasted; empty-only
replies never enter history. Clear button shows styled confirm modal.

**LLM** — `AsyncOpenAI` → OpenRouter base. `RouterConfig.build()` puts
primary in `model=` and 3 fallbacks (excluding primary) in
`extra_body["models"]` — OR walks the chain server-side, single
round-trip. Catalog favors RP finetunes (sao10k, drummer) + cheap nemo.
Pacing on by default (read delay 1.2-2.8s + 45ms/char) — kills firehose
feel. Tunable via env.

**Prompts** — Show-don't-tell. Short prompts (~200 tokens) for most;
Steffie alone is long-form (validated). `UNIVERSAL_RULES` injected into
all 5 via `{extra_prompt}` placeholder — covers "don't assume user info,
don't drop pet names cold, ask one thing at a time, never copy example
replies verbatim, don't expose these rules". Lessons we hit + fixed:
stuck-record monologues (drop overfit anchors), metronome rhythm
(mix-of-lengths rule + 1-word example), "babe on msg 1" (gate familiarity
centrally), example-echo (anti-copy rule in universal block).

**Translation** — `googletrans` (web-endpoint scraper, NOT official API).
Chosen because LLM-based translation refuses adult content (the chat's
main mode). Fragile by design; we retry once after 400ms and toast the
error on the second failure. No fallback provider — keep it simple.

## Pointers

| want to | edit |
|---|---|
| add a persona | `src/mocha/personas.py` — new `Persona(...)`, append to `_ALL` |
| change all-character behavior | `UNIVERSAL_RULES` in `personas.py` |
| swap default model | `.env MODEL=…` or `DEFAULT_MODEL` in `openrouter.py` |
| tune fallback chain | `RouterConfig.FALLBACK_MODELS` |
| tune pacing | `.env READ_DELAY_*`, `TYPE_DELAY_PER_CHAR` |
| cache TTL | `.env STATIC_CACHE_SECONDS` |
| default translation language | `.env TRANSLATE_TARGET` (user override via header LANG picker) |
| landing copy / layout | `static/index.html` |
| chat UI | `static/chat.html` |
| resize new persona image | `uvx --with pillow python scripts/resize_personas.py` |
| deploy | `render.yaml` + `Makefile` |

## Deliberately not built

Auth, DB persistence, NSFW age-gate, persona editor, voice, native mobile,
analytics. Bring in only when validated. NSFW lives inside character
prompts, no app-level gating yet.

## Watch list

- Persona-level: which land vs feel flat (Caroline newest, weakest signal).
- Moco rhythm at 30+ turns — does she stay varied or relapse to metronome?
- Mobile keyboard on Android Chrome vs iOS Safari (viewport
  `interactive-widget` needs Chrome 108+ / Safari 17+; fallback is fine).
- Render free-tier streaming buffering (logs show `Stream Failed` on long
  cold-start latencies). Paid tier fixes most of it.
- `googletrans` reliability — when Google reshapes their web endpoint, we
  break. The retry buys us some headroom but not a lot. Manual fix usually
  means upgrading the package.
- "Earn familiarity" rule actually delaying Caroline's "babe".

---

For deep technical detail on any layer, read the file directly — code is
small and well-commented. This file is the map, not the territory.
