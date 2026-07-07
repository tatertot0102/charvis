# MACHINE_SETUP.md — Per-Device Setup

> Exactly what to install and configure on each device. Pair with `EXTERNAL_ACTIONS.md` (accounts,
> tokens, clicks). Golden rule: **the brain is portable — machine-specific values live in `.env`,
> never in code.**
>
> Roles: **MacBook Pro** = always-on server (brain + Postgres + local LLM). **MacBook Air** = dev
> box (same stack, points its LLM at the Pro or runs a small local model). **Android** = signals +
> chat.

---

## MacBook Pro 🖥️ — the always-on server

### Software / brew installs
```bash
# Xcode CLT (git, compilers)
xcode-select --install
# Homebrew (if not present): https://brew.sh
brew install git uv          # uv = Python dep/build manager
brew install --cask docker   # Docker Desktop (Apple Silicon)
brew install --cask ollama   # local LLM host (or install from ollama.com)
brew install --cask tailscale # or the App Store / standalone app
# optional quality-of-life
brew install jq
```

### Python packages
- The brain's Python deps are **inside the container** (managed by `uv` from `brain/pyproject.toml`)
  — you do **not** pip-install them on the host.
- Host-level Python is only needed for one-off helpers (generating tokens, the mac-agent). Use the
  system `python3` or a `uv`-managed venv for `agents/mac-agent`.

### Node packages
- None on the Pro for the backend. (The dashboard is built as static assets; it can be built on the
  Air and served by the brain, or built on the Pro if you prefer — Node 20 LTS via `brew install node`
  only if building here.)

### Local LLM (Ollama)
```bash
# after install, Ollama runs a service on 11434
ollama pull qwen2.5:7b-instruct     # size to RAM; 14b if you have headroom
ollama pull nomic-embed-text        # embeddings for memory / pgvector
# allow the brain container (and the Air over Tailscale) to reach Ollama:
#   set OLLAMA_HOST so it isn't localhost-only
launchctl setenv OLLAMA_HOST "0.0.0.0:11434"   # then restart Ollama
```
**Model sizing rule of thumb (unified memory):** keep model + Postgres + brain within RAM with
headroom. ~8 GB free → 7B; ~16 GB+ free → 14B. Ollama unloads idle models automatically. If the Pro
has ≤ 16 GB total, stay at 7B and avoid the 14B.

### System permissions (for the mac-agent, Phase 2+)
- **System Settings → Privacy & Security → Automation:** allow the agent (python/Terminal) to control
  System Events / target apps (for `osascript`).
- **Privacy & Security → Accessibility:** add the agent if window/app control needs it.
- **Privacy & Security → Full Disk Access:** only if a future feature needs it (not for MVP).

### LaunchAgents
- **mac-agent:** `~/Library/LaunchAgents/com.jarvis.mac-agent.plist` (template in
  `agents/mac-agent/launchd/`). Load: `launchctl load ~/Library/LaunchAgents/com.jarvis.mac-agent.plist`.
  Keeps the agent alive and restarts it on crash/login.
- **Ollama** runs as its own login item/service from the installer — no plist needed.

### Keep-awake (must-do for an always-on server)
- **System Settings → Battery/Energy → Options:** "Prevent automatic sleeping on power adapter when
  the display is off" → ON. Keep plugged in.
- Belt-and-suspenders via a LaunchDaemon running `caffeinate -s`, or:
  `sudo pmset -c sleep 0 disksleep 0` (on charger, never sleep). Document that this is intentional.

### Docker requirements
- Docker Desktop running at login (**Settings → General → Start Docker Desktop when you sign in**).
- Give it generous memory (**Settings → Resources**): enough for Postgres + brain (LLM is native, not
  in Docker) — 4–6 GB is plenty since the model is outside Docker.

### Ports / services
| Service | Port | Bound to | Notes |
|---|---|---|---|
| brain (FastAPI) | 8000 | Tailscale interface (`100.x.y.z`) | every endpoint requires `AUTH_SHARED_TOKEN` |
| postgres | 5432 | Docker-internal (not exposed to LAN) | reachable by brain via compose network |
| ollama | 11434 | `0.0.0.0` (Tailscale + localhost) | so brain container + Air can reach it |

Nothing is published to the public internet. Firewall: allow Tailscale; do not port-forward on the
router.

### Environment variables (`.env` on the Pro)
```
AUTH_SHARED_TOKEN=<generated>
SECRET_ENCRYPTION_KEY=<fernet key>
DB_DSN=postgresql+asyncpg://jarvis:jarvis@db:5432/jarvis
TELEGRAM_BOT_TOKEN=<from BotFather>
TELEGRAM_ALLOWED_USER_IDS=<your id>
LLM_PROVIDER=ollama
LLM_BASE_URL=http://host.docker.internal:11434   # brain container → native Ollama on the Pro
LLM_MODEL=qwen2.5:7b-instruct
LLM_EMBED_MODEL=nomic-embed-text
GOOGLE_CLIENT_ID=<phase 2>
GOOGLE_CLIENT_SECRET=<phase 2>
TODOIST_API_TOKEN=<phase 2>
APP_ENV=production
BIND_HOST=0.0.0.0        # inside the container; compose maps to the Tailscale IP
```
> `host.docker.internal` resolves to the Mac host from inside Docker Desktop containers — that's how
> the containerized brain reaches native Ollama. If it ever fails, use the Pro's Tailscale IP.

