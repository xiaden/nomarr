# Task: ML Inference Configuration UI

## Problem Statement

The ML inference pipeline uses `fully_configured` on each `ml_models` vertex to decide whether a model participates in inference. Unknown (third-party) models are registered at startup with `fully_configured=False` and stay that way forever — there is no UI or API to label their outputs or mark them ready.

The fix is a third accordion in `ConfigPage` called "ML Inference" that:

1. Lists all registered models with their configuration status.
2. Shows each model's output activations and lets the user assign a label.
3. Provides a "Mark as Configured" button once all outputs are labeled.
4. Moves the VRAM Probe button from the Admin accordion into this new accordion (it belongs with ML config, not general admin controls).

Existing backend infrastructure is in place:

- `MLModelsOperations` (`ml_models_aql.py`) — `list_models`, `set_fully_configured`
- `MLModelOutputsOperations` (`ml_model_outputs_aql.py`) — `get_outputs_for_model`, `update_label`
- `MLService` (`ml_svc.py`) — owns `db` and `cfg`, currently only has `list_backbones`, `discover_heads`, `clear_vram_measurements`
- `encode_id` / `decode_path_id` in `id_codec.py` — URL-safe ArangoDB ID encoding (`ml_models/abc` → `ml_models:abc`)

## Phases

### Phase 1: Add model management methods to MLService

- [x] Add `list_all_models(self) -> list[dict[str, Any]]` to `MLService` — delegates to `db.ml_models.list_models()`
    **Notes:** Added `list_all_models` to `ml_svc.py`. Delegates to `db.ml_models.list_models()`. lint_project_backend nomarr/services — 0 errors.
- [x] Add `get_model_outputs(self, model_id: str) -> list[dict[str, Any]]` — delegates to `db.ml_model_outputs.get_outputs_for_model(model_id)`
    **Notes:** Added `get_model_outputs` to `ml_svc.py`.
- [x] Add `update_output_label(self, output_id: str, label: str) -> None` — delegates to `db.ml_model_outputs.update_label(...)`
    **Notes:** Added `update_output_label(output_id, label)` to `ml_svc.py`. Delegates to `db.ml_model_outputs.update_label`. Label-only signature matches the cleaned-up persistence method.
- [x] Add `mark_model_configured(self, model_id: str, value: bool) -> None` — delegates to `db.ml_models.set_fully_configured(model_id, value)`
    **Notes:** Added `mark_model_configured(model_id, value)` to `ml_svc.py`. Delegates to `db.ml_models.set_fully_configured`.
- [x] Verify `db.ml_models` and `db.ml_model_outputs` are accessible on `MLService.db` (read `ml_svc.py` and `db.py` to confirm attribute names)
    **Notes:** Verified at phase start. `db.py` shows `self.ml_models = MLModelsOperations(self.db)` at line 127 and `self.ml_model_outputs = MLModelOutputsOperations(self.db)` at line 128. Both accessible as `self.db.ml_models` and `self.db.ml_model_outputs` from `MLService`.

### Phase 2: Add Pydantic types and new API routes

- [x] Create `nomarr/interfaces/api/types/ml_types.py` — define `MlModelResponse`, `MlModelOutputResponse`, `UpdateOutputLabelRequest` (field: `label: str`), `MarkConfiguredRequest` Pydantic models
- [x] Add `GET /api/web/ml/models` to `ml_if.py` — returns `list[MlModelResponse]` via `ml_service.list_all_models()`; encode IDs using `encode_ids`
- [x] Add `GET /api/web/ml/models/{model_id}/outputs` to `ml_if.py` — decode path `model_id` with `decode_path_id`, return `list[MlModelOutputResponse]`
- [x] Add `PATCH /api/web/ml/models/{model_id}/outputs/{output_id}` to `ml_if.py` — decode both path IDs, call `update_output_label`
- [x] Add `POST /api/web/ml/models/{model_id}/mark-configured` to `ml_if.py` — decode path `model_id`, call `mark_model_configured`
    **Notes:** All 4 routes added to ml_if.py in one edit. Imports extended with decode_path_id and all 4 ml_types. lint_project_backend nomarr/interfaces and nomarr/services — 0 errors each.
- [x] Run `lint_project_backend` on `nomarr/interfaces` and `nomarr/services` — fix all errors

### Phase 3: Frontend API layer

- [x] Extend `frontend/src/shared/api/ml.ts` — add TypeScript interfaces (`MlModel`, `MlModelOutput`, `UpdateLabelPayload`) and API functions (`listModels`, `getModelOutputs`, `updateOutputLabel`, `markModelConfigured`)
    **Notes:** Extended ml.ts with MlModel, MlModelOutput, UpdateLabelPayload, MarkConfiguredPayload interfaces and listModels, getModelOutputs, updateOutputLabel, markModelConfigured functions. Imports get, patch, post from client.

### Phase 4: Frontend components and hooks

- [x] Create `frontend/src/features/config/hooks/useMLModels.ts` — fetches model list, tracks expanded model, handles label edits and save/configure actions with loading/error state
- [x] Create `frontend/src/features/config/components/MLInference.tsx` — renders VRAM probe `ActionCard`, model list via MUI `Table` (backbone, head, outputs labeled / total, configured badge), expandable per-model output label editor (label text field, save-row button), and per-model "Mark as Configured" button, using `Panel` / `SectionHeader` / `ActionCard` shared components

### Phase 5: Wire accordion into ConfigPage

- [x] Add "ML Inference" `Accordion` (third, after Admin) to `frontend/src/features/config/ConfigPage.tsx` — render `<MLInference>` inside it, passing `onVramProbe` and `actionLoading` from `useAdminActions`
- [x] Remove `<MLControls>` from the Admin accordion in `ConfigPage.tsx` (VRAM probe now lives in ML Inference)
- [x] Delete `frontend/src/features/admin/components/MLControls.tsx` (component fully replaced)

## Completion Criteria

- `GET /api/web/ml/models` returns registered models with encoded IDs
- `PATCH /api/web/ml/models/{id}/outputs/{id}` persists label changes to DB
- `POST /api/web/ml/models/{id}/mark-configured` flips `fully_configured` in DB
- Config page shows three accordions: Settings, Admin, ML Inference
- ML Inference accordion lists models, shows output label editor for unconfigured models, and contains the VRAM probe button
- VRAM probe button no longer appears in the Admin accordion
- `lint_project_backend` passes with zero errors

## References

- Prior work: Plans F and G (model graph schema, discovery contract)
- `nomarr/persistence/database/ml_models_aql.py` — DB operations
- `nomarr/persistence/database/ml_model_outputs_aql.py` — DB operations
- `nomarr/services/infrastructure/ml_svc.py` — service to extend
- `nomarr/interfaces/api/web/ml_if.py` — router to extend
- `nomarr/interfaces/api/id_codec.py` — encode_id / decode_path_id
- `frontend/src/features/config/ConfigPage.tsx` — page to modify
- `frontend/src/features/admin/components/MLControls.tsx` — to delete
