---
name: nomarr-tags
description: 'Deep reference for the Nomarr nom: tag system. Use when creating, gating, storing, reading, curating, or calibrating tags — including any work on ML-to-tag pipelines, confidence thresholds, tier logic, opponent suppression, mood aggregation, calibration, tag writeback to audio files, or tag curation (rename/merge/split). Also covers the database tag schema and the nom: namespace convention.'
---

# Nomarr Tag System

Two-tier architecture: PostgreSQL is the source of truth (relational tables); audio files are projections written on demand. ML inference flows through ONNX head models → `HeadDecision` → `HeadOutput` objects with confidence tiers → mood aggregation with opponent suppression → `DeferredFileWrites` → async DB write.

**Load references as needed:**
- [references/architecture.md](references/architecture.md) — full schema, data flow, nom: convention, CRUD, curation, API surface
- [references/gating.md](references/gating.md) — threshold cascade, stability caps, opponent suppression, regression mood, calibration, gaps, and statistical alternatives

---

## Key Files

| Area | File |
| ------ | ------ |
| Tag DB schema (`tags` + `song_tags` join) | `nomarr/persistence/models/tag.py`, `nomarr/persistence/models/song_tag.py` |
| Tag value-object (canonical) | `nomarr/helpers/dataclasses/tags_dataclass.py` (`nomarr/helpers/dto/tags_dto.py` is a backward-compat re-export shim) |
| Tag row↔domain mapper | `nomarr/persistence/mappers/tag_mapper.py` (`tags_from_tag_rows`, `tag_rows_from_tags`) |
| ML head decision + tier | `nomarr/components/ml/inference/ml_heads_comp.py` |
| Head pipeline (pool + decide) | `nomarr/components/ml/inference/ml_head_pipeline_comp.py` |
| Known models + OPPONENT_MAP | `nomarr/components/ml/onnx/ml_known_models_comp.py` |
| Tagging aggregation (mood tiers, suppression) | `nomarr/components/tagging/tagging_aggregation_comp.py` |
| Tag DB write | `nomarr/components/tagging/tag_write_comp.py` |
| Tag DB cleanup | `nomarr/components/tagging/tag_cleanup_comp.py` |
| Tag curation (rename/merge/split) | `nomarr/components/tagging/tagging_writer_comp.py` |
| Tag removal from audio files | `nomarr/components/tagging/tagging_remove_comp.py` |
| Mood label → regression mapping | `nomarr/components/tagging/mood_labels_comp.py` |
| Tag parsing (string→typed values) | `nomarr/components/tagging/tag_parsing_comp.py` |
| Deferred write orchestration | `nomarr/services/infrastructure/workers/discovery_worker.py` (`_execute_deferred_writes`) |
| Mood file-write gate | `nomarr/workflows/processing/write_file_tags_wf.py` (`_filter_tags_for_mode`) |
| Head spec / Cascade dataclass | `nomarr/helpers/dto/ml_head_dto.py` |
| Orphan cleanup workflow | `nomarr/workflows/library/cleanup_orphaned_tags_wf.py` |
| Tag interface routes (web) | `nomarr/interfaces/api/web/tags_if.py`, `nomarr/interfaces/api/web/tag_curation_if.py`, `nomarr/interfaces/api/web/library_if.py` |

---

## Common Task Patterns

**Change a tier threshold** → `ml_heads_comp.py` `_determine_tier()` + update `Cascade` defaults in `ml_head_dto.py`. Read [references/gating.md](references/gating.md) for all three gates and the stability caps.

**Add a new model label or fix ordering** → `ml_known_models_comp.py` `KNOWN_MODELS`. Label index order follows upstream MTG Essentia metadata (`docs/upstream/modelsinfo.md`), NOT stem name order. Update guard tests in `tests/unit/components/ml/onnx/test_ml_known_models_comp.py`.

**Add/change a nom: tag key format** → `ml_head_dto.py` `HeadInfo.build_versioned_tag_key()`. Key format: `{normalize_label}_{backbone}_{model_stem}`. Stored in DB as `nom:{key}`.

**Change mood tier aggregation or suppression** → `tagging_aggregation_comp.py`. Read both references for suppression algorithm and tier set definitions.

**Work with calibration** → `SegmentScoresStats` collection + `CalibrationState`. Calibration allows mood tiers to be re-derived from stored segment stats without re-running ML. Mood tags are withheld from audio file writeback until `has_calibration=True`.

