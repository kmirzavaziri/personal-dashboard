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
| `mcp.<domain>` (MCP)     | `/mcp` + `/api/*` | **default-deny bearer token** (whole host) |

Every request passes two app-level gates, in order:

1. **Origin lock (`CF_PROXY_SECRET`):** reject anything that didn't arrive through your
   Cloudflare proxy (which injects a secret header). This closes the raw `*.onrender.com`
   backdoor and — critically — makes **`Host`-header spoofing impossible**: the app can't
   distinguish a forged `Host: dash.<domain>` from a real one on its own, so it trusts the
   CF-only header instead. Only `/healthz` is exempt (Render's health probe; it returns just
   `"ok"`).
2. **Authorization:**
   - **UI hosts** (those in `WEB_HOSTS`) → allowed; Cloudflare Access already gated the whole
     host at the edge with interactive SSO.
   - **Every other host** (the MCP subdomain, the raw Render URL, anything spoofed) →
     **default-deny**: the request must carry a valid `Authorization: Bearer <MCP_TOKEN>`,
     or be a GitHub webhook with a valid HMAC signature. Otherwise `401`. Nothing is
     allow-listed per-path, so no endpoint can be accidentally left open.

`WEB_HOSTS` is **fail-closed**: leave it unset and the UI serves nowhere but localhost. So a
misconfigured deploy hides the UI rather than exposing it.

### Why spoofing can't get in
- Skip Cloudflare and hit the origin directly → no secret header → `403`.
- Point your own domain/proxy at the origin → you don't know the 256-bit secret → `403`.
- Forge `Host: dash.<domain>` at the origin → origin lock fires *before* the host check → `403`.
- Enter via the mcp edge with a forged `Host` → Cloudflare forwards the edge hostname it
  served, not your header → treated as the mcp host → `401`.
- Forge `X-Forwarded-Host` → ignored; the app reads the real `Host` (no `ProxyFix`).

**Two invariants this rests on — don't break them:**
1. **Keep `CF_PROXY_SECRET` set in production.** It is what defeats Host-spoofing; unsetting it
   (the escape hatch) reopens that door, so use it only in an emergency.
2. **Serve both hosts over Full (strict), never Flexible.** On a Flexible zone the CF→origin
   hop is plaintext HTTP and the bearer token would leak there — the per-host Configuration
   Rule in step 5 fixes this.

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
`https://mcp.<domain>/` → `401`, `https://mcp.<domain>/mcp` (no token) → `401`.
**Escape hatch:** delete `CF_PROXY_SECRET` in Render to disable the lock (emergency only — it
reopens Host-spoofing; see *Why spoofing can't get in*).

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
| Path | Purpose | Reachable |
|------|---------|-----------|
| `/` and feature pages | web UI | UI hosts only, behind Access |
| `/mcp` | MCP JSON-RPC | bearer `MCP_TOKEN` |
| `/api/webhook` | GitHub webhook → pull data | HMAC `WEBHOOK_SECRET` |
| `/api/sync` | manual "pull data now" | UI host (via Access) or bearer token |
| `/version` | deployed commit SHA | UI host (via Access) or bearer token |
| `/healthz` | liveness — returns `"ok"` | always public (Render health check) |

Confirm a deploy: open `/version` in the browser on the UI host, or
`curl -H "Authorization: Bearer <MCP_TOKEN>" https://mcp.<domain>/version`.

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
