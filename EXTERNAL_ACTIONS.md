# EXTERNAL_ACTIONS.md — Everything You Must Do By Hand

> When Jarvis needs something that can't be created from inside the repo (an account, a token, a
> permission toggle, a model download), the build **STOPS** and points you here. Do these in phase
> order; you don't need later-phase items until their phase begins.
>
> **Rules:** never fake a credential, never hardcode a secret, never skip an integration silently.
> Every secret goes into your machine's `.env` (never committed — only `.env.example` is versioned).
>
> Legend: 🖥️ = MacBook Pro (server) · 💻 = MacBook Air (dev) · 📱 = Android phone.
> `.env` key names below match those referenced in EXECUTION_PLAN / TECH_STACK.

---

## Phase 0 — Deploy proof (do these first)

### 0.1 — Docker Desktop (🖥️ and 💻)
- **Purpose:** run `brain` + `db` containers with one command.
- **Why needed:** the entire brain is containerized for identical Air→Pro deploys.
- **Where to click:**
  1. Go to https://www.docker.com/products/docker-desktop/ → download **Apple Silicon** build.
  2. Open the `.dmg`, drag Docker to Applications, launch it, complete onboarding.
  3. In Docker Desktop → **Settings → Resources**: give it enough memory (≥ 4 GB; more on the Pro).
- **Info you need:** none (no login required for local use).
- **Where it goes in the project:** nothing to paste; `docker compose up` just works.
- **Verify:** terminal → `docker --version` and `docker compose version` both print versions; `docker run --rm hello-world` prints the success message.

### 0.2 — Git + GitHub repo (💻 primary)
- **Purpose:** version control + the Air→Pro deploy path (`git pull`).
- **Why needed:** deploy = pull the same repo on the Pro.
- **Where to click:**
  1. Ensure Git: `git --version` (install via `xcode-select --install` if missing).
  2. Create a repo at https://github.com/new → name `jarvis` → **Private** → Create.
  3. (Recommended) install GitHub CLI `gh` and run `gh auth login` (choose SSH), or add an SSH key at https://github.com/settings/keys.
- **Info you need:** your GitHub account; an SSH key or `gh` auth.
- **Where it goes:** `git remote add origin git@github.com:<you>/jarvis.git`. The repo already lives at `/Users/zanewolf/Documents/Jarvis`.
- **Verify:** `git push -u origin main` succeeds; the files appear on GitHub.

