# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 2A — See my life (read-only Calendar).** Everything from Phase 1, plus a
> read-only Google Calendar integration: an OAuth connect/callback flow, Fernet-encrypted OAuth
> tokens in Postgres, `GET /calendar/today`, and a "what's my day?" answer on Telegram. No writes,
> no Gmail/Todo/Drive, no dashboard yet.

## Endpoints (Phase 1 + 2A)
- `GET /health` — service + DB status (token required)
- `POST /chat` — `{ "message": "...", "session_id": "default" }` → `{ "reply", "conversation_id" }`
- `POST /capture` — `{ "text": "..." }` → `{ "id", "status": "captured" }`
- `GET /integrations/google/connect` — (token) → `{ "auth_url" }`; open it in a browser **on the
  brain's host** to grant read-only Calendar access
- `GET /integrations/google/callback` — Google's redirect target (no token; CSRF-guarded by `state`);
  stores the encrypted refresh token
- `GET /calendar/today` — (token) → `{ "connected", "timezone", "events": [...] }`; `connected:false`
  with a hint until you complete the connect flow

## Connect Google Calendar (Phase 2A)
Requires the Google Cloud setup in `EXTERNAL_ACTIONS.md` §2 (Calendar API + a **Web application**
OAuth client whose redirect URI matches `GOOGLE_OAUTH_REDIRECT_URI`).

```bash
make secret-key                  # copy output into SECRET_ENCRYPTION_KEY in .env (encrypts tokens)
# add GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI to .env
docker compose up -d             # restart brain so it reloads .env
make google-connect              # prints the consent URL — open it in a browser on this machine
make calendar-today              # after granting: today's events as JSON
```

On Telegram: `/connect_google` returns the consent link; after granting, text **"what's my day?"**.

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
make migrate                     # apply migrations to head (0003 = oauth_tokens)  [separate terminal]
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

## Layout
```
docker-compose.yml     brain + db
Makefile               dev commands (make help)
.env.example           config template (never commit .env)
brain/                 FastAPI app, Dockerfile (uv), Alembic
  app/                 config, telemetry, deps (auth), db, api/, llm/, comms/, conversation/
    integrations/      google/ (oauth, tokens, calendar — read-only)
    security/          crypto (Fernet, OAuth tokens at rest)
  tests/               unit + integration (no live Google/LLM calls)
```
