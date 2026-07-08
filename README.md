# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 2C — Unified Intelligence / Meeting Prep.** Everything from 2A (Calendar) + 2B
> (Gmail), plus a `ContextResolver` that reasons *across* those sources: it links a calendar event
> to its related Gmail threads, waiting-on items, and your captures, then synthesizes a concise
> meeting briefing (LLM-written, with a deterministic fallback). Adds `GET /state/{today,waiting,
> deadlines,next-action,next-meeting}` and Telegram questions like "prep me for my next meeting",
> "what is my next meeting about?", "what deadlines are coming up?". **Read-only** — no new external
> integrations; combines the data Jarvis already has.

## Endpoints (Phase 1 + 2A + 2B + 2C)
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
- `GET /state/today` — (token) → today's calendar + a waiting-on overview + one-line summary
- `GET /state/waiting` — (token) → the waiting-on ledger, split by who owes whom
- `GET /state/deadlines` — (token) → deadlines from calendar events + flagged email, urgency-sorted
- `GET /state/next-action` — (token) → the single top recommendation across all sources
- `GET /state/next-meeting` — (token) → synthesized briefing for your next meeting + related emails

All Gmail/state endpoints return `connected:false` with a re-consent hint until Google is connected.

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
**"did Sarah reply?"**, and (Phase 2C) **"prep me for my next meeting"**, **"what is my next
meeting about?"**, **"what emails relate to my next event?"**, **"what deadlines are coming up?"**
(no special commands).

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
    context/           resolver + briefing + deadlines (cross-source unified intelligence, 2C)
    lifemodel/         people (contacts slice of the life model)
    coordination/      waiting (waiting-on ledger — detection only)
    security/          crypto (Fernet, OAuth tokens at rest)
  tests/               unit + integration (no live Google/LLM calls)
```
