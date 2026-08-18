---
name: persistence-domain-model
description: Nomarr persistence architecture — 3-tier PostgreSQL layer (primitives→repos→intent facades), ADR-041 domain-model gap, TypedDict DTO vs domain dataclass proliferation, ArangoDB→PostgreSQL migration state, and the V2 domain model redesign. Load when working on persistence layer, domain model, DTOs, database access, or evaluating rewrite-vs-repair.
---

# Persistence & Domain Model Architecture

## Mental Model

Nomarr's persistence layer is a well-structured 3-tier PostgreSQL architecture that survived a successful hard-cut migration from ArangoDB (~59% code reduction: 8,600→3,500 lines). Tier 1 (`sql/primitives.py`) provides 8 pure SQLAlchemy Core CRUD functions. Tier 2 (`database/*_repo.py`) has 15 table-scoped repository classes using Core `Table` operations (not ORM queries). Tier 3 (`api/*.py`) exposes 3 intent facades (`LibraryDb`, `AppDb`, `MlDb`) — the ONLY supported caller boundary.

The critical gap: **ADR-041 mandates domain dataclasses as the persistence-component contract, but zero facade methods comply.** The entire V1 codebase has only ONE domain dataclass (`Tag`/`Tags`). Everything else flows through 28 TypedDict DTO files — database row shapes (`SongRow`, `TagRow`) that couple every layer to the storage schema. The V2 redesign (`v2/`) has the right domain dataclasses (Song, Library, EmbeddingStream, ClassifierChain) but they exist as unused scaffolding with empty component directories and contradictory `from_db_doc()` factories that couple them back to storage shapes.

## Coverage

**Documented:** PostgreSQL 3-tier persistence architecture, intent facade API surface, TypedDict DTO proliferation problem, ADR-041 compliance gap, V2 domain dataclass state, ArangoDB migration status (no `_id`/`_key`/`_rev` outside persistence), migration infrastructure (Alembic), architecture enforcement tests

**Not yet documented:** Detailed per-repo method API, individual DTO file contents, V2 dataclass→V1 integration plan, frontend persistence coupling, Navidrome-specific persistence patterns

**Last extended:** 2026-08-18

## Key Files

| Concern | Canonical File |
|---------|---------------|
| Database facade + DI wiring | `nomarr/persistence/db.py` |
| PostgreSQL engine, session factory | `nomarr/persistence/pg_engine.py` |
| Tier 1 SQL Core primitives | `nomarr/persistence/sql/primitives.py` |
| SQLAlchemy error mapping | `nomarr/persistence/sql/exceptions.py` |
| Library intent facade | `nomarr/persistence/api/library.py` |
| App-state intent facade | `nomarr/persistence/api/application.py` |
| ML intent facade | `nomarr/persistence/api/ml.py` |
| Song repository (songs table) | `nomarr/persistence/database/song_repo.py` |
| Library repository | `nomarr/persistence/database/library_repo.py` |
| Tag repository | `nomarr/persistence/database/tag_repo.py` |
| Shared repository helpers | `nomarr/persistence/database/repo_helpers.py` |
| ORM models (30 files) | `nomarr/persistence/models/*.py` |
| Persistence layer documentation | `nomarr/persistence/PERSISTENCE.md` |
| V1 domain dataclass (only one) | `nomarr/helpers/dataclasses/tags_dataclass.py` |
| DTO TypedDicts (28 files) | `nomarr/helpers/dto/*.py` |
| Repository return types | `nomarr/helpers/dto/repo_dto.py` |
| V2 Song domain dataclass | `v2/nomarr/helpers/dataclasses/song_dataclass.py` |
| V2 Library domain dataclass | `v2/nomarr/helpers/dataclasses/library_dataclass.py` |
| V2 Classifier dataclasses | `v2/nomarr/helpers/dataclasses/classifier_dataclass.py` |
| V2 Embedding dataclasses | `v2/nomarr/helpers/dataclasses/embedding_dataclass.py` |
| Arango-naming sabotage enforcement | `tests/sabotage/test_no_arango_naming.py` |
| Architecture enforcement tests | `tests/test_architecture_qc.py` (tier bans) + import-linter contracts |
| Alembic migration env | `alembic/env.py` |
| Alembic baseline migration | `alembic/versions/001_initial_v1_baseline_schema.py` |
| App DI container | `nomarr/app.py` |

## Critical Invariants

1. **Tier 3 intent facades are the ONLY persistence boundary.** Higher layers must NOT import `nomarr.persistence.database` or `nomarr.persistence.sql` directly. Enforced by `test_higher_layers_do_not_import_persistence_tier1_or_tier2_internals()`.

2. **ADR-041 requires domain dataclasses as the contract.** Persistence methods must accept and return domain model objects — NOT TypedDicts, NOT raw dicts, NOT storage shapes. Currently aspirational, not enforced.

3. **Persistence returns raw data shapes, not domain objects.** This is the current state but violates ADR-041. All facade methods return TypedDicts (`SongRow`, `TagRow`, etc.) — changing this requires updating all callers.

4. **No ArangoDB field names (`_id`/`_key`/`_rev`) outside persistence.** Field names use `id`/`key`/`rev`. Live enforcement is `tests/sabotage/test_no_arango_naming.py` (scans non-persistence dirs) plus `tests/test_architecture_qc.py` tier bans and import-linter contracts (ADR-042). The former `.arango-field-allowlist.yaml` / ripgrep / grimp enforcement was removed.

