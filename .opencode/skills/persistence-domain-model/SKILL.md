---
name: persistence-domain-model
description: Nomarr persistence architecture — 3-tier PostgreSQL layer (primitives→repos→intent facades), ADR-041 domain-model gap, TypedDict DTO vs domain dataclass proliferation, ArangoDB→PostgreSQL migration state, and the V2 domain model redesign. Load when working on persistence layer, domain model, DTOs, database access, or evaluating rewrite-vs-repair.
---

# Persistence & Domain Model Architecture

## Mental Model

Nomarr's persistence layer is a well-structured 3-tier PostgreSQL architecture that survived a successful hard-cut migration from ArangoDB (~59% code reduction: 8,600→3,500 lines). Tier 1 (`sql/primitives.py`) provides 8 pure SQLAlchemy Core CRUD functions. Tier 2 (`database/*_repo.py`) has 15 table-scoped repository classes using Core `Table` operations (not ORM queries). Tier 3 (`api/*.py`) exposes 3 intent facades (`LibraryDb`, `AppDb`, `MlDb`) — the ONLY supported caller boundary.

The critical gap: **ADR-041 mandates domain dataclasses as the persistence-component contract, but zero facade methods comply.** The entire V1 codebase has only ONE domain dataclass (`Tag`/`Tags`). Everything else flows through 28 TypedDict DTO files — database row shapes (`SongRow`, `TagRow`) that couple every layer to the storage schema. The V2 redesign (`v2/`) has the right domain dataclasses (Song, Library, EmbeddingStream, ClassifierChain) but they exist as unused scaffolding with empty component directories and contradictory `from_db_doc()` factories that couple them back to storage shapes.

## Coverage

**Documented:** PostgreSQL 3-tier persistence architecture, intent facade API surface, TypedDict DTO proliferation problem (quantitative inventory 2026-08-19: 422 classes, 60 exact-shape / 100 names-only duplicate families), ADR-041 compliance gap, V2 domain dataclass state, ArangoDB migration status (no `_id`/`_key`/`_rev` outside persistence), migration infrastructure (Alembic), architecture enforcement tests

**Not yet documented:** Detailed per-repo method API, V2 dataclass→V1 integration plan, frontend persistence coupling, Navidrome-specific persistence patterns

**Last extended:** 2026-08-19

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

- **DTO duplication:** 28 files in `helpers/dto/`, four separate tag representations (`tags_dataclass.py` domain, `v2/.../tags_dataclass.py` copy, `tags_dto.py` DTO, `repo_dto.py` TagRow) plus `song_class.Tag` and `FileTag`/`TagSongItem` — see Domain Identity Audit
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

## Domain Identity Audit (2026-08-19, read-only)

Read-only domain-correctness audit of identity semantics across entities/DTOs/value objects. Key findings (all with locations; confidence high unless noted):

