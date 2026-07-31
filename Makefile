.PHONY: bootstrap check format lint test governance clean

bootstrap:
	uv python install 3.12
	@test -f uv.lock || uv lock
	uv sync --group dev --locked
	uv run pre-commit install

check:
	uv run python scripts/check.py

format:
	uv run ruff format .
	uv run ruff check --fix .

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

test:
	uv run pytest

governance:
	uv run python scripts/verify_governance.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache __pycache__
