# db.example

A complete, bootable placeholder dataset. It contains **no real data** — every
name, price, and reference is a generic sample so a fresh fork can start the app
and see all pages render.

## Boot with it

```bash
DB_ROOT=$(pwd)/db.example dash server up
# or copy it and edit in place:
cp -r db.example db && dash server up
```

## Layout

- `items/` — the shared item store. `kind: edible` (meals, snacks, supplements,
  care, hygiene) feed health/shopping/expenses; `kind: clothing` feeds styling;
  `kind: durable` is gear.
- `health/` — `weekly_plan` (meal slots → edible item keys), `batches` +
  `routine` (dosing/care), `nutrient_targets` (→ `nutrients/`), plus
  `profile`, `gym`, `monitoring`, `clinics`, `skin_clinic`.
- `nutrients/`, `edible_categories/`, `clothing_sections/`,
  `expense_categories/` — reference vocabularies.
- `expenses/recurring.yaml`, `income/models.yaml` — expense/income config. Each recurring entry's `frequency` is daily | workday | weekly | biweekly | monthly | yearly, and `category` is a `transactions/categories` key; an entry without `category` budgets Misc. (spending in categories with no budget).
- `planner/` + `planner_meta/board.yaml` — kanban tasks (`backlog`/`next`/`done`)
  and label ordering.
- `calendar/` — recurring (`day:`) and dated (`date:`) entries; `task_key`
  links an entry to a planner task.
- `styling/profile.yaml` — fit/size profile driving the styling review.
- `transactions/` — message parsing rules: `patterns.yaml` (regex per message
  template, `action: record | alert | ignore`), `cards.yaml` (last4/name →
  account display), `categories/` (one file per category with its rules: an exact vendor name or a transaction type such as `cash_withdrawal`, optional
  time `slot`, default `note`, and `type` override), `time.yaml` (timezone, when the day starts, the day of the month a budget period starts and the incoming vendor, such as Salary, that marks a period start when it lands within `period_marker_window_days` of it, weekend days and
  the time slots rules can target), `owner.yaml` (your own names and the wording of movements between your own accounts, such as card bill payments, so they count as self-transfers), `matching.yaml` (how close two messages must be to count as the same movement, the refund, self-transfer and statement windows, and which generic descriptions statements may replace), `counterparties.yaml` (names for counterparty account numbers found in statements), `statements/lines.jsonl` (transfer lines from `dash transactions statement-lines`), `fx.yaml` (pegged rates), `types.yaml` (transaction types and which count as
  spending). Categories, notes and refunds are derived live from these rules; a transaction stores only its
  manual `category_override` and `note`.
- `messaging/config.yaml` — Telegram `channels` and the senders the Mac relay forwards (`relay.senders`).

## Cross-references to keep valid when you edit

- Every `weekly_plan` meal-slot key and every `batches` `pool_key` must be an
  edible item key in `items/`.
- `nutrient_targets[].nutrient_key` must exist in `nutrients/nutrients.yaml`.
- Each edible item's `metadata.edible.category` must be an
  `edible_categories` key.
- `skin_clinic[].clinic_groups[].key` must be a key in `health/clinics.yaml`.
- `expense_categories[].category` must be a `transactions/categories` key.
- Calendar `task_key` must match a `planner/` task key.
