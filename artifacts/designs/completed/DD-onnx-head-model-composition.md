# ONNXHeadModel Composition Refactor — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-20  

**Related Documents:**

- [Compose complex types from simpler types instead of redeclaring their fields]() —
- [Top-level imports by default]() —
- [New ML backends must plug into stable contract]() —

---

## Scope

nomarr/components/ml/onnx/ml_head.py, nomarr/components/ml/onnx/ml_discovery_comp.py, nomarr/components/ml/onnx/ml_cache.py, nomarr/components/ml/inference/ml_head_pipeline_comp.py, nomarr/components/ml/inference/ml_heads_comp.py, nomarr/helpers/dto/ml_dto.py, nomarr/workflows/processing/process_file_wf.py, nomarr/workflows/platform/register_ml_models_wf.py

---

## Problem Statement

`ONNXHeadModel` redeclares fields from `HeadInfo` instead of composing it:

- `backbone_name`, `head_type`, `model_name`, `labels`, `is_regression` — all duplicated with inconsistent names (`is_regression` vs `is_regression_head`, `model_name` vs `name`/`model_stem`, `_path` vs `model_path`)
- `build_versioned_tag_key()` — method duplicated

`HeadOutput.head` is typed `HeadInfo` but receives `ONNXHeadModel` at runtime from `to_head_outputs()` in `ml_head_pipeline_comp.py`. This causes mypy errors and would cause `AttributeError` if the two code paths mixed.

`discover_head_models()` builds `HeadInfo` objects, extracts only `labels`, passes them into `ONNXHeadModel`, and discards the `HeadInfo`. This violates ADR-028's rule: "Factory functions that build both types pass the simpler type into the complex one instead of extracting fields and discarding it."

---

## Architecture

## Composition Model

`ONNXHeadModel` gains a `meta: HeadInfo` attribute. All metadata fields and `build_versioned_tag_key()` are removed from `ONNXHeadModel`. Callers access metadata through `model.meta.*`.

### Layer Mapping

| Component | Layer | Responsibility |
|-----------|-------|----------------|
| `HeadInfo` | components/ml/onnx | Metadata container: labels, backbone, head_type, model_path, build_versioned_tag_key() |
| `ONNXHeadModel` | components/ml/onnx | ONNX runtime wrapper: session lifecycle, inference, tensor metadata |
| `HeadOutput` | helpers/dto | Cross-layer DTO: carries `HeadInfo` reference + inference result |
| `ml_head_pipeline_comp` | components/ml/inference | Orchestrates head inference, builds HeadOutput from `model.meta` |
| `ml_cache.py` | components/ml/onnx | Groups discovered models by backbone; accesses `head.backbone_name` for keying |
| `register_ml_models_wf` | workflows/platform | Registers ONNX models at startup; calls `head_parts_from_path()` to parse path metadata |
| `process_file_wf` | workflows/processing | Consumes HeadOutput, accesses `ho.head.model_path` |

### Changes Per File

#### 1. `nomarr/components/ml/onnx/ml_head.py` — ONNXHeadModel

**Remove:**

- Fields: `backbone_name`, `head_type`, `model_name`, `labels`, `is_regression`
- Method: `build_versioned_tag_key()`
- Property: `name` (derived from `model_name`)

**Add:**

- `meta: HeadInfo | None` attribute (None before discovery injects it)

**Modify constructor:**

```python
def __init__(
    self,
    path: str,
    *,
    meta: HeadInfo | None = None,
) -> None:
    super().__init__(path)
    self.meta: HeadInfo | None = meta
    self.input_node = None
    self.output_node = None
    self.input_dim = None
    self.num_classes = None
```

**Keep:** `_run()`, `load()`, `unload()`, `input_node`, `output_node`, `input_dim`, `num_classes` — these are ONNX runtime concerns, not metadata.

**No delegation properties.** All callers are updated to use `model.meta.*` directly. No shims, no legacy API.

**All caller sites that need updating:**

| Old Access | New Access | File | Usage |
|-----------|-----------|------|-------|
| `head.backbone_name` | `head.meta.backbone` | `ml_cache.py` | Dict keying in `ONNXModelCache.__init__` |
| `m.backbone_name` | `m.meta.backbone` | `ml_discovery_comp.py` | Sort key in both discover functions |
| `m.head_type` | `m.meta.head_type` | `ml_discovery_comp.py` | Sort key in both discover functions |
| `m.model_name` | `m.meta.model_stem` | `ml_discovery_comp.py` | Sort key in both discover functions |
| `head_model.name` | `head_model.meta.name` | `ml_head_pipeline_comp.py` | `HeadSpec(name=...)` |
| `head_model.head_type` | `head_model.meta.head_type` | `ml_head_pipeline_comp.py` | `HeadSpec(kind=...)` and logging |
| `head_model.labels` | `head_model.meta.labels` | `ml_head_pipeline_comp.py` | `HeadSpec(labels=...)` |

