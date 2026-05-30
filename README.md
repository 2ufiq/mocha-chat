# mocha ☕ — cheeky companion chat

Tiny FastAPI + vanilla JS app. 4 files of real code. No build step. uv-managed.

## What's inside
```
companion-chat/
├── app.py              # FastAPI: /api/chat (streams) + /api/greeting
├── openrouter.py       # Model catalog + streaming client + fallback chain
├── prompts.py          # SYSTEM_PROMPT + GREETING  ← edit persona here
├── static/index.html   # Chat UI, history in localStorage
├── pyproject.toml      # uv deps
├── .env.example
└── README.md
```

## How to run

```bash
cd ~/Desktop/companion-chat
cp .env.example .env             # paste your OPENROUTER_API_KEY
uv sync                          # installs into .venv
uv run uvicorn app:app --reload --port 8765
```

Open **http://localhost:8765/** → start chatting.

## How to play

### 1. Change the personality
Open `prompts.py`. Edit `SYSTEM_PROMPT`. Save. Send a new message — the
backend reloads the prompt on each request (uvicorn `--reload` restarts on save).

The greeting line shown on first open lives in the same file (`GREETING`).
Clear localStorage (click **clear** in the UI) to see a new greeting.

### 2. Switch the model
Two ways:

**Quick (no code):** in `.env` set
```
MODEL=z-ai/glm-4.5-air:free
```
Restart the server.

**In code:** edit `DEFAULT_MODEL` at the top of `openrouter.py`.

### 3. Fallback chain
`openrouter.py` → `FALLBACK_MODELS`. If the active model errors / refuses /
returns empty, we automatically retry on the next one. You'll see a small
`_(swapping model...)_` hint in the stream when that happens.

Reorder the list to change priorities. Add new model slugs from
[openrouter.ai/models](https://openrouter.ai/models).

### 4. Tune the vibe
`openrouter.py` → `stream_chat()`. Bump `temperature` for wilder replies,
lower for tame. `max_tokens` caps response length.

### 5. Reset
Click **clear** in the UI. Wipes localStorage history.

## Notes
- History is sent in full every turn (no compaction yet). At ~50+ turns you
  may want a sliding window — easy to add in `app.py`.
- API key never touches the browser. All calls go through the FastAPI proxy.
- Free-tier OpenRouter models have rate limits; the fallback chain helps.
