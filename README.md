# mocha ☕ — multi-persona companion chat

Tiny FastAPI + vanilla JS app. Landing gallery → per-persona chat. No build
step. Single Python package, two HTML pages, browser-only state.

## What's inside

```
mocha-chat/
├── src/mocha/
│   ├── app.py          # FastAPI routes (pages, /api/personas, /api/chat, /api/compact, /healthz)
│   ├── personas.py     # Single source of truth for all characters
│   ├── openrouter.py   # AsyncOpenAI client + RouterConfig (server-side fallback) + pacing
│   ├── memory.py       # Older-turn compaction → short "memory" string per persona
│   ├── settings.py     # env-derived config
│   └── utils.py        # datetime helper for {extra_prompt} injection
├── static/
│   ├── index.html      # Landing — gallery of persona cards
│   ├── chat.html       # Chat page — reads ?persona=<slug> from URL
│   ├── favicon.svg
│   └── persona/        # Character images (mocha.jpg, steffie.webp, etc.)
├── pyproject.toml      # uv deps (src-layout, hatchling build)
├── Makefile            # build + run
├── render.yaml         # Render blueprint
└── .env.example
```

## How to run

```bash
cd ~/Desktop/mocha-chat
cp .env.example .env       # paste your OPENROUTER_API_KEY
uv sync                    # installs into .venv
make run                   # gunicorn + uvicorn worker on $PORT (default 8765)
```

Open **http://localhost:8765/** → pick a persona → chat.

## Add a persona

Open `src/mocha/personas.py`. Add a `Persona(...)` instance, append to `_ALL`
at the bottom — that's it. The API + gallery auto-pick it up. Drop an image at
`static/persona/<slug>.<ext>` matching the `avatar` field (emoji fallback
shows until you do).

```python
nikita = Persona(
    slug="nikita",
    name="Nikita",
    age=24,
    profession="Bodyguard",
    tags=["loyal", "sharp", "tough"],
    avatar="nikita.webp",
    emoji="🛡️",
    tagline="Caroline's shadow. doesn't smile until she likes you.",
    greeting="state your business.",
    system_prompt="""... use existing personas as templates ...""",
)
```

## How to play

### Persona stuff lives in `src/mocha/personas.py`
- system_prompt, greeting, voice, backstory — all editable in place. No app
  code change needed when you tweak.
- Uvicorn `--reload` picks up changes on save (for local dev; prod uses
  gunicorn without reload).

### Switch the active default model
In `.env`:
```
MODEL=mistralai/mistral-nemo
UTILITY_MODEL=mistralai/mistral-nemo
```
Or edit `DEFAULT_MODEL` / `UTILITY_MODEL` at the top of `src/mocha/openrouter.py`.

### Fallback chain
`RouterConfig.FALLBACK_MODELS` in `openrouter.py`. OpenRouter handles the
fallback server-side via `extra_body={"models": [...], "route": "fallback"}`
in a single HTTP round-trip. Reorder/expand the list to taste.

### Tune the vibe + pacing
All via `.env`:
```
PACING_ENABLED=1
READ_DELAY_MIN=1.2
READ_DELAY_MAX=2.8
TYPE_DELAY_PER_CHAR=0.045
KEEP_RECENT=20            # recent turns sent verbatim alongside the memory string
LOG_LEVEL=INFO
```

### Reset a conversation
Click **clear** in the chat page → styled modal asks to confirm. Wipes ONLY
that persona's localStorage (each character has independent history + memory).

## Deploy (Render)

`render.yaml` is checked in. Service settings:

- **Build Command:** `pip install uv && make build`
- **Start Command:** `make run`
- **Health Check Path:** `/healthz`
- Secret File path: `/opt/render/project/src/.env` (so `python-dotenv` picks
  it up from the working dir automatically)

`/healthz` returns `{"status":"ok", "openrouter_configured": true}` — wire it
to UptimeRobot / Render's check / any external pinger.

## Notes

- **Privacy** — server is stateless. All history + memory lives in the
  browser's localStorage, keyed per-persona (`mocha.history.<slug>` /
  `mocha.memory.<slug>`). No DB, no accounts.
- **Compaction** — once a persona's history grows past ~20 turns, older
  messages are folded into a short memory string via `/api/compact`. Keeps
  per-turn token cost roughly flat.
- **Errors** — stream-level errors are wrapped in a `\x00MOCHA_ERR\x00`
  sentinel, stripped from the chat, and shown as a toast. Empty-reply turns
  don't pollute history.
- **Mobile** — chat page uses `interactive-widget=resizes-content` + `100svh`
  so the on-screen keyboard doesn't hide the input bar.
- **API key** never touches the browser. All calls go through the FastAPI proxy.
- Free-tier OpenRouter models have rate limits; the fallback chain helps.

---

**FF character reference:** https://freefireinfo.in/character/

**Feedback form:** https://docs.google.com/forms/d/e/1FAIpQLSdpRoo9uzZWkDlkq4CzVH9g-0-tIxcgLcNjrSwYfhyuuC3-1w/viewform
