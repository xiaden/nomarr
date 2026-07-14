# Task: SQL Core Primitives

## Problem Statement

Part A of the PostgreSQL migration creates the SQLAlchemy engine, session factory, and ORM models. Part B replaces `nomarr/persistence/aql/primitives.py` (~420 lines of ArangoDB AQL) with `nomarr/persistence/sql/primitives.py` (~200 lines of SQLAlchemy Core expressions). These primitives are the Tier 1 building blocks that every Tier 2 repository (Parts C and D) calls for basic CRUD — select, insert, upsert, update, delete, batch upsert, and emptiness check.

The existing AQL primitives operate on string collection names and `SafeDatabase` clients. The SQL primitives operate on SQLAlchemy `Table` objects and `AsyncSession` instances. The public exception contract (`PersistenceError`, `DuplicateKeyError` from `nomarr.persistence.exceptions`) is preserved — no PG-specific exceptions leak above this layer.

**Prerequisite:** TASK-postgresql-pgvector-migration-A-infrastructure-and-schema (models, engine, and session factory must exist).

## Phases

### Phase 1: Exception Mapping and Primitive Functions

- [ ] Create `nomarr/persistence/sql/__init__.py` as an empty package init that will later re-export primitives and exception helpers
- [ ] Create `nomarr/persistence/sql/exceptions.py` with `map_sqlalchemy_error(exc: SQLAlchemyError) -> PersistenceError` that converts `asyncpg.exceptions.UniqueViolationError` (via SQLAlchemy `IntegrityError`) to `DuplicateKeyError` and all other `SQLAlchemyError` subclasses to `PersistenceError`. Import `DuplicateKeyError` and `PersistenceError` from `nomarr.persistence.exceptions` — do not redefine them.
- [ ] Create `nomarr/persistence/sql/primitives.py` with `select_by_key(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> Row | None` — builds `select(table).where(table.c[key_col] == key_val)`, executes via `session.execute()`, calls `.fetchone()`, returns `None` when no row matches. Wraps execution in try/except that calls `map_sqlalchemy_error`.
- [ ] Add `select_many_by_keys(table: Table, keys: list, *, session: AsyncSession, key_col: str = "id") -> list[Row]` — short-circuits with `[]` when `keys` is empty, otherwise builds `select(table).where(table.c[key_col].in_(keys))`, executes, returns `.fetchall()`. Missing keys produce fewer results (no error).
- [ ] Add `insert_one(table: Table, data: dict, *, session: AsyncSession) -> Row` — builds `insert(table).values(**data)`, executes with `returning(table)`, calls `.fetchone()`. On `IntegrityError`, `map_sqlalchemy_error` raises `DuplicateKeyError`.
- [ ] Add `upsert_by_field(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row` — builds `insert(table).values(**data).on_conflict_do_update(index_elements=[field], set_={k: v for k, v in data.items() if k != field})` with `returning(table)`. The `set_` dict excludes the conflict field to avoid no-op self-assignment. Executes and returns `.fetchone()`.
- [ ] Add `update_by_field(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row | None` — builds `update(table).where(table.c[field] == match_val).values(**data)` with `returning(table)`. Returns `.fetchone()` or `None` when no row matches.
- [ ] Add `delete_by_key(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> None` — builds `delete(table).where(table.c[key_col] == key_val)`, executes. No return value; no error when key does not exist.
- [ ] Add `batch_upsert(table: Table, data_list: list[dict], conflict_fields: list[str], *, session: AsyncSession) -> list[Row]` — short-circuits with `[]` when `data_list` is empty, otherwise builds `insert(table).values(data_list).on_conflict_do_update(index_elements=conflict_fields, set_={col: getattr(excluded, col) for col in data_list[0].keys() if col not in conflict_fields})` with `returning(table)`. Executes and returns `.fetchall()`. Must be transactional — the caller manages the transaction boundary via `session`.
- [ ] Add `is_table_empty(table: Table, *, session: AsyncSession) -> bool` — builds `select(func.count()).select_from(table)`, executes, returns `True` when count is 0, `False` otherwise.

