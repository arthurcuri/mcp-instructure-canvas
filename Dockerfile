FROM ghcr.io/astral-sh/uv:0.11.19@sha256:b46b03ddfcfbf8f547af7e9eaefdf8a39c8cebcba7c98858d3162bd28cf536f6 AS uv
FROM python:3.12-slim@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1

ARG VERSION
ARG REVISION
LABEL org.opencontainers.image.title="Canvas MCP" \
      org.opencontainers.image.source="https://github.com/arthurcuri/mcp-instructure-canvas" \
      org.opencontainers.image.description="Local Canvas LMS MCP with REST reads/writes, GraphQL and file transfers. Telegram reminders and Codex/Claude agents are configured from the source repository." \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION"

COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
ENV UV_PYTHON_DOWNLOADS=never UV_COMPILE_BYTECODE=1
RUN uv sync --locked --no-dev --no-editable \
    && useradd --uid 10001 --create-home canvas \
    && mkdir /files && chown canvas:canvas /files

USER canvas
WORKDIR /files
ENTRYPOINT ["/app/.venv/bin/canvas-mcp-server"]