### Bring-up on the Pro
```bash
git clone git@github.com:<you>/jarvis.git && cd jarvis
cp .env.example .env      # then fill in the Pro values above
docker compose up -d --build
docker compose exec brain alembic upgrade head   # run migrations
curl -H "Authorization: Bearer $AUTH_SHARED_TOKEN" http://localhost:8000/health
```

---

## MacBook Air 💻 — the dev box

### Software / brew installs
```bash
xcode-select --install
brew install git uv node        # node 20 LTS for the dashboard
brew install --cask docker
brew install --cask tailscale
brew install --cask visual-studio-code
# optional: run a small local model here for offline dev
brew install --cask ollama
```

### Python packages
- Same model as the Pro: brain deps live in the container via `uv`. For local linting/type-checking
  and the mac-agent, create a `uv` venv:
  ```bash
  cd brain && uv sync        # creates .venv from pyproject/uv.lock for editor + tooling
  ```

### Node packages
```bash
cd dashboard && npm install   # React + Vite + TS + TanStack Query + Tailwind
```

### LLM for dev — two supported modes (pure config, no code change)
1. **Point at the Pro (recommended, matches prod):**
   ```
   LLM_PROVIDER=ollama
   LLM_BASE_URL=http://<pro-tailscale-ip>:11434
   LLM_MODEL=qwen2.5:7b-instruct
   ```
2. **Run a small model locally on the Air (offline):**
   ```bash
   ollama pull qwen2.5:3b-instruct   # smaller, fits the Air
   ```
   ```
   LLM_PROVIDER=ollama
   LLM_BASE_URL=http://host.docker.internal:11434
   LLM_MODEL=qwen2.5:3b-instruct
   ```

### System permissions / LaunchAgents
- Same mac-agent permissions and (optional) LaunchAgent as the Pro if you want the Air's app/tab
  context ingested during dev. Not required for backend work.

### Docker requirements / ports / services
- Identical compose stack; brain on `localhost:8000`, postgres internal, migrations via
  `docker compose exec brain alembic upgrade head`.
- For dashboard dev, Vite dev server runs on `5173` and proxies API calls to `localhost:8000`.

### Environment variables (`.env` on the Air)
Same keys as the Pro, but `APP_ENV=development`, `LLM_BASE_URL` per the mode chosen above, and you may
use a **separate Telegram test bot** so dev messages don't collide with the production bot.

### Dev loop
```bash
cd jarvis
cp .env.example .env      # fill dev values
docker compose up --build            # brain + db
docker compose exec brain alembic upgrade head
# dashboard (separate terminal)
cd dashboard && npm run dev
make test   # or: docker compose exec brain pytest
```

---

## Android phone 📱 — signals + chat

### Apps to install
- **Telegram** (chat with the bot).
- **Tailscale** (Play Store) — sign in, enable VPN, keep connected.
- **Tasker** (Play Store, paid) — device automation.
- (Phase 4/5) nothing extra; Tasker handles SMS/notifications.

### Tasker profiles (imported from `agents/android-tasker/`)
| Profile | Trigger | Action | Phase |
|---|---|---|---|
| Location update | location change / interval | POST location → `/ingest/android` | 2 |
| Battery report | battery level change | POST battery → `/ingest/android` | 2 |
| SMS inbound | SMS received | POST sms_in → `/ingest/android` | 2/4 |
| SMS outbound | brain requests (poll or push) | send SMS | 4 |
| Notification forward | notification posted | POST → `/ingest/android` | 5 |

Each HTTP action targets `http://<pro-tailscale-ip>:8000/ingest/android` with header
`Authorization: Bearer <AUTH_SHARED_TOKEN>`.

### System permissions
- **Location:** "Allow all the time" for Tasker.
- **Battery optimization:** set Tasker to **Unrestricted / Don't optimize** (Settings → Apps →
  Tasker → Battery). **OEM note:** Samsung (Device care → Battery → Tasker → unrestricted), Xiaomi
  (Autostart + no battery restrictions), OnePlus/Oppo similar — otherwise the OS kills Tasker and
  signals stop. treat device signals as best-effort, never a hard dependency.
- **SMS** (Phase 4): grant read/send; be aware of the default-SMS-app rules on your Android version.
- **Notification access** (Phase 5): grant Tasker notification listener permission.

### Environment / config
- No `.env` on the phone; all config (brain URL + token) lives inside the Tasker HTTP actions.

### Verify
- With Tailscale on, open `http://<pro-tailscale-ip>:8000/health` in the phone browser (add the
  bearer via a REST client, or just confirm the port responds) — reachability proves the mesh works.
- Trigger a location/battery change → confirm `/state/context` updates.

---

## Cross-device conventions

- **One source of truth for config:** every machine has its own `.env`; the repo only ships
  `.env.example`. No hostnames/paths/secrets in code.
- **Deploy path (Air → Pro):** commit + push on the Air → on the Pro `git pull` → ensure Pro `.env`
  → `docker compose up -d --build` → `alembic upgrade head`. Identical images, different config.
- **Time zone:** set the brain's TZ via `.env` (`TZ=America/New_York` or your zone) so scheduling and
  briefings use your local time consistently on both machines.
- **Backups (Pro):** nightly `pg_dump` (a scheduler job or a launchd cron) to an encrypted local path;
  DB holds encrypted OAuth tokens, so protect the dump. Keep `SECRET_ENCRYPTION_KEY` backed up
  separately — without it, backups can't be decrypted and integrations must re-auth.
