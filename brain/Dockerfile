FROM python:3.12-slim

# uv: fast, reproducible dependency management (see TECH_STACK.md).
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

# Install dependencies first (better layer caching). Dev deps included so the
# smoke test can run inside the container (Phase 0 keeps the image simple).
COPY pyproject.toml ./
RUN uv sync

# Application source.
COPY . .

EXPOSE 8000
CMD [".venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
