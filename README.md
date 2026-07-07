# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 1 — Talk to it.** Token-protected brain with `/health`, `/chat`, and `/capture`;
> a provider-agnostic local LLM (Ollama by default) reached only via `app.llm.generate`; a Telegram
> long-polling bot; and persistent conversation history in Postgres. No integrations/dashboard yet.

## Endpoints (Phase 1)
- `GET /health` — service + DB status (token required)
- `POST /chat` — `{ "message": "...", "session_id": "default" }` → `{ "reply", "conversation_id" }`
- `POST /capture` — `{ "text": "..." }` → `{ "id", "status": "captured" }`

## LLM providers
The app only calls `app.llm.generate(...)`. Switch backends by editing `.env` only:
`LOCAL_LLM_PROVIDER` = `ollama` (default) | `openai` | `anthropic` | `lmstudio` | `echo`,
plus `LOCAL_LLM_BASE_URL` and `LOCAL_LLM_MODEL`. Default model: `llama3.2:3b` (fits the 8 GB M1 Pro).

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
