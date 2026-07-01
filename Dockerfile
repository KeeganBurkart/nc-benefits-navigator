# Stage 1: build the web UI
FROM node:22-slim AS web
WORKDIR /build
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

# Stage 2: Python runtime
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

# Install dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY rules/ rules/
COPY interview/ interview/
COPY server/ server/
RUN uv sync --frozen --no-dev

COPY --from=web /build/dist web/dist

RUN useradd -m app && chown -R app /app
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz')" || exit 1

# Fail fast with a clear error when no API key is provided.
CMD ["sh", "-c", "\
  if [ -z \"$ANTHROPIC_API_KEY\" ] && [ -z \"$NAV_ANTHROPIC_API_KEY\" ]; then \
    echo 'ERROR: ANTHROPIC_API_KEY environment variable is required (docker run -e ANTHROPIC_API_KEY=sk-...)' >&2; \
    exit 1; \
  fi; \
  exec /app/.venv/bin/uvicorn server.app:app --host 0.0.0.0 --port 8000"]
