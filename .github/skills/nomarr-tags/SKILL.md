---
name: nomarr-tags
description: Deep reference for the Nomarr nom: tag system. Use when creating, gating, storing, reading, curating, or calibrating tags — including any work on ML-to-tag pipelines, confidence thresholds, tier logic, opponent suppression, mood aggregation, calibration, tag writeback to audio files, or tag curation (rename/merge/split). Also covers the ArangoDB tag schema and the nom: namespace convention.
---

# Nomarr Tag System

Two-tier architecture: ArangoDB is the source of truth (vertex+edge graph); audio files are projections written on demand. ML inference flows through ONNX head models → `HeadDecision` → `HeadOutput` objects with confidence tiers → mood aggregation with opponent suppression → `DeferredFileWrites` → async DB write.

**Load references as needed:**
- [references/architecture.md](references/architecture.md) — full schema, data flow, nom: convention, CRUD, curation, API surface
- [references/gating.md](references/gating.md) — threshold cascade, stability caps, opponent suppression, regression mood, calibration, gaps, and statistical alternatives

---

## Key Files

| Area | File |
| ------ | ------ |
| Tag DB schema | `nomarr/persistence/collections.py`, `nomarr/persistence/models/tag.py` |
| Tag DTO | `nomarr/helpers/dto/tags_dto.py` |
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
| Tag interface routes | `nomarr/interfaces/routes/tag_route.py`, `nomarr/interfaces/routes/tag_curation_route.py`, `nomarr/interfaces/routes/library_route.py` |

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
