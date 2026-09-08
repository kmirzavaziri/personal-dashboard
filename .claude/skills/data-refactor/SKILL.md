---
name: data-refactor
description: Safely change dashboard DATA locally (schema/vocab changes, bulk refactors, edits the MCP tools don't cover) without racing the deployed server's own writes to the data repo.
---

# Local data refactors without a data-repo race

## The problem

The dashboard has **two writers to the same data repo**:

1. **The deployed server** — every MCP write (`item_*`, `styling_*`, `planner_*`, `calendar_*`) mutates the server's working copy of the data, and the server commits + pushes it on a debounced timer.
2. **You, editing files locally** — direct edits to `db/**/*.yaml` in the local data repo (for things MCP can't do: adding a section/vocab entry, model/schema-coupled changes, bulk rewrites).

If both write around the same time, the two histories diverge → non-fast-forward pushes, merge conflicts, or silently clobbered data. **Never interleave local file edits with MCP writes.**

## The protocol (follow in order)

Whenever a change needs local file edits:

1. **Flush the server.** Call MCP `data_push`. The server commits + pushes everything it has pending. Now the data repo == server state, with nothing pending server-side.
2. **Stop all MCP writes** for the duration of the refactor. No `item_*`/`styling_*`/`planner_*`/`calendar_*` writes.
3. **Edit locally.** `git pull` the data repo (to pick up what step 1 just pushed), make your file edits, commit, push.
4. **Make the server pull.** Call MCP `data_pull` (or `POST /api/sync`). The server fast-forwards to your commit and reloads.
5. **Resume MCP writes** only after step 4 succeeds.

Reads (`report`, `profile`, `item_get`, `*_list`) are always safe.

## Code-coupled changes (schema / model)

If the data change is coupled to a **code** change (e.g. adding or removing a model field), the code and data deploy on **different paths** (image rebuild vs. data-repo pull), so they can land out of order. Models use `extra='forbid'` and reject unknown keys, and required fields reject missing keys — so a mismatched code/data pair crashes loading.

**Make the transition order-independent instead of relying on timing:**
- Adding a field → give it a **default** so old data (without it) still loads.
- Removing a field → **first** ship a release that makes it optional-with-default and drops the *behavior* (stop reading it); once all data no longer carries it, a later release can delete the field entirely.

This way neither deploy order can crash on the other's data.

## Tools

- `data_push` — force the server to commit + push pending data now (step 1).
- `data_pull` — force the server to fast-forward pull (step 4).
- `profile` — read health + styling profile (context, goals, fit targets); grounds decisions without a write.
