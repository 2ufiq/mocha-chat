-include .env
export

# Defaults so make doesn't break if .env is partial.
HOST ?= 0.0.0.0
PORT ?= 10000
WEB_WORKERS ?= 1

.PHONY: build run

# Render build step — locked deps, no dev extras, cache pruned for slim image.
build:
	uv sync --frozen --no-dev && uv cache prune --ci

# Production server — gunicorn managing uvicorn workers. No --reload.
run-gunicorn:
	uv run gunicorn mocha.app:app \
		-k uvicorn.workers.UvicornWorker \
		-w $(WEB_WORKERS) \
		-b $(HOST):$(PORT)

run:
	uv run uvicorn mocha.app:app --host $(HOST) --port $(PORT) --workers $(WEB_WORKERS) --use-colors

public:
	ngrok http --url=$(NGROK_URL) $(PORT)