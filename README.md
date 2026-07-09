# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 2C.5 — Deep Context / Memory.** Everything from 2A (Calendar) + 2B (Gmail) + 2C
> (unified intelligence), plus a **memory layer**: a consolidation pass turns your existing history
> (Gmail mirror, calendar, captures, chat) into evidence-backed **conclusions**, **patterns**, and
> **commitments** — the model of "me" the ContextResolver reasons over. Every conclusion carries a
> **confidence (0–1), an evidence breakdown, a source list, and timestamps**, and is fully
> explainable ("I think ARISE is a project because: 12 email threads · 6 calendar events"). Entities
> belong to **overlapping contexts** (Work, School, Research, Family, …), not one category. Adds
> `GET /memory/{conclusions,patterns,projects,people,commitments}` + `POST /memory/consolidate`, and
> Telegram introspection ("what do you know about me?", "why do you think ARISE is important?", "show
> low-confidence conclusions"). **Read-only, no new external setup** — it only reads data Jarvis
> already has. Migration `0005`.

## Endpoints (Phase 1 + 2A + 2B + 2C + 2C.5)
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
- `GET /state/next-action` — (token) → the single top recommendation across all sources (memory-aware)
- `GET /state/next-meeting` — (token) → synthesized briefing for your next meeting + related emails
- `GET /memory/conclusions?kind=&min_confidence=&max_confidence=` — (token) → durable conclusions
  with confidence, evidence, source list, contexts, and timestamps
- `GET /memory/projects` · `GET /memory/people` — (token) → conclusions filtered to projects / people
- `GET /memory/patterns` — (token) → detected behavioral patterns (response times, activity windows)
- `GET /memory/commitments` — (token) → open loops: replies owed, follow-ups, flagged deadlines
- `POST /memory/consolidate` — (token) → (re)build memory from existing data; returns row counts

All Gmail/state endpoints return `connected:false` with a re-consent hint until Google is connected.
Memory endpoints work from whatever data exists (they self-consolidate once if memory is empty).

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
**"did Sarah reply?"**, (Phase 2C) **"prep me for my next meeting"**, **"what is my next
meeting about?"**, **"what emails relate to my next event?"**, **"what deadlines are coming up?"**,
and (Phase 2C.5) **"what do you know about me?"**, **"what patterns have you noticed?"**, **"what
projects do you think I'm working on?"**, **"why do you think ARISE is important?"**, **"show
low-confidence conclusions"** (no special commands).

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
make migrate                     # apply migrations to head (0005 = memory tables)  [separate terminal]
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
    memory/            gather → derive → persist: conclusions, patterns, commitments, contexts (2C.5)
    lifemodel/         people (contacts slice of the life model)
    coordination/      waiting (waiting-on ledger — detection only)
    security/          crypto (Fernet, OAuth tokens at rest)
  tests/               unit + integration (no live Google/LLM calls)
```
