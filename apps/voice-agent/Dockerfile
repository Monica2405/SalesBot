# Build from the repo root (uv workspace):  docker build -f apps/voice-agent/Dockerfile -t salesbot-agent .
# Long-running container: holds live call audio streams. Never deploy this to Vercel/serverless.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PACKS_DIR=/app/packs \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY packages/core/pyproject.toml packages/core/pyproject.toml
COPY apps/api/pyproject.toml apps/api/pyproject.toml
COPY apps/voice-agent/pyproject.toml apps/voice-agent/pyproject.toml
RUN uv sync --frozen --no-dev --package salesbot-agent --no-install-workspace

COPY packages/core packages/core
COPY apps/voice-agent apps/voice-agent
COPY packs packs
RUN uv sync --frozen --no-dev --package salesbot-agent

RUN useradd --create-home --uid 10001 app
USER app

# TODO: replace with the real call server entrypoint once telephony is decided.
CMD ["python", "-m", "salesbot_agent", "--demo"]
