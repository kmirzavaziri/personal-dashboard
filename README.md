# Personal Dashboard

A self-hostable personal dashboard — health & nutrition plan, shopping list, styling,
budget, and a task manager + calendar — served as a small Flask app backed by plain YAML
files. No database: your data is **files in git**, which makes it versioned, portable, and
impossible to lose to a dead server.

## Design in one line
> **Your data is the crown jewel; the server is disposable.** The app runs from this public
> code repo; your data lives in a separate **private** repo. The server pulls the data on boot
> and pushes changes back (debounced). Lose the host → redeploy, never lose data.

## Features
- **Task manager** (kanban: Backlog / To Pick / Planned / Missed / Done) + **Calendar**
  (recurring + one-off, linked to tasks).
- **Health plan** (weekly meals, nutrient targets, routines, gym, skincare), **Shopping list**
  (with live store price/stock), **Styling** pipeline, **Budget**.
- Glass UI, mobile-friendly, collapsible sections, PWA installable.
- **Two ways to edit:** quick toggles in the web UI, and conversational edits from the Claude
  app via a built-in **MCP** endpoint — no computer needed.

---

## How it's wired

One Render service serves the app on **two hostnames**, gated differently:

| Hostname | Serves | Gate |
|----------|--------|------|
| `dash.<domain>` (web UI) | full UI + everything | **Cloudflare Access** (your email) |
| `mcp.<domain>` (MCP)     | only `/mcp`, `/api/*`, `/healthz`, `/version` | **bearer token** / webhook HMAC |

Behind both, the app itself enforces:
- **`WEB_HOSTS` allowlist (default-deny):** the UI is served *only* on hostnames you list.
  Any other host (the MCP subdomain, the raw `*.onrender.com` URL, anything spoofed) gets
  `404` for UI paths — only the token-gated endpoints answer. Miss the var → UI is locked
  everywhere but localhost. Fail-closed by design.
- **Origin lock (`CF_PROXY_SECRET`):** the app rejects any request that didn't come through
  your Cloudflare proxy (which injects a secret header), so the raw Render URL can't be used
  to bypass Access. `/healthz` and `/version` stay exempt so health checks/probes work.

---

## Self-host your own tenant

You need: a GitHub account, a free **Render** account, and a domain on **Cloudflare**.

### 1. Fork this repo
Public — code only, no data.

### 2. Create a private `dashboard-data` repo
Two folders at its root:
```
db/        # your YAML data (start from db.example/ in this repo)
storage/   # images, etc.
```
Seed it from the sample: copy this repo's `db.example/` to `db/` in the data repo, commit, push.

### 3. Give Render write access to the data repo (SSH deploy key)
The app commits your edits back, so it needs write access. A deploy key is scoped to this one
repo (safer than a personal token):
```bash
ssh-keygen -t ed25519 -f data_key -N "" -C dashboard-deploy
gh repo deploy-key add data_key.pub --repo <you>/dashboard-data --allow-write
base64 < data_key | tr -d '\n'      # copy this → DATA_DEPLOY_KEY_B64
```
(Alternatively use HTTPS: set `DATA_REPO_TOKEN` to a token with write access instead of the key.)

### 4. Deploy on Render
*New → Blueprint* → pick your fork (it reads `render.yaml`). Set these env vars when prompted:

| Var | Value |
|-----|-------|
| `DATA_REPO` | `git@github.com:<you>/dashboard-data.git` (SSH) — or the `https://…` URL if using a token |
| `DATA_DEPLOY_KEY_B64` | the base64 blob from step 3 (omit if using `DATA_REPO_TOKEN`) |
| `GIT_AUTHOR_NAME` | name for the auto-commits (default `dashboard`) |
| `GIT_AUTHOR_EMAIL` | email for the auto-commits |
| `WEB_HOSTS` | `dash.<your-domain>` — comma-separated; **the UI serves only on these** |
| `ALLOWED_EMAIL` | your email (informational; Cloudflare Access enforces the real gate) |
| `MCP_TOKEN` | a random secret the MCP endpoint requires (`openssl rand -hex 32`) |
| `WEBHOOK_SECRET` | a random secret to enable GitHub-webhook pulls (`/api/webhook`) |
| `CF_PROXY_SECRET` | a random secret for the origin lock — **set last**, see step 6 (`openssl rand -hex 32`) |
| `ENABLE_MAC` | `false` unless you set up the Mac bridge |

