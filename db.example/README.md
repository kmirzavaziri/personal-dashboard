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
  `expense_accounts/`, `expense_categories/` — reference vocabularies.
- `expenses/recurring.yaml`, `income/models.yaml` — expense/income config.
- `planner/` + `planner_meta/board.yaml` — kanban tasks (`backlog`/`next`/`done`)
  and label ordering.
- `calendar/` — recurring (`day:`) and dated (`date:`) entries; `task_key`
  links an entry to a planner task.
- `styling/profile.yaml` — fit/size profile driving the styling review.

## Cross-references to keep valid when you edit

- Every `weekly_plan` meal-slot key and every `batches` `pool_key` must be an
  edible item key in `items/`.
- `nutrient_targets[].nutrient_key` must exist in `nutrients/nutrients.yaml`.
- Each edible item's `metadata.edible.category` must be an
  `edible_categories` key.
- `skin_clinic[].clinic_groups[].key` must be a key in `health/clinics.yaml`.
- `expense_categories[].account` must be an `expense_accounts` key.
- Calendar `task_key` must match a `planner/` task key.