**Keep `head_parts_from_path()` function** — still called by `register_ml_models_wf.py` (line 72) which does not construct `ONNXHeadModel` and needs path parsing independently. The function is no longer called from `ONNXHeadModel.__init__`, but it remains a valid utility for path-based metadata extraction outside the inference pipeline.

#### 2. `nomarr/components/ml/onnx/ml_discovery_comp.py` — discover_head_models()

**Modify `discover_head_models()`** — pass `HeadInfo` into `ONNXHeadModel` instead of extracting labels:

```python
for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx"))):
    stem = Path(onnx_path).stem
    info = head_info_map.get(stem)
    model = ONNXHeadModel(onnx_path, meta=info)
    models.append(model)
```

**Modify `discover_head_models_no_db()`** — synthesize minimal `HeadInfo` from path metadata:

```python
for onnx_path in sorted(glob.glob(os.path.join(head_type_dir, "*.onnx"))):
    model_stem = os.path.splitext(os.path.basename(onnx_path))[0]
    # Synthesize HeadInfo from filesystem structure
    meta = HeadInfo(
        name=model_stem,
        labels=[],
        backbone=backbone,
        head_type=head_type,
        model_stem=model_stem,
        model_path=onnx_path,
        embedding_graph=embedding_graph or "",
        is_regression_head=model_stem in _REGRESSION_HEADS,
    )
    models.append(ONNXHeadModel(onnx_path, meta=meta))
```

This approach ensures `model.meta` is always non-None after construction — both DB-backed and no-DB paths produce a `HeadInfo`. The no-DB path has empty labels (matching current behavior) but valid structural metadata.

**Sort keys (lines 472, 532):** Both `discover_head_models()` and `discover_head_models_no_db()` sort with `models.sort(key=lambda m: (m.backbone_name, m.head_type, m.model_name))`. Update to `models.sort(key=lambda m: (m.meta.backbone, m.meta.head_type, m.meta.model_stem))`.

#### 3. `nomarr/components/ml/inference/ml_head_pipeline_comp.py` — run_single_head / _build_tag_key

**Modify `_build_tag_key()`:**

```python
def _build_tag_key(label: str, *, head_model: ONNXHeadModel) -> str:
    model_key, _ = head_model.meta.build_versioned_tag_key(
        normalize_tag_label(label),
        calib_method="none",
        calib_version=0,
    )
    return model_key
```

**Modify `run_single_head()` — HeadOutput construction:**

Change `to_head_outputs(head_info=head_model, ...)` to `to_head_outputs(head_info=head_model.meta, ...)`:

```python
head_outputs = decision.to_head_outputs(
    head_info=head_model.meta,
    key_builder=key_builder,
)
```

**Modify HeadSpec construction in `run_single_head()`:**

```python
spec = HeadSpec(
    name=head_model.meta.name,
    kind=head_model.meta.head_type,
    labels=list(head_model.meta.labels),
)
```

**Modify logging line:**

```python
logger.debug(f"[processor] Head {head_name} ({head_model.meta.head_type}) produced {len(head_tags)} tags")
```

#### 4. `nomarr/helpers/dto/ml_dto.py` — HeadOutput

**No changes needed.** `HeadOutput.head` is already typed `HeadInfo`. After this refactor, it will actually receive `HeadInfo` instances (not `ONNXHeadModel` masquerading as one). The TYPE_CHECKING import already exists.

#### 5. `nomarr/workflows/processing/process_file_wf.py` — edge mapping

**Change `ho.head._path` to `ho.head.model_path`:**

```python
path_map = output_id_map.get(ho.head.model_path)
```

This is the correct fix: `HeadInfo.model_path` holds the same absolute ONNX path that was previously accessed via `BaseONNXModel._path`.

#### 6. `nomarr/components/ml/onnx/ml_cache.py` — ONNXModelCache.__init__

**Modify** — line 103 accesses `head.backbone_name` to group heads by backbone. Update to use composed instance:

```python
self.heads.setdefault(head.meta.backbone, []).append(head)
```

#### 7. `nomarr/workflows/platform/register_ml_models_wf.py` — register_ml_models_workflow

**No code changes needed** — this file imports `head_parts_from_path` from `ml_head.py` (line 18) and calls it at line 72 to parse `(backbone, head_type, model_stem)` from ONNX paths. It does NOT construct `ONNXHeadModel` — it works directly with the DB model registry.

