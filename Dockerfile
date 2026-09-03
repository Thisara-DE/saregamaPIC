# syntax=docker/dockerfile:1

FROM node:20-bookworm-slim AS frontend-build
WORKDIR /build/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# Resolve + install the backend virtualenv with uv in a throwaway stage. uv/uvx
# are only needed to BUILD the venv, so they never reach the runtime image below —
# keeping their Rust-dependency CVEs (e.g. quinn-proto) out of the container scan.
# `only-system` forces the venv onto the base image's Python so its interpreter
# symlinks stay valid once the venv is copied into the identical runtime base.
FROM python:3.13-slim AS backend-build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /uvx /bin/
ENV UV_PYTHON_PREFERENCE=only-system
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --locked --no-dev --no-install-project


FROM python:3.13-slim AS runtime

# gosu drops root → appuser in the entrypoint (see docker-entrypoint.sh); it is a
# tiny setuid helper, not a service dependency. Create a fixed-id unprivileged
# user for the server process.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 appuser \
    && useradd --uid 10001 --gid 10001 --create-home \
       --home-dir /home/appuser --shell /usr/sbin/nologin appuser

WORKDIR /app/backend
# Copy the ready-made virtualenv (no uv binary in this image). Same base image +
# same path means the venv's interpreter symlinks and shebangs stay valid.
# App code, the venv, and the frontend bundle stay root-owned and world-readable:
# appuser only needs to READ them, and read-only-to-the-app code is a feature.
COPY --from=backend-build /app/backend/.venv /app/backend/.venv
COPY backend/app ./app
# Offline eval tooling (Phase 3.5 tiling A/B). Inert read-only scripts, no extra
# deps — shipped so `python -m scripts.evaluate_recognition` can run against the
# environment's own /data volume (e.g. the Development recognition baseline).
COPY backend/scripts ./scripts
COPY --from=frontend-build /build/frontend/dist /app/frontend-dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENV PATH="/app/backend/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/home/appuser \
    SAREGAMAPIC_DATA_DIR=/data \
    SAREGAMAPIC_WEB_DIR=/app/frontend-dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/api/health', timeout=3)"

# No USER: the entrypoint must start as root to chown the freshly-mounted /data
# volume, then drops to appuser via gosu before exec'ing the server. exec inside
# the sh -c hands uvicorn PID 1 so SIGTERM reaches it directly.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
