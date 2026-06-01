# Production server — gunicorn + UvicornWorker

`make run` boots gunicorn as a process supervisor; each worker is a
`UvicornWorker` (async event loop). Gunicorn doesn't add concurrency — it
adds resilience: worker recycling, graceful reloads, signal handling.

## Concurrency model
- All FastAPI handlers are `async def` → **one worker handles hundreds of
  concurrent chats** (LLM calls park on `await`, event loop serves others).
- `WEB_WORKERS=1` is fine for I/O-bound traffic. Bump to 2 for resilience
  (one keeps serving while the other recycles/crashes). RAM permitting.

## Flag cheat sheet
- `--timeout 180` — arbiter kills worker after 3min of no heartbeat. Sized above `openrouter.py` httpx `read=120s` so a slow LLM never trips it.
- `--graceful-timeout 90` — on deploy (SIGTERM), in-flight streams get 90s to finish before SIGKILL. Without this, deploys cut chats mid-token.
- `--keep-alive 5` — reuse TCP from nginx/proxy for 5s (cheap win).
- `--max-requests 1000 --max-requests-jitter 100` — recycle each worker after ~1000 reqs to bound memory growth (googletrans leaks a bit).
- `--access-logfile -` / `--error-logfile -` — pipe to stdout/stderr so Render's log viewer captures them. Default = no access log at all.

## Bad signals to watch in Render logs
- `WORKER TIMEOUT` → bump `--timeout`.
- Frequent `Booting worker` → crash loop, check error log.