5. **Essentia imports locked to 2 files only.** Components `ml_audio_comp.py` and `ml_preprocess_comp.py` ONLY. Enforced by architecture test.

6. **Workflows must not import services or app.** Enforced by architecture test. DI via parameters.

## ML Facade Write Atomicity (2026-08-18)

Findings from research on the reported ML persistence facade issue (`nomarr/persistence/api/ml.py` L258-379).

- **The atomicity gap is real and documented in docstrings as "Part F" deferred work:** `replace_output_streams_for_song` (ml.py:300) and `replace_song_vectors` (ml.py:327) are delete-then-insert where the delete and EACH insert commit independently (each repo method does `begin_nested()` + `commit()`). An insert failure after the delete leaves partial state.
- **AR-SDR-4 forbids the Part F docstring's suggested fix.** Facades must NOT expose `transaction()`/`_require_transaction` (enforced by `tests/unit/test_transaction_guard.py` + `tests/sabotage/test_no_facades_begin_transactions.py`); repos own short internal transactions. The atomicity mechanism that complies: **one repo method wrapping all statements in a single `begin_nested()` + one `commit()`** — all repos share ONE `scoped_session` (db.py:69), so a single repo method can atomically span cross-table work.
- **Contract mismatch bug:** `ml_output_stream_store_comp.upsert_output_streams` sends `{output_id, values}` payloads but `replace_output_streams_for_song` reads `payload["model_id"]`/`["status"]` → KeyError at runtime in `discovery_worker._execute_deferred_writes` (discovery_worker.py:119). The `model_id` FK → `ml_models.id` would also reject Arango-era output ids like `ml_model_outputs/out-1`.
- **Table mismatch in OutputRepo:** `delete_outputs_for_song` deletes from `ml_model_outputs`; `store_output_stream` inserts into `ml_output_streams`; `get_outputs_for_song` reads `ml_model_outputs`. Delete/insert/read target different tables.
- **Unbounded delete bug:** `replace_song_vectors` deletes ALL embeddings for a song across ALL backbones, then inserts one backbone's row. `process_file_wf.py:164` calls `persist_backbone_vector` per backbone in a loop → each backbone wipes the previous one's rows. Replace must be backbone-scoped (`DELETE … WHERE song_id = ? AND backbone_id = ?`).
- **Schema can't store canonical streams:** `ml_output_streams` (alembic 001:214-227) has only id/song_id/model_id/status/created_at — no output_id/values columns. ADR-038 / DD-canonical-raw-output-stream-persistence values require an alembic change.
- **Embedding stream write path is unwired:** `replace_embedding_stream_for_song` / `remove_embedding_streams_for_song` have zero production callers (test-only); `ml_embedding_streams` has no UNIQUE(song_id, backbone_id) (select-then-insert race).
- **Recommended smallest fix:** new atomic repo method (single tx across embeddings + streams) exposed as `MlDb.replace_song_inference_results(song_id, backbone, *, vectors, output_streams)`; fix backbone-scoped delete; fix stream payload contract; migrate callers (discovery_worker.py, process_file_wf.py, ml_vector_persist_comp.py, library_song_query_comp.py); wire repo in db.py.

## Agent Proliferation Patterns (Known)

- **DTO duplication:** 28 files in `helpers/dto/`, three separate tag representations (`tags_dataclass.py` domain, `tags_dto.py` TypedDict, `repo_dto.py` TagRow)
- **Naming inconsistency:** `ModelRepo`/`OutputRepo` (short suffix) vs `LibraryRepository`/`SongRepository` (full suffix)
- **Legacy coexistence:** Deprecated `PersistenceError` lives alongside canonical `DatabaseStateError`; facade `.maintenance` surfaces contain documented no-ops
- **V2 self-contradiction:** V2 dataclasses have `from_db_doc()` methods that couple them to storage shapes — the exact pattern ADR-041 prohibits

## Architecture Diagram

```
interfaces → services → workflows → components → (persistence / helpers)
                                                  │
                                                  ├── api/  (LibraryDb, AppDb, MlDb)  ← ONLY caller boundary
                                                  │   └── .maintenance (destructive ops)
                                                  ├── database/  (15 repos)           ← internal
                                                  │   └── repo_helpers.py
                                                  ├── sql/  (primitives.py)           ← internal
                                                  └── models/  (30 ORM models)
```

## V2 Redesign State

V2 lives in `v2/nomarr/` and contains:
- `helpers/dataclasses/` — 5 domain dataclass files (correct shapes, wrong factories)
- `components/domain/` — empty directories (songs/, libraries/, embeddings/, classifiers/, metadata/)
- `components/infrastructure/` — empty directories (filesystem/, maintainance/, onnx/, workers/)

**To make V2 operational:** (1) Remove all `from_db_doc()` methods from V2 dataclasses. (2) Add persistence mappers in `database/` (DB row → domain dataclass). (3) Update facade methods to return domain dataclasses. (4) Update all callers from TypedDict access to attribute access. (5) Keep the sabotage/arch-QC enforcement green (no ArangoDB field names outside persistence).

## Sources

- ADR-032: Domain-Model Boundary — Persistence Returns Only Domain Objects
- ADR-040: PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB
- ADR-041: Domain Dataclasses as the Persistence-Component Contract
- `nomarr/persistence/PERSISTENCE.md` — Comprehensive persistence layer documentation
- `docs/dev/architecture.md` — Intended architecture and layer design
- `tests/sabotage/test_no_arango_naming.py` — Live Arango-naming enforcement (ADR-042)
- `tests/test_architecture_qc.py` — Architecture QC tier bans + import-linter contracts