Since `head_parts_from_path()` is retained (see section 1), this file continues working unchanged.

#### 8. `nomarr/components/ml/inference/ml_heads_comp.py` — to_head_outputs type annotation

**Change parameter type:**

```python
def to_head_outputs(
    self,
    head_info: HeadInfo,  # was: ONNXHeadModel
    ...
) -> list[HeadOutput]:
```

The `TYPE_CHECKING` import of `HeadInfo` already exists in this file.

### Import Changes

| File | Change | Import-Linter Impact |
|------|--------|---------------------|
| `ml_head.py` | Add `TYPE_CHECKING` import of `HeadInfo` from `ml_discovery_comp` (see below) | None (same layer) |
| `ml_head.py` | Remove `from pathlib import Path` if no longer needed | None |
| `ml_heads_comp.py` | `HeadInfo` import already in TYPE_CHECKING | None |
| `ml_head_pipeline_comp.py` | No import changes needed | None |
| `ml_cache.py` | No import changes needed | None |
| `register_ml_models_wf.py` | No import changes needed | None |
| `ml_discovery_comp.py` | No import changes needed | None |
| All files | No cross-layer import changes | No new exceptions needed |

### HeadInfo Import in ml_head.py — Circular Import Resolution

`HeadInfo` lives in `ml_discovery_comp.py` (same package: `components/ml/onnx`). `ml_discovery_comp.py` already imports `ONNXHeadModel` from `ml_head.py`. A runtime import of `HeadInfo` in `ml_head.py` would create a circular import failure at module load time.

**Resolution:** Import `HeadInfo` under `TYPE_CHECKING` only. This is safe because:

1. `from __future__ import annotations` is already present in `ml_head.py`, so `meta: HeadInfo | None` is a string annotation at runtime — no runtime resolution needed.
2. The `meta` value is injected via the constructor parameter, which receives an already-constructed `HeadInfo` instance — no import needed to receive it.
3. The delegation properties access `self.meta.*` attributes on the already-constructed instance — also no import needed.

```python
if TYPE_CHECKING:
    from nomarr.components.ml.onnx.ml_discovery_comp import HeadInfo
```

**Do NOT use a runtime import.** The earlier Import Changes table entry saying "Add runtime import" was incorrect and has been corrected. ADR-026 permits TYPE_CHECKING for circular prevention within the same layer.

### Data Flow After Refactor

```
discover_head_models(models_dir, db):
    heads: list[HeadInfo] = discover_heads(models_dir, db)  # builds HeadInfo with labels
    head_info_map = {hi.model_stem: hi for hi in heads}
    for onnx_path in ...:
        info = head_info_map.get(stem)
        model = ONNXHeadModel(onnx_path, meta=info)  # HeadInfo passed in, not discarded

run_single_head(head_model, predict_fn):
    # Use model.meta for metadata
    head_outputs = decision.to_head_outputs(head_info=head_model.meta, ...)
    # HeadOutput.head is now actually HeadInfo ✓

process_file_wf:
    for ho in all_head_outputs:
        path_map = output_id_map.get(ho.head.model_path)  # HeadInfo.model_path ✓
```

---

## Design Goals

1. Apply ADR-028 composition principle: ONNXHeadModel holds HeadInfo, does not redeclare its fields
2. Fix HeadOutput.head type mismatch: annotation says HeadInfo, runtime receives ONNXHeadModel
3. Fix process_file_wf accessing private `_path` attribute on wrong type
4. Preserve all existing behavior — this is a structural refactor, not a behavioral change
5. No delegation properties — break the old API and fix all callers in one pass

---

## Constraints

- No file moves or ML package restructuring
- No multiple inheritance, protocols, or union types
- No changes to HeadSpec unless from_head_info needs updating
- Circular import between ml_head.py and ml_discovery_comp.py must be handled via TYPE_CHECKING
- discover_head_models_no_db() must still work without a database (synthesizes HeadInfo from path)
- model.meta must always be non-None after construction (both DB and no-DB paths)
- No delegation properties — all callers updated to use `model.meta.*` directly

---

## Open Questions

1. ~~Should delegation properties be kept for migration?~~ **Resolved:** No. Break the old API and fix all callers in one pass. No shims.
2. ~~Should `head_parts_from_path()` be deleted or kept as a utility?~~ **Resolved:** Keep it. `register_ml_models_wf.py` imports and calls `head_parts_from_path()` (line 18, 72) independently of `ONNXHeadModel` construction. It parses path metadata for the DB model registry workflow.

---
