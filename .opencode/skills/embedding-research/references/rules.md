# Rules — DB, Report, and "Never Do"

Comprehensive rules governing DB access, report generation, and hard constraints.

---

## DB Layer Rules

- Never SELECT a column not in the schema. Verify in CONTRACTS.md Section 1 before adding any SELECT.
- `as_tuple()` order in `db/_types.py` must exactly match the INSERT column order in the upsert function. Divergence silently inserts values into wrong columns.
- ALTER TABLE guards (`ADD COLUMN IF NOT EXISTS`) are required only for columns added after the baseline schema. Columns already in `ensure_schema()` do not need guards.
- New columns require: DDL in `_schema.py` + guard in both `load_retrieval_flat` and `load_retrieval_binned`.

---

## Report Section Rules

Every `section_*` function must return a v2 dict with all 11 keys:

```
id  title  description  stats  charts  tables  panels
subsections  warnings  headline  empty_message
```

- `empty_message` is a non-empty string when no data is present; `None` or `""` when data exists.
- Never return early with a partial dict — callers check all 11 keys.
- Pass values to `make_table` unformatted; `make_table` calls `fmt()` internally.
- `disc_score_warning` must return `[]` on exception — never raise from it.

---

## Contract Sections Quick Reference

| Section | Covers |
|---------|--------|
| Section 1 | `db/_schema.py`, `db/_types.py`, `db/__init__.py`, all 20 DuckDB table schemas |
| Section 2 | `db/flat.py` — upsert/load functions, SQL column lists, conflict clauses |
| Section 3 | `similarity.py` — `compute_retrieval_metrics()` return dict, `ANNIndex` |
| Section 4 | `strategy_flat/_cache.py`, `_embed.py`, `_analyze.py`, `_truncate.py` |
| Section 5 | `strategy_binned/` — all 13 modules |
| Section 6 | `report/` — section functions, v2 section dict shape, `_base.py` constants |
| Section 7 | `run.py` pipeline phases, embed/classify skip logic, ID flow |

---

## Never Do

- Fix a crash in one layer without checking all connected layers. A metric change touches at minimum 5 files.
- Read a partial file range and assume the rest is clean. Read the whole relevant section.
- Remove a metric because it looks unused. Check `FLAT_COLUMNS`, `BINNED_COLUMNS`, and all report sections first.
- Return a plausible-looking value derived from wrong data. Log a WARNING and use `0.0` / `None` explicitly.
- SELECT `disc_album` or `recall_k_album`. These columns do not exist.
- Use `act[0]` for head scores. Always `act[1]`.
- Alter the `bin_idx` formula.
- Add `medoid` to `AGG_METHODS`. The validator raises `ValueError` on startup.
- Change `disc_general` to include zero-valued components. The WARNING is intentional.
