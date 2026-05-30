.PHONY: run sync dev clean

sync:
	uv sync

run:
	uv run uvicorn app:app --reload --port 8765

dev: sync run

clean:
	rm -rf .venv __pycache__ */__pycache__
