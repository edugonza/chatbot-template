# syntax=docker/dockerfile:1

# ---- build: compile the Rust bridge and install every Python dependency into /app/.venv
FROM rust:1-slim-trixie AS build
COPY --from=ghcr.io/astral-sh/uv:0.9.27 /uv /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app
RUN uv python install 3.12

COPY pyproject.toml uv.lock ./
COPY matrix_bridge ./matrix_bridge
# --no-editable builds a real wheel for the bridge, so the venv is
# self-contained and can be copied into the runtime image on its own.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=cache,target=/usr/local/cargo/registry \
    uv sync --frozen --no-dev --no-install-project --no-editable

# ---- runtime: no compiler toolchain, just Python + the venv
FROM debian:trixie-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 1000 bot \
    && mkdir -p /data/store \
    && chown -R bot:bot /data

COPY --from=build /python /python
COPY --from=build --chown=bot:bot /app/.venv /app/.venv

WORKDIR /app
USER bot

COPY --chown=bot:bot src ./src
COPY --chown=bot:bot scripts ./scripts

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
VOLUME ["/data/store"]

CMD ["python", "-m", "src.main"]
