# Phase 2 Triage Matrix — Part H Docstring Cleanup (ArangoDB → PostgreSQL terminology)

Plan: TASK-postgresql-migration-second-pass-H-docstring-cleanup
Phase: P2 (Triage — classification only, ZERO edits)
Scoped dirs: components/library/, components/ml/, components/matching/ (=components/navidrome/ descriptor_match), components/tags/ (=components/tagging/), components/navidrome/, workflows/, services/, helpers/
Excluded: nomarr/persistence/**, tests/**, interfaces/** (out of assigned groups)
Triage date: 2026-08-14

## Classification key
- LITERAL_ARANGO → UPDATE: literal `_id`/`_key`/`_rev` field refs, or ArangoDB slash ID formats (`song/12345`, `song/_id`, `libraries/{key}`).
- TERMINOLOGY → UPDATE: "collection" describing a DB table, "document"/"vertex"/"edge" describing DB records/junctions in a storage/data-model sense.
- FALSE_POSITIVE → SKIP: compound domain names, pgvector HNSW collections, loose "document"/"edge"/"vertex" prose, out-of-scope code.
- out-of-scope-code: CODE (not docstring/comment) — classified FALSE_POSITIVE here, listed in observations.

## UPDATE list (file:line | classification | current text | suggested replacement)

### LITERAL_ARANGO

| file:line | current text | suggested replacement |
|---|---|---|
| nomarr/helpers/dto/navidrome_dto.py:222 | `unresolved_file_ids: Nomarr file ``_id`` values with no ND mapping.` | `Nomarr file ``id`` values with no ND mapping.` |
| nomarr/workflows/vectors/get_track_vector_wf.py:32 | `file_id: Song document ``_id`` (e.g. ``"song/12345"``).` | `Song document ``id`` (e.g. ``"12345"``).` |
| nomarr/workflows/navidrome/generate_playlists_wf.py:82 | `List of generated playlists with ``song/_id`` track lists.` | `List of generated playlists with ``song_id`` track lists.` |
| nomarr/workflows/library/scan_library_full_wf.py:76 | `library_id: Library document ``_id``` | `library_id: Library document ``id`` (or Library record ``id``)` |
| nomarr/workflows/library/scan_library_quick_wf.py:72 | `library_id: Library document ``_id``` | `library_id: Library document ``id`` (or Library record ``id``)` |
| nomarr/workflows/library/scan_setup_wf.py:43 | `library_id: Library document ``_id``.` | `library_id: Library document ``id``.` |
| nomarr/workflows/library/reconcile_paths_wf.py:31 | `library_id: Library document _id to scope reconciliation to` | `library_id: Library document id (Library record id) to scope reconciliation to` |
| nomarr/workflows/processing/process_file_wf.py:60 | `file_id: song document _id. Avoids path-based lookup when provided.` | `file_id: song document id (song record id). Avoids path-based lookup when provided.` |
| nomarr/workflows/processing/write_file_tags_wf.py:48 | `file_key: str  # Document _key of the file` | `file_key: str  # Document id (file id) of the file` |
| nomarr/workflows/processing/write_file_tags_wf.py:121 | `file_key: Document _key of the file to write` | `file_key: Document id (file id) of the file to write` |
| nomarr/components/library/tag_hydration_comp.py:87 | `Songs without a string _id are returned as shallow copies.` | `Songs without a string id are returned as shallow copies.` |
| nomarr/components/library/tag_hydration_comp.py:136 | `If the song has no string _id, returns a shallow copy unchanged.` | `If the song has no string id, returns a shallow copy unchanged.` |
| nomarr/components/library/move_detection_comp.py:31 | `file_id: int  # DB _id of the moved file` | `file_id: int  # DB id of the moved file` |
| nomarr/components/library/reconcile_paths_comp.py:38 | `library_id: Library document _id to scope reconciliation to` | `library_id: Library document id (Library record id) to scope reconciliation to` |
| nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:29 | `song_id: Library song document ``_id``.` | `song_id: Library song document ``id``.` |
| nomarr/components/navidrome/playlist_builder_comp.py:4 | `Builders return ``songs/id`` values;` | `Builders return ``song_id`` (song id) values;` |
| nomarr/services/domain/library_svc/songs.py:116 | `library_id: Library document _id to scope reconciliation to` | `library_id: Library document id (Library record id) to scope reconciliation to` |
| nomarr/services/domain/playlist_import_svc.py:59 | `library_id: Optional library _id to restrict matching scope` | `library_id: Optional library id to restrict matching scope` |
| nomarr/services/domain/analytics_svc.py:201 | `library_id: Optional library ``_id`` to filter by.` | `library_id: Optional library ``id`` to filter by.` |
| nomarr/services/domain/tagging_svc/query.py:96 | `tag_id: Tag _id` | `tag_id: Tag id` |
| nomarr/services/domain/tagging_svc/query.py:133 | `library_id: Optional library _id to scope.` | `library_id: Optional library id to scope.` |

### TERMINOLOGY (collection → table)

| file:line | current text | suggested replacement |
|---|---|---|
| nomarr/components/library/reconcile_paths_comp.py:32 | `This component scans the songs collection and re-validates each path` | `This component scans the songs table and re-validates each path` |
| nomarr/workflows/library/reconcile_paths_wf.py:25 | `This checks all files in the songs collection to detect paths` | `This checks all files in the songs table to detect paths` |
| nomarr/services/domain/library_svc/songs.py:111 | `This checks all files in the songs collection to detect paths` | `This checks all files in the songs table to detect paths` |
| nomarr/workflows/calibration/calibration_loader_wf.py:30 | `Load all calibrations from calibration_state collection.` | `Load all calibrations from the calibration_state table.` |
| nomarr/workflows/calibration/calibration_loader_wf.py:88 | `Checks calibration_version in meta collection.` | `Checks calibration_version in the meta table.` |
| nomarr/workflows/metadata/cleanup_orphaned_entities_wf.py:17 | `Clean up orphaned tags from the tags collection.` | `Clean up orphaned tags from the tags table.` |
| nomarr/workflows/navidrome/generate_navidrome_config_wf.py:28 | `Queries the tags collection to discover all nomarr tags` | `Queries the tags table to discover all nomarr tags` |
| nomarr/components/ml/resources/ml_vram_probe_comp.py:4 | `results in the ``meta`` collection as:` | `results in the ``meta`` table as:` |

## Observations

### (a) Out-of-scope CODE hits (functional code, NOT docstrings — must NOT be "fixed" by this docstring plan)
- `nomarr/components/ml/calibration/ml_calibration_state_comp.py:94-96,111,227` — `_key = _make_calibration_state_key(head_name, label)` then `doc = {"key": _key, ...}`. This is a CODE-level local variable building a calibration-state dict. Real `_key` reference but functional code. **OUT OF SCOPE** for this docstring-only plan → classified FALSE_POSITIVE. This is exactly the CRITICAL BOUNDARY case the plan flags. Flag to manager: real `_key` handling exists in functional code and may need a separate functional-change plan.

### (b) Real LITERAL_ARANGO hits OUTSIDE my assigned directory groups (manager should route)
These are genuine docstring `_id`/`_key`/slash hits but fall outside the P2-S1..S5 directory scope (components/library, ml, matching, tags, navidrome, workflows, services, helpers). Flagged for the manager to decide whether a follow-up pass covers them.
- `nomarr/components/workers/worker_tag_comp.py:33` — `File ``_id`` string if a file was claimed, ``None`` if no work available`. components/workers/ NOT in any P2 group.
- `nomarr/interfaces/api/types/info_types.py:176,195` — `library_id: int = Field(..., description="Library document _id")`. interfaces/ NOT in P2 scope.
- `nomarr/interfaces/api/types/playlist_import_types.py:44` — `description="Optional library _id to restrict matching scope"`. interfaces/ NOT in P2 scope.

### (c) Hits requiring a FUNCTIONAL change (recorded only — must NOT be "fixed" as docstring)
- `nomarr/components/library/library_id_comp.py:4,12,19` — docstrings say "libraries/{key} document ids" but the CODE genuinely uses a `libraries/` string prefix functionally (`normalize_library_id` does `startswith("libraries/")` / `f"libraries/{library_id}"`). Changing the docstring without changing the code would make it inaccurate. This is functional slash-format behavior, not stale Arango docstring prose → **functional change required**, recorded only. Flag to manager.

### (d) Hits deliberately left FALSE_POSITIVE that a reviewer should double-check
- `nomarr/workflows/navidrome/generate_playlists_wf.py:64` — `Vector collections are per-backbone (no library_key needed).` "Vector collections" = pgvector HNSW collection (benign); `library_key` = compound domain key (benign). FALSE_POSITIVE.
- `nomarr/workflows/navidrome/find_similar_tracks_wf.py:54-97`, `nomarr/components/ml/vectors/ml_vector_retrieve_comp.py:19-72`, `ml_vector_persist_comp.py:59,107,111`, `nomarr/helpers/vector_params_helper.py:25,30` — "cold/hot collection", "vector collection", "doc_count", "docs" = pgvector HNSW + vector record terminology (benign per plan). FALSE_POSITIVE.
- `nomarr/helpers/constants/file_states.py:1` — "Canonical song-state axis-pair vertex identifiers" — "vertex" = pipeline-state axis identifier (benign per plan). FALSE_POSITIVE.
- `nomarr/components/tagging/tag_write_comp.py:18,104` — "tag vertex" / "song tag references" — vertex = tag DB record in current junction model (loose but reflects current song-tag junction table naming). Lower-confidence; reviewer may reconsider. FALSE_POSITIVE.
- `nomarr/components/tagging/tag_query_comp.py:111`, `tag_stats_comp.py:19,33` — "tag document by ``id``" / "library song documents" — "document" used as loose prose for a persisted record; these use PG `id` correctly. FALSE_POSITIVE.
- `nomarr/components/workers/worker_discovery_comp.py:55-111` — "File document id (e.g., ``12345``)" — uses PG-style `id` and `12345` example, correct current vocabulary. FALSE_POSITIVE.
- `nomarr/helpers/exceptions.py:17`, `exceptions_helper.py:15` — "when a library document cannot be found by its ID." — "document" as loose prose for a record. FALSE_POSITIVE (conservative).
- `nomarr/helpers/config_schema.py:11`, `helpers/dataclasses/tags_dataclass.py:55,61`, `helpers/filter_types.py:4` — "collection"/"document"/"sub-schema" used generically, not DB-storage. FALSE_POSITIVE.
- `nomarr/services/domain/metadata_svc.py:3` + "tag collections"/"Route collection values"/"entity collection names"/`COLLECTION_REL_MAP` — "collection" = a named grouping of tag entities (artist/album/genre name grouping), NOT a DB table. `COLLECTION_REL_MAP` is a code identifier. FALSE_POSITIVE.
- `nomarr/components/ml/onnx/ml_model_registry_comp.py:21,26,31,62,144,180` — "model document"/"output vertex"/"model vertex" — vertex = ML output-graph node concept, not DB record. FALSE_POSITIVE.
- `nomarr/workflows/platform/prune_orphaned_files_wf.py:3-32`, `prepare_database_wf.py:77`, `workflows/library/scan_library_full_wf.py:71`, `scan_setup_wf.py:47`, `validate_library_tags_wf.py:28`, `library_song_state_comp.py` — "edge"/"ownership edge"/"written edge"/"from_vertex"/"to_vertex" describing relationship/junction concepts in the current relational model. These describe current song-tag/state junction relationships (list_song_tag_edges etc.), reflecting current schema naming. Lower-confidence; reviewer may reconsider a broader "edge→relationship" sweep. FALSE_POSITIVE.
- `nomarr/workflows/library/validate_library_tags_wf.py`, `file_batch_scanner_comp.py`, `library_records_comp.py`, `library_scan_*_comp.py`, `scan_lifecycle_comp.py`, `library_song_mutation/query/state_comp.py`, `work_status_comp.py` — pervasive "library document"/"song document"/"scan document"/"file document" describing a persisted record. Left FALSE_POSITIVE (conservative) — "document" as loose prose; the unambiguous Arango signal is the `_id`/`_key`/slash refs, already captured above.
- `nomarr/workflows/vectors/get_track_vector_wf.py:3,36` — "per-backbone cold collection"/"Vector document dict" — pgvector HNSW collection (benign). The line-32 `_id` is the real hit (already captured). FALSE_POSITIVE for the collection/doc uses.

## Triage counts (in-scope dirs only)
- LITERAL_ARANGO (UPDATE): 21
- TERMINOLOGY (UPDATE): 8
- FALSE_POSITIVE (SKIP): all other terminology/document/collection/vertex/edge hits in scope (see observations d)
- STORAGE_CONTEXT: 0 (persistence glob excluded)
- out-of-scope-code: 1 (ml_calibration_state_comp `_key`)
- Total UPDATE docstrings: 29 across ~19 files

## Methodology
Derived from `.opencode/scratch/h-docstring-triage.md` (Phase 1 output). Each UPDATE-classified hit was verified by reading the exact docstring region (not whole files). ZERO files were modified. Only this matrix file was created.
