# Personal Dashboard

A self-hostable personal dashboard — health & nutrition plan, shopping list, styling,
budget, and a task manager + calendar — served as a small Flask app backed by plain YAML
files. No database: your data is **files in git**, which makes it versioned, portable, and
impossible to lose to a dead server.

## Design in one line
> **Your data is the crown jewel; the server is disposable.** The app runs from a code repo;
> your data lives in a separate private repo. The server pulls the data on boot and pushes
> changes back (debounced). Lose the host → redeploy, never lose data.

## Features
- **Task manager** (kanban: Backlog / To Pick / Planned / Missed / Done) + **Calendar**
  (recurring + one-off, linked to tasks).
- **Health plan** (weekly meals, nutrient targets, routines, gym, skincare), **Shopping list**
  (with live store price/stock), **Styling** pipeline, **Budget**.
- Glass UI, mobile-friendly, collapsible sections, PWA installable.
- CLI (`main.py`) to manage everything from a terminal; the same operations back the web UI.

---

## Self-host your own tenant

You need: a GitHub account, a free **Render** account, and (optional) a domain on
**Cloudflare** for private access.

1. **Fork this repo** (public — code only, no data).
2. **Create a private `dashboard-data` repo** with two folders:
   ```
   db/        # your YAML data (start from db.example/ in this repo)
   storage/   # images, etc.
   ```
   Seed it: `cp -r db.example db && git add . && commit && push` in that repo.
3. **Deploy on Render** → *New → Blueprint* → pick your fork (it reads `render.yaml`).
   Set these env vars (marked secret in the blueprint):
   | Var | What |
   |-----|------|
   | `DATA_REPO` | `https://github.com/<you>/dashboard-data.git` |
   | `DATA_REPO_TOKEN` | GitHub token with write access to the data repo |
   | `GIT_AUTHOR_EMAIL` | email for the auto-commits |
   | `ALLOWED_EMAIL` | your email (Cloudflare Access enforces the real gate) |
   | `MCP_TOKEN` | random secret if you want the MCP endpoint |
   | `WEBHOOK_SECRET` | random secret to enable `/api/webhook` pulls |
   | `ENABLE_MAC` | `false` unless you set up the Mac bridge |
   See `.env.example` for the full list.
4. **Lock it down (recommended):** put it behind **Cloudflare Access** — add a CNAME for
   `dashboard.<your-domain>` → the Render URL (proxied), and an Access policy allowing only
   your email. Now it's a public URL only you can open.

That's it — data changes made in the app commit back to your private repo automatically.

## Local development
```bash
make install          # venv + deps + `dash` alias
dash server up      # run locally (data from ./db, ./storage)
dash check          # smoke-test all pages render
dash --help         # CLI: planner / calendar / item / store / …
```
`DB_ROOT` / `STORAGE_ROOT` override the data location; unset = `./db` and `./storage`.

## Structural migrations
Data and code migrate together in a short window (no zero-downtime needed):
1. Pause the deployed app. 2. Clone `dashboard-data`, change code + write a migration script,
run it on the clone. 3. Push data + code. 4. Redeploy → new code + new data shape, consistent.

## Optional
- **MCP** (manage tasks conversationally from the Claude app) — exposed on
  `mcp.dashboard.<domain>` behind its own token. See `DEPLOY_PLAN.md`.
- **My Mac** (drive your Mac's terminal from your phone via the server over Tailscale) —
  `ENABLE_MAC=true` + `MAC_HOST` + a Tailscale auth key. See `DEPLOY_PLAN.md`.

## License
MIT.
