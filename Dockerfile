# syntax=docker/dockerfile:1.7

# -- build: the virtual environment, from uv.lock -------------------------------------------------------------------
FROM python:3.12-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.13.7 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cached while only the code changes).
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-dev --all-extras --no-install-project

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-extras --no-editable

# -- runtime -----------------------------------------------------------------------------------------------------------
FROM python:3.12-slim

WORKDIR /app
COPY --from=build /app/.venv /app/.venv

# Transitional: the dev manifest (knowledge `evilflowers.yaml.j2`) still starts the old layout with
# `celery --workdir src -A worker worker …`. Drop this once it runs `-A evilflowers_image.worker`.
RUN mkdir /app/src && echo "from evilflowers_image.worker import app  # noqa: F401" > /app/src/worker.py

ARG IMAGE_TAG=dev
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    IMAGE_TAG=${IMAGE_TAG}

# Prefork with one child: Flower can inspect the worker while a book is being cropped (with --pool=solo it
# cannot), and telemetry starts in the child (worker_process_init).
CMD ["celery", "-A", "evilflowers_image.worker", "worker", "--loglevel=INFO", "-E", "--concurrency=1", \
     "--queues=evilflowers_image"]