**Curate tags (rename/merge/split)** → `tagging_writer_comp.py` + `tag_write_comp.py` `relink_tag_edges()`. Curation only touches DB; affected files are set to `tags_not_written` state for deferred writeback.

**Add a new tag source (non-ML)** → Tags are plain `(name, value)` vertices — any source can write via `tag_write_comp.set_song_tags_batch()`. Apply `nom:` prefix for nomarr-generated tags. Use a different prefix for third-party sources.

---

## Critical Invariants

- `nom:` prefix is applied once in `_execute_deferred_writes` before `save_file_tags`. Do not double-prefix.
- `OPPONENT_MAP` is derived at module load from `KNOWN_MODELS`. If label strings change, the map changes automatically.
- `set_song_tags_batch` is full-replace per `(song, tag_name)` — old edges for that name are deleted first.
- `nom:mood-*` values are stored as JSON-encoded lists in the `value` field, not plain strings. Parsing is handled by `tag_parsing_comp.py`.
- Mood file writes are blocked when `has_calibration=False` regardless of mode — this is silent to the user.

---

## Tag/Tags API Duplication Migration Map (updated post-TASK-tag-boundary-A, log L109)

Two `Tag`/`Tags` dataclasses exist. Only one is live.

### LIVE (canonical): `tags_dataclass` — `nomarr/helpers/dataclasses/tags_dataclass.py`
- `Tag{name: str, values: tuple[TagValue, ...]}` frozen+slots; `Tags` canonicalizes (merges dup names, dedupes values, sorts by name), `has_name`, `get_values`. `TagValue = str|int|float|bool` declared here. Carries **no** database-row API or persistence fields (docstring: canonical `Tag`/`Tags`, per ADR-041/tag-boundary CONTRACTS.md).
- `nomarr/helpers/dto/tags_dto.py` is now a **backward-compat re-export shim** (`from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags, TagValue`) — legacy `.key`/`.value` attribute names and the `from_dict`/`from_db_rows`/`to_dict`/`to_db_rows` factories are gone.
- **Row↔domain conversion is owned by `nomarr/persistence/mappers/tag_mapper.py`**: `tags_from_tag_rows(rows) -> Tags` (groups `{name, value}` rows into canonical domain `Tags`) and `tag_rows_from_tags(tags, *, namespace)` (domain→write-payload rows `{"name", "value", "namespace"}`; `namespace` normalized blank→`default`, explicit `nom` preserved; never emits `source`).
- **Consumers**: `tag_query_comp.py` uses `tags_from_tag_rows`; tag-workflow/model comps (e.g. `tag_parsing_comp`, `tag_write_comp`, `tagging_aggregation_comp`, `tagging_reader_comp`, `tagging_writer_comp`, `process_file_wf`, `file_write_comp`, `write_file_tags_wf`, `write_calibrated_tags_wf`, `processing_dto`) and `tagging_svc/curation.py` consume `Tag`/`Tags`/`TagValue` via the shim (`.name`/.`values`, `.items`).
- The former empty `dataclasses.py` module (directly under `helpers/`) was removed; only the `dataclasses/` package remains (`nomarr/helpers/dataclasses/`).

### DEAD: the legacy `song_class` module (deleted)
- The legacy song_class module (scalar-mutable `Tag{name, value}`, `Vector`, `Song`) has been **deleted** — do not reference it. The canonical `Tag`/`Tags`/`TagValue` live in `tags_dataclass` above; the canonical song domain object is `Song` in `nomarr/helpers/dataclasses/song_dataclass.py` (see `library-files-data-flow`). No literal `TagV2`/`TagsV2` exists anywhere; "v2" in `__version__.py` = DB schema.

### Library/song tag paths (FileTag contract — not domain Tag/Tags)
- Library song-tag query paths (`song_tags_comp.py`, `library_song_query_comp.py`) and `library_svc/songs.py` pass/return the **library-owned `FileTag`** DTO (`nomarr/helpers/dto/library_dto.py`, `.key`/`.value`/`.tag_type`/`.is_nomarr`), not dict rows. Row→`FileTag` projection is centralized in `nomarr/components/library/tag_mapping_comp.py` (`file_tag_from_tag_row` / `is_numeric_tag_value`).
- The former dict-row `tag["type"]` reads in `tagging_svc/query.py` / `library_svc/songs.py` are resolved — those paths now consume the `tag_type` field on `FileTag`; no stale KeyError/conflation claims remain. Different classes with same attribute names (`analytics_comp`/`analytics_if`/`analytics_types` `TagSpec`, `filter_engine_wf` `TagCondition`) are separate concerns — do not touch when changing tag representation.
