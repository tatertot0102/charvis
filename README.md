# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 0 — Deploy proof.** An empty, token-protected brain (`/health`) + Postgres,
> reachable over Tailscale. No chat, LLM, or integrations yet.

## Planning docs
- `EXECUTION_PLAN.md` — architecture, phases, risks, standards
- `TECH_STACK.md` — technology choices + rationale
- `EXTERNAL_ACTIONS.md` — everything to set up by hand (accounts, tokens, clicks)
- `MACHINE_SETUP.md` — per-device setup (Air / Pro / Android)
- `MVP.md` — the smallest useful slice

## Quick start (MacBook Air — dev)
Prereqs: Docker Desktop, Git, and the Phase 0 items in `EXTERNAL_ACTIONS.md` §0.

```bash
cp .env.example .env
make token                       # copy the output into AUTH_SHARED_TOKEN in .env
make up                          # build + start brain and db
make migrate                     # apply the (empty) baseline migration   [separate terminal]
make health                      # curl /health with your token
make test                        # run the smoke test
```

`/health` returns `{"status":"ok","database":"connected"}` when the brain and Postgres are up.

## Deploy (MacBook Pro — server)
```bash
git clone <repo> jarvis && cd jarvis
cp .env.example .env             # set APP_ENV=production and Pro values
docker compose up -d --build
docker compose exec brain .venv/bin/alembic upgrade head
```

Details, Tailscale verification, and rollback steps live in `MACHINE_SETUP.md` and the Phase 0
notes returned with this scaffold.

## Layout (Phase 0)
```
docker-compose.yml     brain + db
Makefile               dev commands (make help)
.env.example           config template (never commit .env)
brain/                 FastAPI app, Dockerfile (uv), Alembic
  app/                 config, telemetry, deps (auth), db, api/health
  tests/               smoke test
```