### 0.3 — Tailscale on all three devices (🖥️ 💻 📱)
- **Purpose:** private mesh network so phone↔Air↔Pro talk with **no public ports**.
- **Why needed:** the brain binds the Tailscale interface; every device reaches it by Tailscale IP.
- **Where to click:**
  1. Create an account at https://login.tailscale.com/start (Google/GitHub sign-in is fine).
  2. **🖥️ Pro:** install from https://tailscale.com/download/mac (App Store or standalone) → sign in → toggle **Connected**.
  3. **💻 Air:** same install + sign in with the **same** account.
  4. **📱 Android:** install "Tailscale" from Play Store → sign in with the same account → enable the VPN.
  5. In the Tailscale admin console (https://login.tailscale.com/admin/machines) note each device's **100.x.y.z** IP. Optionally enable **MagicDNS** so you can use device names.
- **Info you need:** the **Pro's Tailscale IP** (this is where the brain will listen).
- **Where it goes:** Pro's IP → `.env` on the Air as the brain host / `LLM_BASE_URL` host later; Android Tasker will POST to `http://<pro-tailscale-ip>:<port>`.
- **Verify:** from the 📱 phone browser (with Tailscale on), once the brain is up, `http://<pro-tailscale-ip>:8000/health` returns `{"status":"ok"}`. Before the brain exists, `ping`/Tailscale admin showing all three devices "connected" is enough.

### 0.4 — Keep the Pro awake (🖥️)
- **Purpose:** the always-on backend must not sleep.
- **Why needed:** if the Pro sleeps, Jarvis and the local model go offline.
- **Where to click:** **System Settings → Displays → Advanced → "Prevent automatic sleeping on power adapter when the display is off"** (wording varies by macOS) → ON. Also **System Settings → Battery / Energy** → prevent sleep on power adapter. Keep it plugged in. (Optional: run `caffeinate -s` or set up via `pmset` — documented in MACHINE_SETUP.)
- **Verify:** close the lid (if using clamshell with external power) or leave it idle; `/health` still answers from the phone after 30+ minutes.

---

## Phase 1 — Talk to it

### 1.1 — Telegram bot (📱/any)
- **Purpose:** your chat front door to Jarvis.
- **Why needed:** Phase 1 is Telegram ↔ `/chat` ↔ local LLM.
- **Where to click:**
  1. In Telegram, open a chat with **@BotFather**.
  2. Send `/newbot` → follow prompts: pick a **name** (e.g., "Jarvis") and a **username** ending in `bot` (e.g., `zane_jarvis_bot`).
  3. BotFather replies with an **HTTP API token** like `123456789:AA...`.
  4. (Optional) `/setprivacy` → **Disable** if you later add it to groups; for a 1:1 bot the default is fine.
- **Info you need:** the **bot token**; and **your own Telegram numeric user ID** (message **@userinfobot** to get it) so the bot only responds to you.
- **Where it goes:** `.env` → `TELEGRAM_BOT_TOKEN=...` and `TELEGRAM_ALLOWED_USER_IDS=<your id>`.
- **Verify:** after the brain is running, message your bot "hello"; you get an LLM reply. (Whitelist check: a different account gets no reply.)

### 1.2 — Ollama + a local model (🖥️ Pro; optionally 💻 Air for dev)
- **Purpose:** the local LLM that powers all reasoning.
- **Why needed:** the amendment mandates local-only AI behind the provider abstraction.
- **Where to click / commands:**
  1. Install from https://ollama.com/download (macOS Apple Silicon) — installs a menu-bar app + `ollama` CLI and starts a service on port **11434**.
  2. Pull the Phase 1 default model (sized for the Pro's **8 GB M1** — do not go larger):
     - `ollama pull llama3.2:3b`
  3. Confirm it serves: `curl http://localhost:11434/api/tags` lists your models.
- **Info you need:** the model name (`llama3.2:3b`); the Ollama host/port. On the Pro it's `http://localhost:11434` (the brain container reaches it at `http://host.docker.internal:11434`). For **Air dev** pointing at the Pro: `http://<pro-tailscale-ip>:11434` — to allow remote access set `OLLAMA_HOST=0.0.0.0:11434` on the Pro (see MACHINE_SETUP) so it isn't localhost-only.
- **Where it goes:** `.env` (these keys already exist in the template) →
  ```
  LOCAL_LLM_PROVIDER=ollama
  LOCAL_LLM_BASE_URL=http://host.docker.internal:11434   # Pro; or http://<pro-tailscale-ip>:11434 for Air dev
  LOCAL_LLM_MODEL=llama3.2:3b
  ```
  To switch providers later, change only these (e.g. `LOCAL_LLM_PROVIDER=openai` + `OPENAI_API_KEY=...`).
  No application code references Ollama.
- **Verify:** `curl http://localhost:11434/api/chat -d '{"model":"llama3.2:3b","messages":[{"role":"user","content":"say hi"}],"stream":false}'` returns a reply; then a Telegram message to Jarvis returns a coherent answer.

### 1.3 — Shared auth token (💻/🖥️ — you generate it)
- **Purpose:** protect every brain endpoint even inside Tailscale.
- **Why needed:** defense in depth; agents and the dashboard must authenticate.
- **Where to click / command:** generate a random secret: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`.
- **Where it goes:** `.env` → `AUTH_SHARED_TOKEN=...` (same value on Air and Pro `.env`s). Agents/dashboard send it as a bearer header.
- **Verify:** `curl -H "Authorization: Bearer <token>" http://<host>:8000/health` → ok; without the header → 401.

### 1.4 — Fernet encryption key (💻/🖥️ — you generate it)
- **Purpose:** encrypt OAuth tokens at rest in Postgres (needed from Phase 2, generate now).
- **Where to click / command:** `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
- **Where it goes:** `.env` → `SECRET_ENCRYPTION_KEY=...`. **Back this up securely** — losing it means re-authing every integration.
- **Verify:** brain startup logs "encryption key loaded" (no plaintext printed).

---

## Phase 2 — See my life (read-only)

> **Phase 2A (current) needs ONLY Google Calendar, read-only.** Gmail (2.2) and Drive are later
> sub-phases — do not enable or scope them yet. The brain requests exactly one scope in Phase 2A:
> `calendar.readonly`. Nothing here can write, send, delete, or spend.

### 2.1 — Google Cloud project + OAuth consent screen (any browser)
- **Purpose:** foundation for Google API access (Phase 2A: Calendar only).
- **Why needed:** Google APIs require an OAuth client.
- **Where to click:**
  1. https://console.cloud.google.com/ → top bar **project dropdown → New Project** → name "Jarvis" → Create → select it.
  2. **APIs & Services → OAuth consent screen** → User type **External** → Create.
  3. Fill app name "Jarvis", your email as support + developer contact → Save and continue.
  4. **Scopes:** skip here (the brain requests `calendar.readonly` at connect time) → Save.
  5. **Test users:** add **your own Google account** (maxwellreyfman@gmail.com). Leaving the app in **"Testing"** status means **no Google verification is required** and tokens work for test users. → Save.
- **Info you need:** your Google account email (already a test user).
- **Where it goes:** nothing yet; this gates the client ID below.
- **Verify:** consent screen shows status "Testing" with your email listed as a test user.

### 2.2 — Enable the Google Calendar API (same console)
- **Purpose:** turn on the one API Jarvis calls in Phase 2A.
- **Where to click:** **APIs & Services → Library** → search **Google Calendar API** → **Enable**.
  - Gmail API / Drive API are **not** needed for Phase 2A — enable them only when their sub-phase begins.
- **Verify:** the Calendar API shows "API Enabled" in the Library.

### 2.3 — OAuth client credentials — **Web application** (same console)
- **Purpose:** the client ID/secret the brain uses to run the OAuth flow, plus the **redirect URI**
  Google will send the browser back to.
- **Why "Web application" (not Desktop):** the brain completes OAuth via a server callback endpoint
  (`GET /integrations/google/callback`). That pattern needs a **registered redirect URI**, which is
  exactly what a Web-application client provides. (Desktop clients don't register a fixed callback
  URL and don't fit this flow.)
- **Where to click:**
  1. **APIs & Services → Credentials → Create Credentials → OAuth client ID**.
  2. Application type: **Web application** → name "Jarvis Web".
  3. Under **Authorized redirect URIs → + Add URI**, paste **exactly**:
     `http://localhost:8000/integrations/google/callback`
     - This must match `GOOGLE_OAUTH_REDIRECT_URI` in `.env` character-for-character.
     - **Do the one-time connect from a browser on the machine running the brain** (so `localhost:8000`
       resolves to the container). Google only accepts `https://…` or `http://localhost` / `http://127.0.0.1`
       redirect URIs for Web clients — a plain `http://<tailscale-ip>` will be **rejected**. If you must
       authorize from another device, either register a `127.0.0.1` URI and SSH-tunnel, or set up a
       Tailscale HTTPS hostname and register that `https://…/integrations/google/callback` URI instead
       (then update `GOOGLE_OAUTH_REDIRECT_URI` to match). For MVP, the localhost path is simplest.
  4. **Create** → copy the **Client ID** and **Client secret** (or download the JSON and copy the two
     values out — do **not** commit the JSON).
- **Where it goes:** `.env` (never committed) →
  ```
  GOOGLE_CLIENT_ID=<client id>
  GOOGLE_CLIENT_SECRET=<client secret>
  GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/integrations/google/callback
  ```
  Then apply it: `docker compose up -d` (restart the brain so it reloads `.env`).
- **Run the one-time connect flow:**
  1. Get the consent URL — either `make google-connect` (prints it), or on Telegram send
     **`/connect_google`** to the bot (it replies with the link). Open the link **in a browser on the
     brain's host**.
  2. Pick your Google account → **"Google hasn't verified this app"** → **Advanced → Go to Jarvis
     (unsafe)** (expected for a Testing app) → grant **read-only Calendar** access.
  3. Google redirects to the callback; the brain stores an **encrypted refresh token** in Postgres
     and shows a "Connected ✓" page.
- **Verify:** `make calendar-today` returns real events (JSON), or text **"what's my day?"** to the
  Telegram bot and get today's schedule. `GET /calendar/today` now returns `"connected": true`.
- **Scope (least privilege):** Phase 2A requests only `calendar.readonly`. `gmail.readonly` (later
  Phase 2 sub-step), `gmail.send` (Phase 4), and `drive.*` (Phase 5) each trigger a fresh re-consent
  when their phase adds them.

### 2.4 — Todoist API token (any browser)
- **Purpose:** read (Phase 2) and later add/complete (Phase 4) tasks.
- **Why needed:** the Todo connector in CLAUDE.md §10.
- **Where to click:** Todoist → **Settings → Integrations → Developer** → copy your **API token**. (This is a personal token — no OAuth dance needed.)
- **Info you need:** the API token.
- **Where it goes:** `.env` → `TODOIST_API_TOKEN=...`.
- **Verify:** `curl -H "Authorization: Bearer <token>" https://api.todoist.com/rest/v2/tasks` returns your tasks JSON; then Jarvis lists them.
- **Note:** if you use **Google Tasks** instead, skip this — it rides the Google OAuth from 2.1–2.3 (enable the Tasks API).

### 2.5 — mac-agent permissions + LaunchAgent (🖥️ and 💻)
- **Purpose:** report running apps and (later) open apps/URLs; kept alive across reboots.
- **Why needed:** OS-touching code lives outside the container (CLAUDE.md Golden Rule #5).
- **Where to click:**
  1. First run of the agent will trigger prompts. Grant in **System Settings → Privacy & Security**:
     - **Automation** → allow the agent (Terminal/python) to control **System Events**/apps (for `osascript`).
     - **Accessibility** → add the agent binary if window/app control needs it.
  2. Install the LaunchAgent: copy the provided plist to `~/Library/LaunchAgents/com.jarvis.mac-agent.plist`, then `launchctl load` it (exact commands ship with the agent; also in MACHINE_SETUP).
- **Info you need:** the brain's Tailscale URL + `AUTH_SHARED_TOKEN` (the agent authenticates its POSTs to `/ingest`).
- **Where it goes:** the agent reads its own small config (brain URL + token) from env/plist.
- **Verify:** `launchctl list | grep jarvis` shows it running; `/state/context` reflects your currently-open apps.

### 2.6 — Chrome extension (load unpacked) (🖥️ and 💻)
- **Purpose:** push active tabs + history to `/ingest`.
- **Where to click:**
  1. Chrome → `chrome://extensions` → toggle **Developer mode** (top-right) → **Load unpacked** → select `agents/chrome-extension/`.
  2. Pin it; open its options and paste the **brain URL** + **auth token**.
- **Info you need:** brain Tailscale URL + `AUTH_SHARED_TOKEN`.
- **Where it goes:** the extension's options storage.
- **Verify:** browse a page; `/state/context` / ingest logs show the tab. (Chrome may warn about developer-mode extensions — expected.)

### 2.7 — Android Tasker: ingest profiles (📱)
- **Purpose:** send location, battery, and (later) SMS/notifications to the brain.
- **Why needed:** device signals for the live-context strip and coordination.
- **Where to click:**
  1. Install **Tasker** (paid) from Play Store; install **Tailscale** (done in 0.3) and keep it connected.
  2. Import the provided profiles (`agents/android-tasker/*.prj.xml`) via Tasker → **☰ → Data → Restore / Import**.
  3. Grant Tasker its permissions: **Location** (Allow all the time), **Battery** (disable battery optimization for Tasker: Settings → Apps → Tasker → Battery → **Unrestricted**), and for Phase 4 **SMS** (read/send) + **Notification access**.
  4. In each profile's HTTP POST action, set the URL to `http://<pro-tailscale-ip>:8000/ingest/android` and add the `Authorization: Bearer <token>` header.
- **Info you need:** Pro's Tailscale IP + port + `AUTH_SHARED_TOKEN`.
- **Where it goes:** inside the Tasker HTTP actions (not the repo).
- **Verify:** move / unplug the phone; `/state/context` shows updated location/battery. Note OEM battery-killers (Samsung/Xiaomi/etc.) may need extra "don't optimize" toggles — see MACHINE_SETUP.

---

## Phase 4 — Act (gated)

### 4.1 — Gmail send scope re-consent (browser)
- **Purpose:** allow draft-first sending.
- **Where to click:** re-run the Google auth command after `gmail.send` is added to requested scopes → browser → grant the new permission. (Same Testing-app flow as 2.3.)
- **Verify:** a Tier-3 "propose-and-wait" email draft, once you approve it, actually sends.

### 4.2 — Android SMS-send profile (📱)
- **Purpose:** send texts via the phone (SMS connector).
- **Where to click:** enable the provided "send SMS" Tasker profile; grant **SMS send** permission; confirm default-SMS-app constraints on your Android version.
- **Verify:** an approved outbound text is delivered.

---

## Phase 5 — Secretary polish

### 5.1 — Google Drive scope (browser)
- **Purpose:** assemble briefings from docs / edit docs.
- **Where to click:** enable Drive API (2.2 if not done), add `drive.readonly`/`drive.file` scopes, re-consent.
- **Verify:** Jarvis can pull a named doc into a meeting briefing.

### 5.2 — Dispatch tool handles (as applicable)
- **Purpose:** route jobs to Claude Cowork / a Docs tool / a Slides tool.
- **Where to click:** obtain whatever access/handle each target tool needs (varies); store its config in `.env`.
- **Verify:** "reorganize my files" produces a real handoff to Cowork.

---

## Master `.env` keys checklist (populate as phases unlock)

```
# Phase 0
AUTH_SHARED_TOKEN=
DB_DSN=postgresql+asyncpg://jarvis:jarvis@db:5432/jarvis   # compose-internal
# Phase 1
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USER_IDS=
LOCAL_LLM_PROVIDER=ollama
LOCAL_LLM_BASE_URL=http://host.docker.internal:11434
LOCAL_LLM_MODEL=llama3.2:3b
SECRET_ENCRYPTION_KEY=
# Phase 2A (Calendar, read-only)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_OAUTH_REDIRECT_URI=http://localhost:8000/integrations/google/callback
# Phase 2 (later sub-steps)
TODOIST_API_TOKEN=
# (agents read AUTH_SHARED_TOKEN + brain URL, set on their own devices)
```

**Never commit `.env`.** Only `.env.example` (keys, no values) is versioned. If any secret is ever
exposed, rotate it at its source (BotFather `/revoke`, Google credentials, Todoist reset) and update
`.env`.
