---
name: ml-output-identity
description: Stable output identity for the Nomarr ML registry — ml_model_outputs.output_id (sha256 _output_key of model_id:output_index), the ml_output_streams.output_id cross-table contract, and the in-flight fix on feat/develop-branch-migration. Use when working on output registry (ensure_model_outputs, update_model_output_label, build_model_output_index_map, replace_model_output, get_model_output), ml_output_streams write/read resolution, register_ml_models_wf, ml_if/ml_types, or the id_codec int-only boundary for ML ids.
---

# ML Output Identity (ml_model_outputs ↔ ml_output_streams)

## Mental Model

Two tables share one identity: the canonical output identifier `output_id` = `sha256(f"{model_id}:{output_index}")` hexdigest truncated to 16 chars (`_output_key` in `ml_model_registry_comp.py`). `ml_output_streams` and `ml_model_outputs` both store it in the current baseline (`alembic/versions/001_current_schema_baseline.py`, NOT NULL String(255)). `ml_model_outputs` is the metadata registry (head/label/fully_labeled per output vertex). The read/write chain: `build_model_output_index_map` (registry) → `process_file_wf:204-229` resolves raw streams to `output_id` → `replace_song_inference_results` persists to `ml_output_streams` → `load_output_streams_for_song`/`build_output_stream_lookup` re-match by `output_id`. If the map is empty, streams are skipped, songs flip to `not_processed`, and re-inference loops forever.

## Coverage

**Documented:** Two-table identity contract; full registry identity chain with locations; in-flight migration state (what's done vs. remaining gaps) as of 2026-08-29; int-only id_codec trap for hex ids; label-alignment hazards.
**Not yet documented:** Final merged state after the branch completes; frontend useMLModels.ts label-edit flow details beyond the o.id→o.output_id change.
**Last extended:** 2026-08-29

## Key Findings

### Finding 1: Streams table already canonical, registry missing it (pre-fix root cause)
- `alembic/versions/001_current_schema_baseline.py` — `ml_output_streams` has `output_id` String(255) NOT NULL, `output_index`, `values` JSONB; it has no model_id/status.
- `nomarr/persistence/models/ml_model_output.py` — NO output_id column pre-fix; int autoincrement PK, `model_id` FK to `ml_models.id` (str), `output_index`, `label`, `fully_labeled`.
- `ml_model_registry_comp.build_model_output_index_map` read `output_doc.get("id")` (int PK) with `isinstance(output_id_key, str)` guard → ALWAYS {} → `process_file_wf:206-213` skipped every canonical stream ("Missing output registry") → `ml_output_streams` never populated in live path → `ml_output_stream_store_comp.load_output_streams_for_song:154-209` transitions `processed→not_processed` → re-inference loop.

### Finding 2: Registry lookups used the wrong key
- `ensure_model_outputs` did `get_model_output(output_index)` (PK lookup with index) → always miss → label preservation dead, duplicate rows per startup.
- `update_model_output_label` passed `output_id` (str) into int PK lookup (`# type: ignore[arg-type]`) → miss → UI label updates silently no-op (web sends encoded int PK; `ml_svc.update_output_label` str()s it).
- `replace_model_output` (facade) accepted `_output_key` but IGNORED it — plain INSERT with auto PK → the sha256 identity was dropped at the persistence boundary.

### Finding 3: Consolidated baseline state (2026-08-30)
The consolidated baseline creates `ml_model_outputs.output_id` as NOT NULL and unique. Existing pre-baseline databases are unsupported and must be recreated; no data backfill is performed.

### Finding 4: REMAINING GAPS (must fix to complete)
1. `_row_to_output_record` (output_repo.py:32-45) does NOT map `output_id` AND `ModelOutputRecord` DTO (output_repo_dto.py:29-40) lacks the field → index map still {} even after everything else.
2. Signature mismatch: updated tests call `store_model_output(song_id, model_id, output_id, output_data, ...)` (output_id 3rd positional); repo currently has `(song_id, model_id, output_data, output_id=None)`.
3. `song_id=0` hardcoded at register_ml_models_wf.py:95,103 + ml_svc.py:148 → FK violation (no songs.id=0) → prepare_database_wf.py:89 startup abort. The baseline currently keeps the model-output table independent of songs; callers and ORM nullability still need to agree on the intended registry contract.
4. register_ml_models_wf.py:107 `output_doc["id"]` → must be `output_doc["output_id"]`.
5. register_ml_models_wf.py:144 `prune_result["tag_model_output_edges_deleted"]` → KeyError; prune_registered_model returns only `{"output_ids": ...}`.
6. `id_codec` is INT-ONLY: `encode_id` raises InvalidIdFormatError on hex, `decode_path_id` HTTP 400s. `MlModelResponse.id`/`MlModelOutputResponse.id` = `encode_id(hex _model_key / int PK)` — model listing crashes with hex ids; PATCH /model/{id}/output/{output_id} must NOT decode_path_id sha256 ids. Response needs `output_id: str` field; frontend ml.ts MlModelOutput + useMLModels.ts:130 `o.id===outputId` → `o.output_id`.
7. `list_model_outputs` (output_repo.py:125-130) no ORDER BY output_index → `outputs[output_index]` in wf and `ml_discovery_comp.py:213-216` label alignment broken (comprehension drops unlabeled indices → labels shift → wrong label mapping / IndexError).
8. `output_repo_dto.OutputStreamRecord.output_id` accidentally made NotRequired — revert to required `str` (the change belongs on ModelOutputRecord).
9. `delete_model_outputs_for_model` returns [] always (component checks isinstance list, facade returns int count) → prune output_ids always empty.
10. Pre-baseline databases are unsupported after consolidation; no legacy output-id backfill is performed by the current baseline.

## Critical Invariants
- `output_id` = sha256(f"{model_id}:{output_index}")[:16] — deterministic, computed by `_output_key`; stream rows and registry rows must use the SAME value.
- `ml_output_streams.output_id` is NOT NULL — never make it optional.
- `ml_models.id` is the 16-hex `_model_key(path)` string (str PK) — int codecs must never touch it or `ml_model_outputs.output_id`.
- Stream write path is `db.ml.replace_song_inference_results(song_id, backbone, vectors, output_streams)` — atomic, one tx per backbone (AR-SDR-4, MlInferenceRepo).

## Sources
- Log L123 (support-researcher, 2026-08-29) — full gap list with locations
- alembic/versions/001_current_schema_baseline.py
- nomarr/persistence/database/output_repo.py, persistence/api/ml.py, persistence/models/ml_model_output.py, helpers/dto/output_repo_dto.py
- nomarr/components/ml/onnx/ml_model_registry_comp.py, workflows/platform/register_ml_models_wf.py, workflows/processing/process_file_wf.py
- nomarr/components/ml/inference/ml_output_stream_store_comp.py
- nomarr/interfaces/api/id_codec.py, interfaces/api/web/ml_if.py, interfaces/api/types/ml_types.py
- tests/unit/persistence/api/test_ml_db.py, tests/unit/persistence/database/test_output_repo.py, tests/unit/components/ml/onnx/test_ml_model_registry_comp.py
