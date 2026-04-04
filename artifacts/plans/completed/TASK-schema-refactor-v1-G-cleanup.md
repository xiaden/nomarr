# Task: Schema Refactor v1 — Part G Final Cleanup

## Problem Statement
After Plans A-F complete all schema changes, Plan G consolidates the migration file, removes deprecated code, updates documentation, and runs final verification. No new schema changes — cleanup and validation only.

## Phases

### Phase 1: Migration AQL Ordering Verification
- [x] Review V021_schema_refactor_v1.py structure — ensure correct execution order: (1) collections, (2) indexes, (3) graphs, (4) data migrations, (5) field drops
- [x] Add section comments to organize AQL: `# === DDL: Collections ===`, `# === Data Migration ===`, `# === Cleanup ===`
- [x] Verify idempotency guards (IF NOT EXISTS, OPTIONS { ignoreErrors: true }, FILTER != null)
- [x] Run `lint_project_backend(path="nomarr/migrations")`

### Phase 2: Remove Deprecated Lock Code
- [x] Delete `nomarr/persistence/database/vector_promotion_lock_aql.py` (replaced by consolidated `locks`)
- [x] Update `nomarr/persistence/database/__init__.py` — remove `VectorPromotionLockOperations` export
- [x] Update `nomarr/persistence/db.py` — remove import and `self.vector_promotion_locks` instance
- [x] Update `nomarr/persistence/database/README.md` — remove row from table
- [x] Delete `tests/unit/persistence/database/test_vector_promotion_lock_aql.py`
- [x] Run `lint_project_backend(path="nomarr/persistence")`

### Phase 3: Create Consolidated LocksOperations
- [x] Create `nomarr/persistence/database/locks_aql.py` with `LocksOperations` class — methods: `try_acquire()`, `release()`, `cleanup_expired()`, `is_locked()`
    **Notes:** File already existed with full implementation including try_acquire, release, force_release, cleanup_expired, is_locked, get_stale_locks, complete_lock, get_lock_status
- [x] Register in `db.py` as `self.locks`
    **Notes:** Already registered as self.locks = LocksOperations(self.db)
- [x] Export from `persistence/database/__init__.py`
    **Notes:** Already exported from .locks_aql and in __all__
- [x] Update `ml_capacity_aql.py` probe lock functions → use `self.parent_db.locks`
    **Notes:** Already delegates via self.parent_db.locks calls
- [x] Update vector promotion callers → use `db.locks`
    **Notes:** Updated arango_bootstrap_comp.py: replaced ml_capacity_probe_locks and vector_promotion_locks with unified locks collection
- [x] Run `lint_project_backend(path="nomarr/persistence")`
    **Notes:** Lint passed: 0 errors across 22 files in nomarr/persistence

### Phase 4: Documentation Updates
- [x] Update `docs/dev/migrations.md` — add V021 summary
    **Notes:** Added Migration History section with V021 summary covering edge collections, data migrations, FK drops, and idempotency guarantees
- [x] Update `nomarr/persistence/database/README.md` — note graph traversal patterns
    **Notes:** Added Graph Traversal Patterns section with AQL examples for all edge collections
- [x] Run `lint_project_backend()`
    **Notes:** lint_project_backend passed: 0 errors across 39 files

### Phase 5: Success Criteria Verification
- [x] Run full `lint_project_backend()` — zero errors
    **Notes:** Full lint passed: 0 errors across 39 files checked
- [x] Verify imports: migration, Pydantic models, LocksOperations
    **Notes:** All three imports verified: V021_schema_refactor_v1.upgrade, Tag + SongHasTagsEdge, LocksOperations
- [x] Cross-check design doc success criteria checklist
    **Notes:** Design doc criteria verified: (1) FK properties replaced by edge traversals ✓, (2) Persistence modules use graph patterns ✓, (3) lint_project_backend passes with zero errors ✓, (4) Migration is idempotent via IF NOT EXISTS, FILTER guards, ignoreErrors ✓

## Completion Criteria
1. `lint_project_backend()` passes with zero errors
2. `python -c "from nomarr.migrations.V021_schema_refactor_v1 import upgrade"` succeeds
3. `python -c "from nomarr.persistence.database import LocksOperations"` succeeds
4. All design doc success criteria verified

## Decisions Made
| Decision | Rationale |
|----------|----------|
| `LocksOperations` as new unified class | Clean break from old pattern |
| Deprecated code deleted entirely | Alpha policy |
| Migration file organized with section comments | Clarity |
| Plans A-F must be complete before executing this plan | Dependency order |

## Dependencies
- **Plans A-F:** All must be complete — this plan is the final step
