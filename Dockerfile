# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Install uv from the official image.
COPY --from=ghcr.io/astral-sh/uv:0.11.0 /uv /usr/local/bin/uv

WORKDIR /app

# Cache dependencies separately from source code.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project --no-editable

# Now install the project itself. --no-editable so /opt/venv is self-contained
# (otherwise uv writes a .pth file pointing at /app/src, which we don't copy
# into the runtime stage).
COPY src ./src
COPY README.md ./README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable


# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:$PATH"

# Non-root user.
RUN groupadd --system --gid 10001 farma && \
    useradd --system --uid 10001 --gid farma --no-create-home --shell /usr/sbin/nologin farma

COPY --from=builder /opt/venv /opt/venv

USER farma
WORKDIR /app

EXPOSE 14000

# Healthcheck: the /mcp endpoint requires auth, but the underlying TCP listen check
# is enough to know the process is up. We use python instead of curl/wget (slim image).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket,sys; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',14000)); s.close()" || exit 1

ENTRYPOINT ["farma-tools-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "14000"]
