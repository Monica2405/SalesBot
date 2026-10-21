# Build from the repo root (uv workspace):  docker build -f apps/api/Dockerfile -t salesbot-api .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PACKS_DIR=/app/packs \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Workspace metadata first for layer caching. uv needs every member's pyproject to resolve.
COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-agent/pyproject.toml apps/voice-agent/pyproject.toml
RUN uv sync --frozen --no-dev --package salesbot-api --no-install-workspace

COPY packages/core packages/core
COPY apps/api apps/api
COPY packs packs
RUN uv sync --frozen --no-dev --package salesbot-api

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "salesbot_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