- **Tag row shape divergence (live KeyError):** `song_tags_comp.get_song_tags_with_path` emits `{key, name, value, is_nomarr_tag}` — NO `type` key (song_tags_comp.py:39-47). Consumers `library_svc/songs.py:87-95` and `tagging_svc/query.py:210-218` read `tag["type"]` → `KeyError: 'type'` on `GET /file/{id}/tags` (route songs_if.py:209-218) whenever tags exist. A parallel shape `_project_tag_row` (library_song_query_comp.py:165-173) emits `{key, value, type, is_nomarr}` matching `map_song_with_tags_to_dto` — two incompatible shapes for the same concept, attribute named `is_nomarr` vs `is_nomarr_tag`.
- **Four copies of the Tag value object:** `helpers/dataclasses/tags_dataclass.py` (`Tag(name, values)` — ADR-041 domain canonical, ZERO real consumers), `helpers/dto/tags_dto.py` (`Tag(key, value)` — the one actually imported by 10+ components/workflows; field named `key` not `name`; divergent `get_values`: raises KeyError vs returns `()`), `components/library/songs/song_class.py` (`Tag(name, value: str)` scalar — dead module), and `v2/.../tags_dataclass.py` (verbatim copy of the V1 dataclass).
- **Identity type drift (str vs int):** `LibraryTrack.file_id: str` / `MatchedFileInfo.file_id: str` (playlist_import, `str(row.get("id") or "")` silent empty default at track_matcher_comp.py:52); `save_song_tags(db, song_id: str, ...)` (song_sync_comp.py:48-64) while `mark_song_processed` takes `int` (song_sync_comp.py:31) and workflows pass ints with `# type: ignore[arg-type]` (sync_file_to_library_wf.py:60,66,77,91); `SongListForEntityResult.song_ids: list[str]` via `str(sid)` (metadata_svc.py:145); `LibraryPipelineInfo.library_id: str` vs `ScanningLibraryInfo.library_id: int` in same module (info_dto.py:111 vs 121); `LibraryCalibrationStatus.library_id: str` (calibration_dto.py:80); `TagSongItem.file_id: str` (tag_curation_dto.py:47). Frontend `LibraryFile.file_id: string`/`library_id: string`/`tagged: boolean` (files.ts:15,17,26) vs backend int (library_types.py:259,261,271).
- **Path conflated with identity:** `get_song_by_path_unscoped` = `WHERE path = ? LIMIT 1` no ORDER BY (song_repo.py:86-92); `remove_song_by_path` unscoped (library_songs.py:328-343); `delete_songs_by_paths` (library_song_mutation_comp.py:130-148) — but path is only unique per `(library_id, path)` (song.py:44-46). Same path in 2 libraries → nondeterministic delete target.
- **V2 dataclass defects:** `EmbeddingStream.__post_init__` and `VectorEntry.__post_init__` reference `self.id`/`self.file_id` which are NOT fields → AttributeError on EVERY construction (embedding_dataclass.py:45-62, 92-104) — unconstructible. V2 `Song` has NO id field yet docstring claims `(id, path, normalized_path, library_id, library_key)` (song_dataclass.py:9-12) and `from_path()` passes `id=` → TypeError (kw_only); `_TUPLE_DOC_FIELDS` artists/labels/genres dead branches; `status`/`tagged`/`is_valid` attributes duplicate the edge-based state machine. V2 `Library.id: str` = `"libraries/12345"` + `key` property + `from_db_doc` reads `doc["_id"]` (library_dataclass.py:54-56,148-196) — reintroduces Arango-style qualified string ids the layer conventions ban; `OutputStream.from_db_doc` reads `doc["_id"]` too (embedding_dataclass.py:160-177).
- **Legacy identity machinery still live:** `library_id_comp.py` `normalize_library_id`/`library_key_from_ref` implement `"libraries/{key}"` string identity (0 production callers, not allowlisted — dead); `library_scan_state_comp.py:42-44` `_scan_doc_id` builds `"library_scans/{key}"` (unused, dead). `get_song_library_key` returns int id but keeps legacy "key" naming (library_song_mutation_comp.py:151-157).
- **DTO mutability:** `helpers/dto/README.md:35` claims "Most DTOs use @dataclass(frozen=True)" but ~9 of 102 `@dataclass` definitions are frozen (tags_dto, playlist_import, path_dto, hydration_dto) — the rest are mutable/unhashable.
- **Dual-typed fields:** `LibraryDict.created_at: str | int` (library_dto.py:58-59) — DTO cannot decide its own type.

Related logged research: L99 (tag_id contract gap: components pass {name,value}, persistence requires tag_id), L93 (state identity bugs: `ensure_song_state("tagged")` ValueError, remove-all/re-add transitions), L94/L103 (scan row legacy keys files_total/completed_at vs files_found/finished_at), L97 (output id/model_id contract mismatch, ml_output_streams schema).

## Quantitative DTO Proliferation Inventory (2026-08-19, second independent pass)

Read-only AST inventory (scripts `/tmp/dto_inventory/inventory.py`, `pass2.py`; repo untouched). Classifier: `@dataclass` frozen/mutable, TypedDict (incl. total=False), Pydantic v2 BaseModel, NamedTuple, Protocol, orm-model (`mapped_column`), plain. Duplicate families computed on flattened (inherited) normalized field signatures, two passes: exact (name+type) and names-only (type-drift tolerant). See log L111 for full evidence.

**Grand totals (422 classes):** dataclass 159 (21 frozen / 138 mutable), TypedDict 66 (incl. 2 total=False), BaseModel 152, NamedTuple 1, Protocol 3, orm-model 24, plain 17.

**By category:** helpers/dto 155 (7F+104M+43TD+1Proto across 27 modules; `__init__` exports 50 names); helpers/dataclasses 2 (Tag/Tags); persistence/models 24 orm; persistence/repos 0 + persistence/api 0 (row TypedDicts live in `helpers/dto/repo_dto.py`, 14 rows); interfaces/api/types 114 BaseModel; interfaces/api/web+v1 38+1; components 40 (7F+17M+12TD+1NT+3plain); workflows 8 (6M+1TD+1Proto); services 30 (9M+7TD+1Proto+13plain).

