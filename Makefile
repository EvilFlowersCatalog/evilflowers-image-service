.PHONY: install install-all lint format test check worker image

# Core + dev tools: enough for the tests.
install:
	uv sync

# Everything the image has (adds the OpenTelemetry and Pyroscope SDKs).
install-all:
	uv sync --all-extras

lint:
	uv run ruff check
	uv run ruff format --check

format:
	uv run ruff check --fix
	uv run ruff format

test:
	uv run pytest

check: lint test

# A local worker (needs a reachable REDIS_URL and STORAGE_PATH; CATALOG_API_* to report).
worker:
	uv run celery -A evilflowers_image.worker worker --loglevel=INFO -E --concurrency=1 --queues=evilflowers_image

image:
	docker build --build-arg IMAGE_TAG=local@$$(git rev-parse --short HEAD) -t evilflowers-image-service:local .
