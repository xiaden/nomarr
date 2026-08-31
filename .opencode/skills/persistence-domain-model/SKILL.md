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

**Last extended:** 2026-08-30 (song-tag facade migration state, log L126)

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
| Alembic baseline migration | `alembic/versions/001_current_schema_baseline.py` |
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

- **Tag row→FileTag projection (resolved TASK-tag-boundary-A):** row-to-library contract conversion is centralized in `tag_mapping_comp.file_tag_from_tag_row`; both song-tag query paths (`song_tags_comp.get_song_tags_with_path`, `library_song_query_comp._tags_for_song`) and `map_song_with_tags_to_dto` consume/pass through `FileTag` objects (key/value/tag_type/is_nomarr) rather than raw dict rows. The previous dual in-component helpers (`_project_tag_row` in library_song_query_comp.py, `_FileTagItem` in song_tags_comp.py) and the `KeyError: 'type'` divergence they caused were both removed.
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

## Independent False-Negative Audit of DTO Claims (2026-08-19)

Static AST + repo-wide reference audit (grep/aft_search incl. tests, scripts, docs, TYPE_CHECKING, importlib/getattr; ~30 tool calls). Audited the inventory's HIGH-RISK duplicate + dead-candidate claims. Corrections and additions:

**Corrections to the inventory:**
- `tags_dto` shim: NOW **zero importers** (inventory's "4 test files" is stale — those tests migrated to tags_dataclass). More deletable than claimed; docs/skills still name it in 4 places (helpers/dto/README.md:30, HELPERS.md:54, nomarr-tags SKILL ×2).
- `tagging_svc/config.py` `ApplyCalibrationResultDict:11-17` + `ApplyCalibrationStatusDict:20-25`: **LIVE in annotation position** (apply.py:188, 215) — NOT dead; do not delete despite zero construction sites.
- `calibration_svc.py` `HistogramGenerationStatusDict:45-51` / `ProgressDict:54-63` / `CombinedStatusDict:66-79`: **ALL LIVE** (`get_generation_combined_status:472` merges 492-493 → calibration_if.py:128 → frontend `calibration.ts getHistogramCombinedStatus`). Duplicate-vs-API claim is live on both sides.
- `recalibration_dto.ApplyCalibrationResult:22-29`: LIVE (constructed by apply_calibration_wf.py:41-217; tagging_svc/__init__.py:15 + apply.py:27 TYPE_CHECKING).
- `repo_dto` rows: **14 (not 11)**, all live, by-design.
- `generate_calibration_wf.py` `CompareCalibrationsResult:80-91` == `CalculateHeadDriftResult:94-105` — live in **DEAD code**: no `generate_calibration_workflow` entrypoint exists; only `generate_histogram_calibration_wf:309-450` is live (calibration_svc.py:267-302). Delete both + `ParseTagKeyResult:71-77` + `_compare_calibrations:230-301` + drift metric helpers; do NOT merge.

**Additional dead DTOs OMITTED from inventory** (all zero importers, allowlisted at deadcode_allowlist.py:282-334): `calibration_dto.GenerateCalibrationResult:33-42`, `CalibrationStateDict:45-62`, `HistogramCalibrationResult:65-73`; `recalibration_dto.GenerateCalibrationResult:32-47` (name-duplicate of calibration_dto's); `processing_dto.WorkerEnabledResult:93-97`, `WorkerStatusResult:100-107`; `helpers/filter_types.py` ENTIRE module (AggResult:31-35; module has zero importers repo-wide); `parse_smart_playlist_query_wf.TokenizedGroup:51`; `navidrome_types.SyncSongsResponse:258` (MEDIUM — FastAPI string response_model risk).

**Do-NOT-delete exceptions (all live, verified importers):** `tag_curation_dto` all 8 (tagging_svc/query.py:28, curation.py:11, tag_query_comp.py:9, tag_write_comp.py:13, test_tagging_svc_curation.py:10); `processing_dto.DeferredOutputStreamWrite:110-116` + `DeferredBackboneVectorWrite:119-131` (fields of DeferredFileWrites + test_process_file_wf.py:15); TrackDescriptor trio (SeedTrackDescriptor:39-50 = **Go plugin contract**); `SimilarTrackResult:29-41` (navidrome_svc.py:36,45); FileTag ×3 (API contract + frontend files.ts:7); `MetaRow:115-119`/`LockRow:122-126` (both live app_repo:60-62,75-77,155-159,218-222 + application.py + tests); `{status,message}` 5-family (all constructed: library_if.py:200,210,223,233; admin_if.py:31,53; config_if.py:40,51; calibration_if.py:53-63,108-119).

**Dynamic-reference scan:** no importlib/getattr DTO loading anywhere (migration_runner_comp loads migrations; test files import workflows). Dead claims NOT invalidated by dynamic dispatch. Tests/scripts import only live DTOs (scripts/embedding_research/config.py:282 → LibraryPath).

**Doc drift to fix on deletion:** helpers/dto/README.md:15,29-31; helpers/HELPERS.md:39,53-55; INTERFACE_STATUS.md:36 (vector_config_dto), :46 (names dead GenerateCalibrationResult), :80; docs/dev/naming.md:247; deadcode_allowlist.py:282-334 stubs (14 class stubs); scripts/human-scripts `generate_inits_config.yml` (helpers/dto __init__ regeneration list).

## DTO Duplication Audit — Verification of Inventory Claims (2026-08-19, read-only, log L114)

All inventory duplicate-family claims RE-VERIFIED against the current tree (post-commit). Every claim in the inventory is REAL; line numbers unchanged since inventory except where noted.

- **MetaRow ≡ LockRow CONFIRMED** — `repo_dto.py:115-119` / `:122-126`, both TypedDict `{key: str, value: dict}`. Consumers: `app_repo.py:77-79 _meta_row_to_dto`, `:62-64 _lock_row_to_dto`; facade `application.py:335 get_config_option`, `:346-348 list_config_options`, `:137 get_lock`, `:147 list_locks`. P2 merge is safe — both tables are generic key-value rows.
- **CompareCalibrationsResult vs CalculateHeadDriftResult — asymmetry discovered:** `generate_calibration_wf.py:80-91` (8 fields) is LIVE (constructed at `:292` inside `_compare_calibrations()` `:230`); `CalculateHeadDriftResult` `:94-105` is now DEAD — the `_calculate_head_drift()` helper it documents was DELETED; zero construction sites, only the class + its re-export in `workflows/calibration/__init__.py:15,29` remain. Deleting the class + export is a pure dead-code removal, NOT a merge.
- **{status,message} 5-class family CONFIRMED** — `calibration_types.py:17-21 BackgroundStartResponse`, `config_types.py:51-55 ConfigUpdateResponse`, `admin_if.py:23-27 RestartResponse` (inline web), `library_if.py:54-58 DeleteLibraryResponse` + `:61-65 ClearLibraryDataResponse` (inline web). Family is actually broader: status-only singles exist (`ml_if.py:83 UpdateOutputLabelResponse`, `:141 VramProbeResponse`) and 3-field variants (`library_types.py:175-183 StartScanStatusResponse {status,message,stats}`, `:180/:454`). The primary inconsistency is placement: 3 inline in web/*_if.py vs 2 in types/ package.
- **Stream family CONFIRMED with cast-bridge proof:** `ml_output_stream_store_comp.py:26-32 StreamWrite` (frozen) == `processing_dto.py:110-116 DeferredOutputStreamWrite` EXACTLY (`{output_id: str, values: list[float], output_index: int|None}`); `StreamRecord` `:35-41` differs only in required `output_index`. `OutputStreamRecord` (`output_repo_dto.py:13-26`) is the ROW shape (id/song_id/output_id/output_index/values/created_at) — NOT a dup. Proof of real duplication: `discovery_worker.py:119,129` aliases `StreamWrite as _StreamWrite` and does `cast("list[_StreamWrite]", writes.raw_output_streams)` — an explicit cast between the two identical types at a live call site.
- **Descriptor 3-way CONFIRMED:** `descriptor_match_comp.py:14-25 TrackDescriptor` (TypedDict, 9 fields) vs `navidrome_types.py:314-325 TrackDescriptorResponse` vs `navidrome_v1_if.py:39-50 SeedTrackDescriptor` — the two BaseModels are BYTE-IDENTICAL (same 9 fields, same defaults). Plus `navidrome_v1_if.py:53-56 SongDescriptor(SeedTrackDescriptor)` +`score` == `find_similar_tracks_wf.py:29-41 SimilarTrackResult` (10 fields, TypedDict twin). Bridges: `navidrome_if.py:195,270 TrackDescriptorResponse(**descriptor_map[fid])`, `navidrome_v1_if.py:228 SeedTrackDescriptor(**descriptor_map[fid])` — mechanical ** unpacking between TD and BMs.
- **Vibe 3-way CONFIRMED:** `analytics_comp.py:259-263 DominantVibeResult` (TD, live — `compute_dominant_vibes` `:266`, imported `mood_analysis_comp.py:7`) / `analytics_dto.py:256-261 DominantVibeItem` (dataclass, DEAD — zero imports) / `analytics_types.py:234-238 DominantVibeItemResponse` (BaseModel, constructed `:276` from dicts).
- **Analytics dead-12 CONFIRMED DEAD:** zero imports at all 5 sites (`helpers/dto/__init__.py:37`, `analytics_svc.py:37`, `analytics_types.py:19`, `analytics_comp.py:24`, `components/analytics/__init__.py:4`) import only the live model/distribution classes. `CollectionOverviewResult`, `MoodAnalysisResult`, `LibraryStatsResult` (:170-177), `DominantVibeItem` etc. are unreferenced. Component twins (`collection_overview_comp.py:17-22`, `mood_analysis_comp.py:19-25`) are name-only, shape-DIVERGED (component TD `stats: dict[str,Any]`, `top_pairs_by_tier` vs dataclass-typed variants) — delete both dead dataclasses, shapes are not replaceable 1:1.
- **FileTag family CONFIRMED incl. frontend drift:** `library_dto.py:107-114` (live, constructed `tagging_svc/query.py:211`, `library_svc/songs.py:88`) == `library_types.py:247-253 FileTagResponse` (constructed `:313,:394`) — frontend `frontend/src/shared/api/files.ts:7-12` uses field name `type` but the backend serializes `tag_type` → naming drift (inventory claim confirmed).
- **ApplyCalibrationResult 3-way CONFIRMED exact:** `recalibration_dto.py:22-29` dataclass (constructed `apply_calibration_wf.py:88,:212`; stored `tagging_svc/apply.py:45,68,142`) == `tagging_svc/config.py:11-17 ApplyCalibrationResultDict` == `calibration_types.py:24-30 ApplyCalibrationResultResponse` (bridge `calibration_if.py:80 ApplyCalibrationResultResponse(**apply_result)`).
- **Histogram 2-way CONFIRMED exact:** `calibration_svc.py:66-79 HistogramGenerationCombinedStatusDict` == `calibration_types.py:64-77 HistogramGenerationStatusResponse` — 11 fields, identical field ORDER, identical docstring. Bridge: `calibration_if.py:133`.
- **tag_curation CONFIRMED:** `tag_curation_dto.py` exactly 8 TypedDicts (:8,:14,:21,:26,:31,:36,:41,:46) vs `tag_curation_if.py` exactly 16 inline BaseModels (:24,:29,:34,:40,:44,:49,:54,:59,:64,:71,:76,:84,:89,:94,:98,:107) — web layer defines ALL request+response models inline instead of importing from types/ (P3 pattern violation). Inline `UpdateFileTagResponse` `:98-103` also uses `type` not `tag_type` (same drift as FileTag).
- **Type-drift correction:** `TagSongItem.file_id: int` (`tag_curation_dto.py:46-52`) — earlier L107 note said str; CURRENT tree is int (inventory's `:46` int claim correct).
- **ADR contradiction re-verified:** the persistence facade (`application.py`) returns `MetaRow`/`LockRow` storage shapes — direct violation of ADR-032 point 1 ("persistence methods accept and return only domain objects — no raw dicts") and ADR-041 (facade mediates with domain dataclasses). Zero facade methods comply; repo_dto row TypedDicts remain the live contract.
- **Baseline CHANGE (contradicts inventory §1):** the inventory's "2 dirty files" (`file_write_comp.py`, `playlist_import_types.py`) are now COMMITTED (650383d4/672179f5 repair checkpoints, 514dab9c DTO encoding fix). The nomarr codebase tree is now CLEAN — only `.opencode/commands/correct.md` (M) + `bulk_correct.md` (??) dirty (non-code). Any remediation now starts from a clean tree.

## Song-Tag Intent Facade Migration State (2026-08-30, working tree `feat/develop-branch-migration`)

First real ADR-041 compliance work landed as a PARTIAL migration of the tag sub-facade (`LibraryTagsDb`) — the tree is currently **not importable** (`import nomarr.persistence.db` → `ModuleNotFoundError`). See log L126 for the full method-by-method report.

- **Import blocker (separate concurrent folder-domain stream):** `nomarr/persistence/database/folder_repo.py:13` imports `nomarr.helpers.dataclasses.library_folder_dataclass` whose source was DELETED (only a stale 14:05 `.pyc` remains). `db.py:17` imports folder_repo at runtime. folder_repo.py body is also mid-migration (still calls removed `select_by_key`/`_row_to_dto`/`LibraryFolderRow`/`Any`; header defines unused `_row_to_domain`).
- **Migrated (domain-shaped, coherent):** `LibraryTagsDb.get_tag(TagIdentity) -> TagIdentity|None` (L49), `find_or_create_tag(TagIdentity) -> TagIdentity` (L56), `list_tags_for_song -> list[SongTagAssignment]` (L61); `search_songs_by_numeric_tag -> list[SongTagMatch]`; `search_songs_by_tag/_contains/_pattern -> list[Song]`. New domain dataclasses: `song_tag_dataclass.py` (`TagIdentity`, `SongTagAssignment` — no `.get()`), `song_dataclass.py` (`Song` with `from_row`/`to_dict`, `SongTagMatch`).
- **Broken (mypy/pyright-verified):** `library_tags.py` `TagRow` undefined at L86/122/126/135/154 (annotations only) **and L159 (RUNTIME NameError — `TagRow(...)` ctor in `list_song_tags_for_songs`)**, `replace_song_tags` L312 calls `find_or_create_tag` with 3 args (TypeError; even fixed it returns `TagIdentity` not int → repo insert breaks). `LibraryDb` forwarders broken: `get_tag(tag_id: int)` L323, `find_or_create_tag(name, value, namespace)` L326 (3-arg vs 1-arg), `list_tags_for_song -> list[TagRow]` L329.
- **Correctness bug:** new `get_tag` resolves via `tag_repo.get_tag_by_name(name, namespace)` — a `fetchone` on a NON-unique key (unique is `(name, value, namespace)`); multi-value names (e.g. `genre`) → false negatives. Needs a value-aware lookup.
- **Callers NOT migrated (latent runtime AttributeError/TypeError):** tag_query_comp (L111 get_tag int, L156/224/276/310 `.get` on domain objects), tag_write_comp (L19 3-arg find_or_create_tag), tag_stats_comp (L41/50), song_tags_comp (L28), mood_analysis_comp (L83), descriptor_match_comp (L85/96 cast-to-dict), move_detection_comp (L257 replace_song_tags dict path), library_song_query_comp `_tags_for_song` L171-176 (missed in the concurrent stream). SAFE: tag_cleanup_comp; `list_song_tags_for_songs` dict consumers (once L159 is fixed).
- **Write path needs an int resolver:** curation.py L74/146 and metadata_svc.py L179/224 call `tag_write_comp.find_or_create_tag(...)` and use the returned int. Minimal fix: `replace_song_tags` should resolve new tags via `self._tag_repo.get_or_create_tag(name, str(value), namespace)` (returns int) directly.
- **Concurrent song-domain stream is COHERENT (do not touch):** library_songs.py returns `Song` everywhere; library_regions.py (`set_pipeline_axis`/`remove_pipeline_state`, `get_pipeline_state` non-None, `pipeline_repo` param); library_song_query_comp search paths consume `Song`/`SongTagMatch` via `to_dict()`/`match.matched_tag`/`match.distance`; db.py wiring (`pipeline_repo` → LibraryRegionsDb; `library_repo` removed from AppDb); curation/apply_calibration renamed `get_song_states` → `song_state_membership`. song_state_repo.py:326 new `result.rowcount` — typing-only mypy error (runtime OK).

## Calibration Domain Dataclass Surface (2026-08-31)

Research findings for adding a `CalibrationState` domain dataclass (ADR-041). Pattern is fully established: `helpers/dataclasses/*_dataclass.py` (frozen+slots, validated) + `persistence/mappers/*_mapper.py` (row↔domain), applied at the facade boundary — `ml.py:264-267` `list_models` → `registered_model_from_record`, `ml.py:176-180` `get_model`, `ml.py:283-296` `model_output_from_record`. Adding `helpers/dataclasses/ml_calibration_dataclass.py` + `persistence/mappers/calibration_mapper.py` is consistent with existing patterns.

- **Calibration facade is SEALED (domain-valued, no raw rows):** `get_calibration_state` / `get_calibration_state_view` / `list_calibration_states` (`nomarr/persistence/api/ml.py`) return `CalibrationState` domain values; `list_calibration_states_with_models() -> list[tuple[CalibrationState, RegisteredModel]]` supersedes the removed `list_all_calibration_states_with_models`; `replace_calibration_state(state)` / `remove_calibration_state(state)` accept/return the domain value. No `CalibrationStateRecord` TypedDict leaks out of the facade.
- **Schema:** `calibration_states` = `{id int PK, model_id str FK ml_models.id, state_data JSONB, updated_at int}` (`persistence/models/calibration_state.py:10-18`); row DTO `CalibrationStateRecord` (`helpers/dto/calibration_repo_dto.py:13-19`).
- **state_data blob keys** (built persistence-internal by mapper `calibration_state_payload`, `calibration_mapper.py:76-95`): `head_name`, `label`, `calibration_def_hash`, `histogram{lo,hi,bins,bin_width}`, `histogram_bins`, `p5`, `p95`, `n` (repo key for `sample_count`), `underflow_count`, `overflow_count`. The writer is the domain-value `save_calibration_state` (`ml_calibration_state_comp.py:58-104`), which builds a `CalibrationState` and calls the sealed `db.ml.replace_calibration_state(state)`; no `head_name:label` key is computed or stripped, and `updated_at` is a column, not a blob key.
- **Flat-vs-nested state_data mismatch RESOLVED:** `get_histogram_for_head` (`calibration_svc.py:496-533`), `load_calibrations_from_db_wf` (`calibration_loader_wf.py:54-73`), `load_calibration_lookup` (`ml_calibration_state_comp.py`) now read `CalibrationState` domain attributes (`state.label`/`state.p5`/`state.p95`/`state.calibration_def_hash`/`state.histogram_bins`) via the sealed `db.ml` facade — the flat-vs-nested shape mismatch is resolved. Test `test_calibration_svc.py:328-354` is the matching 3-arg mock.
- **LIVE wire projection is FLAT:** `GET /calibration/histogram` (`calibration_if.py:142-164`) projects flat `CalibrationHistogramItem` DTOs (`nomarr/interfaces/api/types/calibration_types.py`) — `model_key`/`head_name`/`label`/`histogram_bins`/`p5`/`p95`/`n`/`histogram_spec` (+ optional `calibration_def_hash`/`underflow_count`/`overflow_count`) — matching frontend `HeadHistogramResponse` (`frontend/src/shared/api/calibration.ts`). No nested `{id, model_id, state_data, backbone_id}` envelope is exposed.
- **Recommended dataclass:** `CalibrationState(model_id, head_name, label, calibration_def_hash, p5, p95, sample_count, underflow_count, overflow_count, histogram, histogram_bins|None, updated_at|None, backbone_id|None)` — drop int PK per `ModelOutput` precedent (`ml_model_output_dataclass.py:5-7`); mapper `calibration_state_from_record` flattens `state_data`; `calibration_state_payload` rebuilds the blob (key `n` ← `sample_count`). Delete is identity-based: sealed `remove_calibration_state` (`ml.py:572-575`) delegates to `delete_state(model_id, head_name, label)`, and `delete_calibration_state` comp (`ml_calibration_state_comp.py:138-149`) is a sealed 3-arg `(db, model_id, head_name, label)` delegating to `db.ml.remove_calibration_state`.

## Mypy Fallout from ab9075af Domain-Model Migration (2026-08-31)

HEAD `ab9075af` ("repair checkpoint", 2026-08-31) landed the AppDb facade rewrite + `CalibrationState` domain dataclass (deliberately WITHOUT `backbone_id` — contrary to this skill's earlier recommendation) + `VramPromise` domain returns, but left 32 mypy errors across 13 files. 30 remained after concurrent uncommitted fixes (ml_vram_probe_comp `list_config_options(prefix=)` → `list_model_vram_limits()`/`clear_model_vram_limits()`). Clusters + root-cause pattern:

1. **AppDb interface/impl/caller tri-partite drift (ab9075af):** interface `update_health(worker_id, *, status, last_seen)` + `upsert_health` + `list_config_options()` (no prefix) are new; impl `app_repo.py:209` still `(component_id, fields: dict)` filtering to `{status, last_seen}` (149572f8f canonical field). app.py:234/411/494 still pass old dict form → mypy + SILENT runtime data loss (component_type/error/exit_code/last_heartbeat dropped). Canonical keyword callers: discovery_worker.py:292-293,568, health_monitor_svc/main.py:389, app.py:207.
2. **Calibration dict→domain drift:** `compute_global_calibration_hash` (ml_calibration_comp.py:555) STILL dict-typed (d74cf55f9 Arango era) but callers (import_wf:197/288, generate_wf:434) pass `list[CalibrationState]`; export_calibration_bundle_wf.py:90-94 uses `.get()` on domain; calibration_if.py:148 passes `list[CalibrationState]` to `GetAllCalibrationHistogramsResponse.calibrations: list[dict]` (model f3b1e3587). CalibrationState mapper (`calibration_mapper.py`) threads `backbone_id` via `**extra` that CalibrationState rejects — dead code from the skill's earlier recommended shape.
3. **VramPromise dict→domain drift:** discovery_worker.py:343-344 `.get()` on domain VramPromise (dict code c10b51ba1; `get_fleet_vram_state` returns FleetVramState TypedDict with `list[VramPromise]`).
4. **SQLAlchemy mechanical gaps:** vector_repo.py:250 `get_bind()` Engine|Connection (a1f52400); vector_repo.py:281 `Result.rowcount` missing the `# type: ignore[attr-defined]` convention used at 12+ other sites (1109e4e7); app_repo.py:578 `filters` list inferred `list[BinaryExpression[bool]]` then `.append(or_(*claim_keys))`.
5. **Value-object typing:** RelinkResult orphaned bool|int (c3b2fd41); `LibraryIdentity.root_path: str | None` (f224ec889) vs `get_library_by_natural_key(name, root_path: str)` hard WHERE clause (library_tags.py:90/106/110/113/115); `float()` on `TagRef.value: object|None` (ml_calibration_comp.py:275, ebaaa041b domain return).

Pattern: every ab9075af-era facade rewrite produces the SAME failure signature (interface+impl migrated, N callers missed, mypy exposes the drift; dict-style callers are runtime-silent). After any facade migration, run full `mypy nomarr/` AND grep for `.get(`/`[`-index access on the new domain returns. See log L137 for the full report (commit hashes/dates per site).

## Sources

- ADR-032: Domain-Model Boundary — Persistence Returns Only Domain Objects
- ADR-040: PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB
- ADR-041: Domain Dataclasses as the Persistence-Component Contract
- `nomarr/persistence/PERSISTENCE.md` — Comprehensive persistence layer documentation
- `docs/dev/architecture.md` — Intended architecture and layer design
- `tests/sabotage/test_no_arango_naming.py` — Live Arango-naming enforcement (ADR-042)
- `tests/test_architecture_qc.py` — Architecture QC tier bans + import-linter contracts