**Duplicate families: 60 exact-shape, 100 names-only.** ~40 exact families are the sanctioned helpers/dto ↔ interfaces/types BaseModel `.from_dto()` boundary (mechanical, low risk). HIGH-RISK true duplicates:
- 5 classes share `{status, message}`: `calibration_types.BackgroundStartResponse`, `config_types.ConfigUpdateResponse`, `web/admin_if.RestartResponse`, `web/library_if.DeleteLibraryResponse` + `ClearLibraryDataResponse`
- `repo_dto.MetaRow` == `repo_dto.LockRow` (same module, `{key, value}`)
- `generate_calibration_wf.py:81 CompareCalibrationsResult` == `:95 CalculateHeadDriftResult` (identical, same file, 8 fields)
- `ml_output_stream_store_comp.StreamWrite`/`StreamRecord` (frozen) == `processing_dto.DeferredOutputStreamWrite` `{output_id, output_index, values}`
- `descriptor_match_comp.TrackDescriptor` == `navidrome_types.TrackDescriptorResponse` == `navidrome_v1_if.SeedTrackDescriptor` (9-field triplication)
- `analytics_comp.DominantVibeResult` == `analytics_dto.DominantVibeItem` == `analytics_types.DominantVibeItemResponse`; `CollectionOverviewResult` + `MoodAnalysisResult` defined BOTH in components/ and `analytics_dto.py` (same-name across modules)
- services: `tagging_svc/config.py ApplyCalibrationResultDict` == `recalibration_dto.ApplyCalibrationResult` == `calibration_types.ApplyCalibrationResultResponse`; `calibration_svc.py:66 HistogramGenerationCombinedStatusDict` == `calibration_types.HistogramGenerationStatusResponse` (11 fields exact)
- ORM vs rows: all 11 `repo_dto` Row TypedDicts mirror `persistence/models` ORM shapes (`SongRow`↔`Song` 17 fields) — by-design dual representation, Mapped[] vs plain types
- `find_similar_tracks_wf.SimilarTrackResult` == `navidrome_v1_if.SongDescriptor` (10 fields); `tag_curation_dto` 8 TypedDicts ↔ `tag_curation_if` 16 inline BaseModels (web layer defines models inline instead of types/ package)

**Tag family current state (dirty tree, migration in flight):** `helpers/dto/tags_dto.py` is now a re-export shim of `helpers/dataclasses/tags_dataclass.py` (0 class defs); `components/library/songs/song_class.py` deleted in tree; `v2/nomarr/helpers/dataclasses/tags_dataclass.py` still holds a duplicate Tag/Tags (plus song/embedding/library/classifier dataclasses). Live tree = 2 defs + 1 v2 scaffold (was 4 pre-migration). Untracked `.opencode/skills/tag-dataclass-migration/` holds the migration notes.

**Ownership boundary violations** (nomarr-layers: DTOs belong in helpers/dto): components define 40 shape classes (incl. `track_matcher_comp.LibraryTrack`, `descriptor_match_comp.TrackDescriptor`, analytics results); workflows 8; services 30 (config dataclasses + status TypedDicts). helpers/dto stays pure (no nomarr.* imports) — violations are LOCAL definitions, not imports.

**Recommended first remediation slice:** (1) `{status, message}` 5-class family → one shared response model; (2) merge `CompareCalibrationsResult`/`CalculateHeadDriftResult`; (3) `StreamWrite`/`StreamRecord` → `processing_dto`; (4) component analytics results → `analytics_dto` canonical, delete component TypedDicts; (5) merge `repo_dto.MetaRow`/`LockRow`; (6) move `tag_curation_if` inline models into types/; (7) delete v2 tag scaffold after migration. Do NOT consolidate the sanctioned dto↔types `.from_dto()` boundary.

## Sources

- ADR-032: Domain-Model Boundary — Persistence Returns Only Domain Objects
- ADR-040: PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB
- ADR-041: Domain Dataclasses as the Persistence-Component Contract
- `nomarr/persistence/PERSISTENCE.md` — Comprehensive persistence layer documentation
- `docs/dev/architecture.md` — Intended architecture and layer design
- `tests/sabotage/test_no_arango_naming.py` — Live Arango-naming enforcement (ADR-042)
- `tests/test_architecture_qc.py` — Architecture QC tier bans + import-linter contracts
