.PHONY: check test format lint typecheck

check: format lint typecheck test

test:
	uv run pytest

format:
	uv run ruff format .

lint:
	uv run ruff check --fix .

typecheck:
	uv run ty check