### Phase 2: Validation, Exports, and Tests

- [ ] Update `nomarr/persistence/sql/__init__.py` to export all eight primitive functions (`select_by_key`, `select_many_by_keys`, `insert_one`, `upsert_by_field`, `update_by_field`, `delete_by_key`, `batch_upsert`, `is_table_empty`) and the `map_sqlalchemy_error` exception mapper
- [ ] Run `ruff check nomarr/persistence/sql/` and `ruff format --check nomarr/persistence/sql/` — fix any lint or formatting issues
- [ ] Run `mypy nomarr/persistence/sql/` — fix any type errors. All function signatures must have complete type annotations. `Row` return types use `sqlalchemy.engine.Row`.
- [ ] Create `tests/unit/persistence/sql/__init__.py` and `tests/unit/persistence/sql/test_primitives.py` with unit tests that verify each primitive against an ephemeral PostgreSQL container via `testcontainers-python` (`PostgresContainer` fixture). Test cases: `select_by_key` returns `None` for missing key; `select_many_by_keys` returns `[]` for empty input and only-found rows for partial matches; `insert_one` raises `DuplicateKeyError` on constraint violation; `upsert_by_field` inserts when no match and updates when match exists; `batch_upsert` is transactional and returns all rows; `is_table_empty` returns `True` on fresh table and `False` after insert.
- [ ] Verify all tests pass: `pytest tests/unit/persistence/sql/ -v`

## Completion Criteria

- `nomarr/persistence/sql/primitives.py` exists with all 8 primitive functions, each using SQLAlchemy Core expressions and `AsyncSession`
- `nomarr/persistence/sql/exceptions.py` maps `IntegrityError` → `DuplicateKeyError` and `SQLAlchemyError` → `PersistenceError`
- `nomarr/persistence/sql/__init__.py` exports all primitives and the exception mapper
- `ruff check` and `mypy` pass clean on `nomarr/persistence/sql/`
- Unit tests pass against ephemeral PostgreSQL (testcontainers)
- No existing `aql/` files are modified — that scope belongs to Part F
- All functions use keyword-only `session: AsyncSession` parameter (enforced by `*` in signature)

## Contracts Exposed Downstream

| Function | Signature | Notes |
|---|---|---|
| `select_by_key` | `(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> Row \| None` | Returns `None` when no match |
| `select_many_by_keys` | `(table: Table, keys: list, *, session: AsyncSession, key_col: str = "id") -> list[Row]` | Empty keys → `[]`; missing keys silently omitted |
| `insert_one` | `(table: Table, data: dict, *, session: AsyncSession) -> Row` | Raises `DuplicateKeyError` on conflict |
| `upsert_by_field` | `(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row` | `ON CONFLICT (field) DO UPDATE` |
| `update_by_field` | `(table: Table, field: str, match_val: Any, data: dict, *, session: AsyncSession) -> Row \| None` | Returns `None` when no match |
| `delete_by_key` | `(table: Table, key_val: Any, *, session: AsyncSession, key_col: str = "id") -> None` | No error when key missing |
| `batch_upsert` | `(table: Table, data_list: list[dict], conflict_fields: list[str], *, session: AsyncSession) -> list[Row]` | Transactional; empty list → `[]` |
| `is_table_empty` | `(table: Table, *, session: AsyncSession) -> bool` | `True` when count == 0 |

## References

- Design doc: `artifacts/designs/pending/DD-postgresql-pgvector-migration.md` (Section 5: Persistence & Repository Architecture)
- Parts breakdown: `artifacts/designs/parts/postgresql-pgvector-migration/README.md`
- Existing AQL primitives being replaced: `nomarr/persistence/aql/primitives.py`
- Existing exceptions: `nomarr/persistence/exceptions.py` (`PersistenceError`, `DuplicateKeyError`)
- Part A plan: `TASK-postgresql-pgvector-migration-A-infrastructure-and-schema` (provides `Base`, models, `AsyncSession` factory)
