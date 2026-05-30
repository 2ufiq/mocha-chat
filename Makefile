include .env
export

run:
	uv run uvicorn mocha.app:app --host $(HOST) --port $(PORT) --workers $(WEB_WORKERS) --reload
