# mocha ☕: multi-character and multi-language companion chat

Tiny FastAPI + vanilla JS app. Landing gallery → per-character chat. No build step. Single Python package, two HTML pages, browser-only state.

Architecture + decisions for CLI Agent, see **[AGENT.md](./AGENT.md)**.

---

## Run

```bash
cd mocha-chat
cp .env.example .env       # paste your OPENROUTER_API_KEY
uv sync                    # installs into .venv
make run                   # gunicorn + uvicorn worker
```

Open **http://localhost:8000/** → pick a character → chat.

## Add a character

Open `src/mocha/personas.py`. Add a `Persona(...)` instance, append to `_ALL` at the bottom — that's it. The API + gallery auto-pick it up. Drop a portrait image at `static/persona/<slug>.webp` matching the `avatar` field (emoji fallback shows until you do).

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

After adding the image, run the resize script to keep it lean (~30-50KB):
```bash
uvx --with pillow python scripts/resize_personas.py
```

## Env knobs (.env)

```bash
# Server
HOST=0.0.0.0
PORT=10000
WEB_WORKERS=1

# LLM
OPENROUTER_API_KEY=sk-or-v1-…
MODEL=sao10k/l3-lunaris-8b              # primary chat model
UTILITY_MODEL=mistralai/mistral-nemo    # used by compaction
COMPACT_MODEL=                          # overrides UTILITY_MODEL for /api/compact only

# Human pacing (set PACING_ENABLED=0 to disable)
PACING_ENABLED=1
READ_DELAY_MIN=1.50
READ_DELAY_MAX=2.25
TYPE_DELAY_PER_CHAR=0.05

# Memory / compaction
KEEP_RECENT=20                          # recent turns sent verbatim alongside the memory string

# Translation
TRANSLATE_TARGET=bn                     # default if browser sends nothing (e.g. en-only locale)

# Static asset cache TTL (seconds). Lower = faster invalidation, more bandwidth.
STATIC_CACHE_SECONDS=86400              # 1 day
```

Edit `DEFAULT_MODEL` / `UTILITY_MODEL` at the top of `src/mocha/openrouter.py` if you'd rather hardcode.

## Fallback chain

`RouterConfig.FALLBACK_MODELS` in `openrouter.py`. OpenRouter handles fallback server-side via `extra_body={"models": [...], "route": "fallback"}` in a single HTTP round-trip. Reorder/expand the list to taste.

## Clear / reset

Click **clear** in the chat → styled modal asks to confirm. Wipes ONLY that character's localStorage; the other 4 chats stay.

## Deploy (Render)

`render.yaml` is checked in. Service settings:

- **Build Command:** `pip install uv && make build`
- **Start Command:** `make run`
- **Health Check Path:** `/healthz`
- **Secret File path:** `/opt/render/project/src/.env` (so `python-dotenv` finds it from cwd)

`/healthz` returns `{"status":"ok", "openrouter_configured": true}` — wire it to UptimeRobot or any external pinger to keep the dyno warm.

## Notes

- **Privacy:** server is stateless. Two browsers = two isolated worlds. No DB, no accounts.
- **Compaction:** after ~20 turns, older messages are folded into a short memory string via `/api/compact`. Per-turn token cost stays flat.
- **Translation:** uses `googletrans` (free, no API key). When it breaks, it breaks; we toast the error. Switch language via the LANG button in the chat header.
- **Errors:** stream errors are wrapped in a `\x00MOCHA_ERR\x00` sentinel, stripped from chat, shown as a toast. Empty replies don't pollute history.
- **API key** never touches the browser. All calls go through the FastAPI proxy.

---

**FF character reference:** https://freefireinfo.in/character/    
**Feedback form:** https://docs.google.com/forms/d/e/1FAIpQLSdpRoo9uzZWkDlkq4CzVH9g-0-tIxcgLcNjrSwYfhyuuC3-1w/viewform    
