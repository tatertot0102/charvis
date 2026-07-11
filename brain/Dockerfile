# --- stage 1: build the dashboard SPA (Node needed only at build time) ---
FROM node:22-slim AS frontend
WORKDIR /ui
# Install deps first for layer caching (lockfile optional).
COPY dashboard/package.json dashboard/package-lock.json* ./
RUN npm ci || npm install
COPY dashboard/ ./
RUN npm run build

# --- stage 2: the Python brain, serving the built SPA same-origin ---
FROM python:3.12-slim

# uv: fast, reproducible dependency management (see TECH_STACK.md).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (better layer caching). Dev deps included so tests can run in-container.
# NOTE: build context is the repo root (see docker-compose.yml) so both brain/ and dashboard/ are reachable.
COPY brain/pyproject.toml ./
RUN uv sync

# Application source + the built dashboard (served by app.main._mount_spa at /).
COPY brain/ .
COPY --from=frontend /ui/dist ./dashboard_dist

EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
