# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 2B — See my life (read-only Gmail).** Everything from Phase 2A (Calendar), plus a
> read-only Gmail integration on the *same* Google OAuth: deterministic email classification
> (importance/urgency/needs-reply/promotional/calendar/deadline/FYI), a waiting-on ledger
> (who owes whom), a people life-model slice, `GET /gmail/*` endpoints, and natural-language email
> questions on Telegram ("check my email", "anything important?", "what am I waiting on?", "did X
> reply?"). **Read-only** — Jarvis never sends, deletes, labels, or modifies email.

## Endpoints (Phase 1 + 2A + 2B)
- `GET /health` — service + DB status (token required)
- `POST /chat` — `{ "message": "...", "session_id": "default" }` → `{ "reply", "conversation_id" }`
- `POST /capture` — `{ "text": "..." }` → `{ "id", "status": "captured" }`
- `GET /integrations/google/connect` — (token) → `{ "auth_url" }`; open on the brain's host to grant
  read-only Calendar **+ Gmail** access
- `GET /integrations/google/callback` — Google's redirect target (no token; CSRF-guarded by `state`)
- `GET /calendar/today` — (token) → today's events; `connected:false` until connected
- `GET /gmail/unread` · `GET /gmail/today` · `GET /gmail/search?q=…` — (token) → classified messages
- `GET /gmail/thread/{id}` — (token) → a full thread, classified
- `GET /gmail/waiting` — (token) → runs a sync, returns `waiting_on_them` / `waiting_on_me`

All Gmail endpoints return `connected:false` with a re-consent hint until Gmail scope is granted.

## Connect Google (Calendar + Gmail, read-only)
Requires the Google Cloud setup in `EXTERNAL_ACTIONS.md` §2 (enable Calendar **and** Gmail APIs + a
**Web application** OAuth client whose redirect URI matches `GOOGLE_OAUTH_REDIRECT_URI`).

```bash
make secret-key                  # copy output into SECRET_ENCRYPTION_KEY in .env (encrypts tokens)
# add GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / GOOGLE_OAUTH_REDIRECT_URI to .env
docker compose up -d             # restart brain so it reloads .env
make google-connect              # prints the consent URL — open it in a browser on this machine
make calendar-today              # after granting: today's events as JSON
make gmail-unread                # unread email, classified
make gmail-waiting               # who's waiting on whom
```

The brain requests **both** `calendar.readonly` and `gmail.readonly` on one client. If you connected
during Phase 2A (Calendar only), **re-run `make google-connect` to re-consent** and grant Gmail — see
`EXTERNAL_ACTIONS.md` §2.3b.

On Telegram: `/connect_google` returns the consent link; then just ask naturally —
**"what's my day?"**, **"check my email"**, **"anything important?"**, **"what am I waiting on?"**,
**"did Sarah reply?"** (no special commands).

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
make migrate                     # apply migrations to head (0004 = Gmail tables)  [separate terminal]
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
    integrations/      google/ (oauth, tokens, calendar, gmail, classify, sync — read-only)
    lifemodel/         people (contacts slice of the life model)
    coordination/      waiting (waiting-on ledger — detection only)
    security/          crypto (Fernet, OAuth tokens at rest)
  tests/               unit + integration (no live Google/LLM calls)
```