`render.yaml` builds the Dockerfile and health-checks `/healthz`. Verify a deploy landed by
hitting **`https://<your-render-url>/version`** — it returns the deployed commit SHA.

### 5. Cloudflare — DNS, TLS, Access
In your `<domain>` zone:

1. **DNS** — two proxied (🟠) CNAMEs → your Render URL:
   - `dash.<domain>` → `<your-service>.onrender.com`
   - `mcp.<domain>`  → `<your-service>.onrender.com`
   Add both as **Custom Domains** on the Render service too.
2. **TLS** — Render serves valid HTTPS, so use **Full (strict)**. If your zone default is
   *Flexible* (to not disturb other subdomains), add a per-host override instead:
   *Rules → Configuration Rules*, expression
   `(http.host in {"dash.<domain>" "mcp.<domain>"})`, set **SSL → Full (strict)**.
3. **Access** (*Zero Trust → Access → Applications → Add → Self-hosted*):
   - Application domain: **`dash.<domain>` only** (do **not** add the mcp host — it uses a
     token, not interactive login).
   - Policy: **Allow**, Include → Emails → your email.

### 6. Close the origin backdoor (origin lock)
Without this, anyone hitting the raw `*.onrender.com` URL bypasses Access.

1. *Rules → Transform Rules → Modify Request Header → Create*:
   - Expression: `(http.host in {"dash.<domain>" "mcp.<domain>"})`
   - **Set static** header `X-Proxy-Secret` = your `CF_PROXY_SECRET` value.
   - Deploy.
2. **Only then** set `CF_PROXY_SECRET` in Render (step 4). Order matters — if the header rule
   isn't live first, Cloudflare's own requests get `403`'d too.

**Verify:** `https://<render-url>/` → `403`, `https://dash.<domain>/` → Access login,
`https://mcp.<domain>/` → `404`, `https://mcp.<domain>/mcp` → `401`.
**Escape hatch:** delete `CF_PROXY_SECRET` in Render to disable the lock.

### 7. Connect MCP + webhook (optional)
- **MCP** — add `https://mcp.<domain>/mcp` as a remote connector in the Claude app, with the
  `MCP_TOKEN` as its bearer token.
- **GitHub webhook** — in the data repo: *Settings → Webhooks*, payload URL
  `https://mcp.<domain>/api/webhook`, content-type `application/json`, secret = `WEBHOOK_SECRET`.
  Lets out-of-band edits (a hand-push to the data repo) trigger an immediate pull.

Done — edits in the app commit back to your private repo automatically; git is your backup.

---

## Local development
```bash
make install          # venv + deps + `dash` alias
dash server up        # run locally (data from ./db, ./storage; UI open on localhost/LAN)
dash check            # smoke-test all pages render
dash --help           # CLI: reports, store scraping, health, styling, mac
```
Locally, `WEB_HOSTS` is unset so the UI is served on localhost/LAN automatically; no auth.
`DB_ROOT` / `STORAGE_ROOT` override the data location (default `./db`, `./storage`).

## Endpoints
| Path | Purpose |
|------|---------|
| `/` and feature pages | web UI (only on `WEB_HOSTS`, behind Access) |
| `/mcp` | MCP JSON-RPC (bearer `MCP_TOKEN`) |
| `/api/webhook` | GitHub webhook → pull data (HMAC `WEBHOOK_SECRET`) |
| `/api/sync` | manual "pull data now" |
| `/healthz` | liveness (always public) |
| `/version` | deployed commit SHA (always public) — use to confirm a deploy |

## Structural migrations
Data and code migrate together in a short window (no zero-downtime needed):
1. Pause the deployed app. 2. Clone `dashboard-data`, change code + write a migration script,
run it on the clone. 3. Push data + code. 4. Redeploy → new code + new data shape, consistent.

## Optional — My Mac bridge
Drive your Mac's terminal from your phone via the server over Tailscale: `ENABLE_MAC=true` +
`MAC_HOST` (its tailnet name) + a Tailscale auth key for the container. See `DEPLOY_PLAN.md`
in your data repo.

## License
MIT.
