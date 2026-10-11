---
name: dashboard
description: >-
  Operate and maintain a self-hosted Personal Dashboard instance. One skill, three
  workflows: (A) everyday changes through the MCP tools, (B) local data edits
  reconciled with the live server via the flush → rebase → push → pull protocol,
  and (C) schema / code-coupled refactors done order-independently. Use whenever
  you add or change dashboard data, hand-edit the data repo (db/ or storage/), do a
  bulk or vocab/schema change the MCP tools don't cover, or need to reconcile local
  and server data — because the deployed app writes the same data repo and
  auto-commits constantly, so naive local pushes clobber or lose server data.
---

# Dashboard — operating the app and its data safely

## Architecture (read first)

A small Flask app backed by **plain YAML files in git** — no database. Two repos:

- **code repo** — the Flask app: per-domain blueprints (health, shopping, styling,
  expenses, mac, planner, calendar), each with its own `model.py` / `service.py` /
  `view.py` / `web.py`. Deploys as a container image.
- **data repo** — `db/**/*.yaml` (the content) + `storage/` (images, records).
  The single source of truth. The host is disposable; data lives in git.

**Privacy boundary — hard rule.** The code repo is public and meant to be forked.
Nothing personal or private goes into it: no names, health/financial details,
addresses, accounts, credentials, real item/task/entry keys, personal paths, or
example data drawn from a real instance — not in code, tests, comments, error
messages, docs, skills, or commit messages. Anything personal lives only in the
private data repo. Before committing to the code repo, scan the diff for leaks.

Writes go through a thin service layer exposed as **MCP tools**. A `check` command
renders every page locally (no server, no API) and is the fastest way to validate
data after any change.

## The core hazard: two writers, one data repo

1. **The deployed server** — every MCP/UI write mutates the server's working copy
   and the server **auto-commits + pushes** on a debounced timer. The remote branch
   moves on its own, constantly; a local checkout is almost always **behind**.
2. **Local hand-edits** — direct edits to `db/**/*.yaml`.

If both write around the same time the histories diverge → non-fast-forward pushes,
conflicts, or silently clobbered data. **Never interleave local file edits with MCP
writes, and never plain `git push` the data repo.** On a free-tier host, MCP writes
are also **volatile**: a cold-start re-clone from git silently drops anything not
flushed + pushed.

---

## Workflow A — everyday changes via the MCP tools

The normal path. Prefer it for anything the tools express.

- **Reads (always safe, anytime):** `report`, `profile`, `item_get`, `item_list`,
  `planner_list`, `calendar_list`, `styling_*` reads.
- **Writes:** `item_*`, `planner_*` (add/edit/move/check/rm), `calendar_*`
  (add/edit/check/uncheck/rm), `styling_*`.
- MCP writes land on the **server's** working copy and are flushed to git by the
  server's timer. To make them durable immediately (and before any local editing),
  call `data_push`. Each domain also has per-domain skills for the richer workflows
  (adding health items with sourced nutrition, styling research, task/calendar
  conventions) — use those for the domain rules.

Gotcha: the MCP calendar tools name the date field `date_` (trailing underscore);
the YAML files on disk use `date`. Same concept, two surfaces — don't mix them.

## Workflow B — local data edits, reconciled with the server

Use when a change needs direct file edits (something the tools can't do, a bulk
rewrite, or a model/schema-coupled change). Run from the data repo, **in order**:

1. **Flush the server FIRST.** Call `data_push` so the server commits + pushes its
   pending writes. This captures the server's latest state *before* you rebase onto
   it. `data_push` returning **"nothing to commit" is NOT proof of success** — it
   means the server tree is clean (e.g. right after a re-clone), not that your data
   is safely on the remote. Verify with git, never trust the message.
2. **Stop all MCP writes** for the duration (no `item_*`/`planner_*`/`calendar_*`/
   `styling_*` writes).
3. **Fetch + rebase, edit, commit, push.** `git fetch origin` →
   `git pull --rebase origin main` (being behind by many of the server's
   auto-commits is normal) → make the edits → commit → `git push`.
   - **Conflicts:** the server re-serializes YAML (field order, image lines), so a
     file you touched may conflict. Resolve by re-applying *your intended change* on
     top of the server's current serialization — don't blindly take a whole side.
   - **Never force-push** — it discards the server's auto-committed data.
4. **Make the server pull.** Call `data_pull` so the running app fast-forwards to
   your commit and reloads. A local push alone does NOT update the live copy.
5. **Resume MCP writes** only after step 4 succeeds, and **verify:**
   `git log --oneline -5` + `git status` (your commit is on the remote, tree clean)
   and `check` the touched domains (they report OK, not validation errors). Reload
   the live page if relevant.

## Workflow C — schema / code-coupled refactors

When a data change is coupled to a **code** change (adding or removing a model
field), code and data deploy on **different paths** (image rebuild vs. data-repo
pull) and can land out of order. Models reject unknown keys (`extra='forbid'`) and
missing required keys — so a mismatched code/data pair crashes loading.

Make the transition **order-independent** instead of trusting timing:

- **Adding a field** → give it a **default** so old data (without it) still loads.
  Deploy the **code first**, confirm it is live by calling the `version` MCP tool
  until it returns the new commit sha, then migrate the data (Workflow B) — old
  server code would reject data carrying the new key.
- **Removing a field** → first ship a release that makes it optional-with-default
  and stops *reading* it; once no data carries it, a later release deletes the
  field.

Either direction, neither deploy order can crash on the other's data.

**Keep the example data in step.** `db.example/` is what a fresh fork starts from.
Any schema change updates it in the same commit, and it must pass
`DB_ROOT=db.example check` alongside your real data — placeholders only, nothing
from a real instance.

---

## Tools reference

- `data_push` — force the server to commit + push pending data now (Workflow B
  step 1). "Nothing to commit" ≠ durable.
- `data_pull` — force the server to fast-forward pull (Workflow B step 4).
- `version` — the deployed code commit (`sha`, `branch`). Use it to confirm a code
  deploy is live before syncing data that depends on it (Workflow C).
- `report` / `profile` / `*_list` / `item_get` — reads; safe anytime.
- `check` (code CLI) — render pages locally to validate data without the server.

## Quick checklist (local edit → live)

- [ ] code-coupled? `version` shows the new sha before touching data
- [ ] `data_push` (flush server) — don't trust "nothing to commit"
- [ ] `git fetch` → `git pull --rebase` (resolve conflicts onto server serialization)
- [ ] edit → commit → `git push` (never `--force`)
- [ ] `data_pull` (sync server)
- [ ] verify: `git log`, `git status`, `check` the touched domains
