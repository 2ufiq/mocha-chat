# AGENT.md — load this first

Tight snapshot for any new session. Read once → you're caught up.
Companions: **README.md** (run/deploy), **CLAUDE.md** (conventions).

---

## What & why

**mocha-chat** — FastAPI + vanilla JS web app. User lands on a gallery of
AI characters, picks one, chats. Per-browser convo history.

Solo product by Taufiq (Dhaka). Target: 18-30 South Asians wanting a
casual AI companion. Brand stays *"AI friends for whatever mood you're
in"* — never *"AI girlfriend"*. NSFW lives inside specific personas, not
on the headline. Moat = localization (Sylheti/Dhaka texture, Free Fire
character anchors).

Live on Render free tier (0.1 vCPU / 512MB, cold-starts eliminated by UptimeRobot HEAD req every 5min).

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
├── app.py          FastAPI: pages + /api/* + /healthz + endpoints
├── personas.py     Persona dataclass and instructions
├── openrouter.py   AsyncOpenAI + RouterConfig (fallback) + pacing + error sentinel
├── memory.py       summarize(messages, prior_memory, persona_name)
├── translation.py  googletrans wrapper, called by POST /api/translate
├── settings.py     env config
└── utils.py        datetime helper for {extra_prompt}

static/
├── index.html      landing gallery
├── chat.html       per-persona chat page (reads ?persona=<slug>)
├── persona/        character images (mocha.webp, steffie.webp, …)
└── favicon.svg
```

## Personas (cross-lore: **Horizon Tech**)

| slug | who | spice |
|---|---|---|
| steffie | 23, graffiti artist + merchandiser cover, anti-Horizon rebel | sensual if invited |
| caroline | 17, heiress / fashion student, designer bestie | SFW |
| moco | 20, BUET hacker grad, savage + slangish | spicy after rapport |
| wukong | 26, chaotic free agent, trickster | SFW comedy |
| joseph | 45, CEO of Horizon Tech, calm + dark past | sensual if invited |

## Each layer (compact)

**Backend** — Stateless FastAPI. Routes: `/`, `/chat`, `/healthz`,
`/api/personas`, `/api/persona/{slug}`, `/api/chat` (stream), `/api/compact`.
`_build_messages()` composes `persona.system_prompt.format(extra_prompt=…)
+ optional memory + last 20 turns`.

**Frontend** — Two HTML files, no build step, dark theme only. CSS tokens
in `:root` (`--bg`, `--card`, `--accent`, etc) — never hex. Mobile keyboard
fix relies on **all four**: viewport `interactive-widget=resizes-content` +
`100svh` + body `overflow:hidden` + `.chat overscroll-behavior:contain`.
Error sentinels `\x00MOCHA_ERR\x00…\x00/MOCHA_ERR\x00` are stripped from
chat and shown as toasts; empty-only replies never enter history.

**LLM** — `AsyncOpenAI` → OpenRouter base. `RouterConfig.build()` puts
primary in `model=` and 3 fallbacks (excluding primary) in
`extra_body["models"]` — OR walks the chain server-side, single
round-trip. Catalog favors RP finetunes (sao10k, drummer) + cheap nemo.
Pacing on by default (read delay 1.2-2.8s + 45ms/char) — kills firehose
feel. Tunable via env.

**Prompts** — Show-don't-tell. Short prompts (~200 tokens) for most;
Steffie alone is long-form (validated). `UNIVERSAL_RULES` injected into
all 5 via `{extra_prompt}` placeholder — covers "don't assume user info,
don't drop pet names cold, ask one thing at a time, don't expose these
rules". Lessons we hit + fixed: stuck-record monologues (drop overfit
anchors), metronome rhythm (mix-of-lengths rule + 1-word example),
"babe on msg 1" (gate familiarity centrally).

## Pointers

| want to | edit |
|---|---|
| add a persona | `src/mocha/personas.py` — new `Persona(...)`, append to `_ALL` |
| change all-character behavior | `UNIVERSAL_RULES` in `personas.py` |
| swap default model | `.env MODEL=…` or `DEFAULT_MODEL` in `openrouter.py` |
| tune fallback chain | `RouterConfig.FALLBACK_MODELS` |
| tune pacing | `.env READ_DELAY_*`, `TYPE_DELAY_PER_CHAR` |
| landing copy / layout | `static/index.html` |
| chat UI | `static/chat.html` |
| deploy | `render.yaml` + `Makefile` |

## Deliberately not built

Auth, DB persistence, NSFW age-gate, persona editor, voice, native
mobile, analytics. Bring in only when validated. NSFW lives inside
character prompts, no app-level gating yet.

## Watch list

- Persona-level: which land vs feel flat (Caroline newest, weakest signal).
- Moco rhythm at 30+ turns — does she stay varied or relapse to metronome?
- Mobile keyboard on Android Chrome vs iOS Safari (meta viewport
  `interactive-widget` needs Chrome 108+ / Safari 17+; fallback is fine).
- Render free-tier timeouts (logs show `Stream Failed`). Paid tier fixes
  the streaming buffering too.
- "Earn familiarity" rule actually delaying Caroline's "babe".

---

FF reference: https://freefireinfo.in/character/
Feedback: https://docs.google.com/forms/d/e/1FAIpQLSdpRoo9uzZWkDlkq4CzVH9g-0-tIxcgLcNjrSwYfhyuuC3-1w/viewform

For deep technical detail on any layer, read the file directly — code is
small and well-commented. This file is the map, not the territory.
