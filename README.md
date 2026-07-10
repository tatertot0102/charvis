# Jarvis — Personal Secretary System

A personal secretary you text, backed by a portable FastAPI "brain" in Docker, Postgres, and a
**local LLM** (later phases). See `CLAUDE.md` for the product spec and `EXECUTION_PLAN.md` for the
roadmap.

> **Status: Phase 2D.1 — Calendar Resolution Hardening.** Everything from 2A–2C.5, plus **calendar
> write actions that are production-safe**. Jarvis can create, move, and delete Google Calendar
> events — including **bulk** operations ("delete all future DSI events") — but **never without an
> explicit, correct confirmation**. Event resolution is **confidence-scored** with real evidence:
> title-keyword, **acronym** (DSI → Data Science Institute), **fuzzy**, attendee, location,
> description, recurring-series, and time-of-day matching, over configurable lookback/lookahead
> windows. A single action needs **`CONFIRM`**; a **bulk delete needs the stronger `CONFIRM DELETE`**
> (a plain `CONFIRM` will not fire it). Every proposal cites its matched provider events with
> per-event confidence and *why* each matched; zero matches → it says so and asks, never fabricates;
> several unrelated matches → it asks which. The execution layer re-validates every event id against
> Google before writing, so **unknown / fabricated / stale / deleted ids are rejected**. Adds
> `GET /approvals`, `POST /approvals/{id}/confirm`, `POST /approvals/{id}/cancel`. Migrations `0006`
> (approval queue) + `0007` (confidence / required-phrase / item-count). **Requires a one-time Google
> re-consent** for the `calendar.events` write scope — see `EXTERNAL_ACTIONS.md §2.3c`.
>
> ### Permanent engineering principle
> **Jarvis may reason under uncertainty, but it may never invent facts. Every factual statement
> shown to the user must be traceable to evidence from a provider (Google Calendar, Gmail, Todoist)
> or the local database. When evidence is insufficient, Jarvis asks — it never guesses.**

## Endpoints (Phase 1 + 2A + 2B + 2C + 2C.5 + 2D)
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
- `GET /approvals` — (token) → pending calendar actions awaiting confirmation (with confidence,
  `required_phrase`, `item_count`, and expiry)
- `POST /approvals/{id}/confirm` — (token) → execute that action (the only endpoint that can write)
- `POST /approvals/{id}/cancel` — (token) → drop a pending action without executing

All Gmail/state endpoints return `connected:false` with a re-consent hint until Google is connected.
Memory endpoints work from whatever data exists (they self-consolidate once if memory is empty).

## Calendar actions (Phase 2D / 2D.1 — always draft-then-confirm)
Text Jarvis a change and it **drafts** the exact proposal — no write happens until you confirm:

```
you › move my 3pm to 4
jarvis › Move “ARISE sync” from Thu Jul 9, 3:00 PM to Thu Jul 9, 4:00 PM
         (confidence 70%; starts at 15:00).
         Reply CONFIRM to apply this, or anything else to hold off.
you › CONFIRM
jarvis › Moved “ARISE sync” ✓

you › delete all future DSI events
jarvis › I found 3 events to delete:
         1. DSI Orientation — Sat Jul 18, 10:00 AM (90%)
            • title contains “dsi”
            • recurring series
         2. DSI Writing Workshop — Mon Jul 20, 2:00 PM (90%) …
         Reply CONFIRM DELETE to delete these 3 events, or anything else to hold off.
```

- A **single** action confirms with `CONFIRM`; a **bulk delete** needs `CONFIRM DELETE` (a plain
  `CONFIRM` is refused). Proposals expire (`CALENDAR_ACTION_TTL_MINUTES`, default 30).
- Zero matches → Jarvis says so and asks; several unrelated matches → it asks which one. It never
  fabricates an event, and rejects any write to an unknown/stale/deleted id.
- Requires the `calendar.events` write scope: re-run `/connect_google` once — see
  `EXTERNAL_ACTIONS.md §2.3c`.

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
