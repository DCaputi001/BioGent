# Dockerfile for the RAG document-search service.
#
# This containerizes the ingest/query scripts as-is (Step 3 of Phase 2) —
# no HTTP API yet, that's Phase 4's job, once there's a real frontend
# shaping what the endpoint should look like. For now this image is meant
# to be run as an on-demand command, e.g.:
#
#   docker run --rm --env-file .env <image> python -m app.ingest
#   docker run -it --rm --env-file .env <image> python -m app.query
#
# Multi-stage build: the `builder` stage installs dependencies via uv into
# a virtual environment; the final stage copies just that venv + the app
# code, keeping the shipped image free of build tooling.

FROM python:3.12-slim AS builder

# Get the uv binary from its own official image rather than pip-installing
# it — this is uv's documented pattern for Docker builds.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Docling (via RapidOCR/onnxruntime and its image-processing dependencies)
# needs a couple of system libraries that python:slim doesn't include by
# default. If a future Docling version needs more, the error will name the
# missing shared library directly (something like "libX.so: cannot open
# shared object file") — add it here when that happens.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# uv-recommended env vars for Docker builds:
#   UV_COMPILE_BYTECODE — precompiles .pyc files at install time instead of
#     on first import, so container startup is a bit faster.
#   UV_LINK_MODE=copy — avoids uv's default hardlink behavior, which
#     doesn't work reliably across the layer boundary in a Docker build.
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy only the dependency manifests first. Docker caches layers by their
# inputs — as long as pyproject.toml/uv.lock don't change, this layer (and
# the potentially slow `uv sync` below) gets reused on rebuilds even when
# application code changes, instead of reinstalling ~180 packages every time.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Now copy the actual application code and install it into the same venv.
COPY app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Run as a non-root user rather than the container default (root) — a
# compromised or buggy process inside the container then can't do anything
# it doesn't have explicit permission for on the host or in the image.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /home/appuser/.cache /opt/hf-cache \
    && chown -R appuser:appuser /home/appuser/.cache /opt/hf-cache
WORKDIR /app
USER appuser

COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --from=builder --chown=appuser:appuser /app/app /app/app

ENV PATH="/app/.venv/bin:$PATH"

# Bake the embedding model into the image instead of fetching it on first use.
# A Fargate task starts with no cache, so without this EVERY task start (deploy,
# scale-up, crash restart) would re-download it before serving a request.
#
# /opt/hf-cache rather than the default ~/.cache/huggingface on purpose:
# docker-compose mounts a volume over /home/appuser/.cache, which would hide
# the baked copy and send the container back to downloading it.
ENV HF_HOME=/opt/hf-cache
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-en-v1.5')"

# The HTTP API is what this image runs when deployed, so it is the default.
# A full command, with no ENTRYPOINT, keeps overrides simple:
#   docker run <image>                              -> serves the API
#   docker run <image> python -m app.ingest --reset  -> runs ingestion instead
#
# (This previously read CMD ["-m", "app.query"] alongside a comment about an
# ENTRYPOINT that was never actually declared, so the image could not start
# without an explicit command. Every existing caller passed one, which is why
# it went unnoticed; ECS would not have.)
#
# --host 0.0.0.0 is load-bearing: uvicorn's default 127.0.0.1 only accepts
# connections from inside the container, so the ALB health check would fail.
EXPOSE 8000
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8000"]