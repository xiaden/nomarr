# ADR-026 Import Refactor — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-20  

**Related Documents:**

- [Top-Level Imports by Default]() —
- [Runtime Imports for FastAPI Depends Types]() —

---

## Scope

All Python files in nomarr/ — move deferred imports to top-level, consolidate TYPE_CHECKING blocks, remove stale circular-import workarounds. Does NOT touch app.py, start.py, discovery_worker.py (allowed DI/entrypoint wiring), essentia imports in ml_audio_comp.py/ml_preprocess_comp.py, or deferred onnxruntime imports (ADR-026 exception 1). Note: top-level onnxruntime imports (e.g., ml_base.py) are already compliant.

---

## Problem Statement

ADR-026 establishes that all imports must be at module level by default, with only two narrow exceptions (heavy environment-conditional third-party libs and DI wiring in app entry points). The current codebase has ~64 deferred imports scattered across components, services, workflows, interfaces, migrations, and persistence that violate this rule. Additionally, one file uses `Any` with a circular-import avoidance comment that should be replaced with a proper TYPE_CHECKING import. These violations hide import errors until runtime, blind static analysis tools (import-linter, pyright), and scatter dependency declarations away from the top of files.

---

## Architecture

## Audit Results

### Category 1: Deferred Imports to Move to Top-Level

#### Components Layer (27 violations)

 | File | Line | Import | Function | Type |
 | ------ | ------ | -------- | ---------- | ------ |
 | `components/library/library_file_query_comp.py` | 449 | `from nomarr.components.library.library_file_state_comp import count_untagged_files` | `get_library_stats` | 1P |
 | `components/library/library_records_comp.py` | 266 | `from nomarr.components.library.scan_lifecycle_comp import get_scan_state` | `_merge_scan_state` | 1P |
 | `components/library/missing_file_detection_comp.py` | 47 | `from pathlib import Path` | `detect_missing_files` | stdlib |
 | `components/library/move_detection_comp.py` | 227 | `from nomarr.components.metadata.entity_seeding_comp import ...` | `apply_detected_moves` | 1P |
 | `components/library/move_detection_comp.py` | 231 | `from nomarr.components.metadata.metadata_cache_comp import ...` | `apply_detected_moves` | 1P |
 | `components/ml/calibration/ml_calibration_comp.py` | 163 | `from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db` | `save_calibration_sidecars` | 1P |
 | `components/ml/calibration/ml_calibration_comp.py` | 174 | `from nomarr.components.tagging.mood_labels_comp import normalize_tag_label` | `save_calibration_sidecars` | 1P |
 | `components/ml/calibration/ml_calibration_comp.py` | 285 | `import hashlib` | `compute_calibration_def_hash` | stdlib |
 | `components/ml/calibration/ml_calibration_comp.py` | 576 | `import hashlib` | `compute_global_calibration_hash` | stdlib |
 | `components/ml/onnx/ml_base.py` | 216 | `from nomarr.components.ml.resources.ml_vram_probe_comp import ...` | `run` | 1P |
 | `components/ml/onnx/ml_discovery_comp.py` | 412 | `from nomarr.components.ml.onnx.ml_backbone import ONNXBackboneModel` | `discover_backbone_models` | 1P |
 | `components/ml/onnx/ml_discovery_comp.py` | 453 | `from nomarr.components.ml.onnx.ml_head import ONNXHeadModel` | `discover_head_models_no_db` | 1P |
 | `components/ml/onnx/ml_discovery_comp.py` | 498-500 | `from pathlib import Path` + `from ...ml_head import ONNXHeadModel` | `discover_head_models` | stdlib+1P |
 | `components/ml/onnx/ml_session_comp.py` | 109 | `import os` | `create_session` | stdlib |
 | `components/ml/resources/ml_capacity_probe_comp.py` | 298 | `from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db` | `_run_capacity_probe` | 1P |
 | `components/ml/resources/ml_capacity_probe_comp.py` | 325 | `from nomarr.components.ml.onnx.ml_cache import ONNXModelCache` | `_run_capacity_probe` | 1P |
 | `components/ml/resources/ml_vram_probe_comp.py` | 178 | `import threading` | `_probe_single_model` | stdlib |
 | `components/ml/vectors/ml_vector_idle_promotion_comp.py` | 36 | `from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones` | `list_hot_vector_targets` | 1P |
 | `components/ml/vectors/ml_vector_idle_promotion_comp.py` | 73 | `from nomarr.helpers.vector_params_helper import compute_nlists` | `compute_promotion_nlists` | 1P |
 | `components/ml/vectors/ml_vector_maintenance_comp.py` | 74 | `from nomarr.components.ml.onnx.ml_discovery_comp import _resolve_embedding_graph` | `derive_embed_dim` | 1P |
 | `components/navidrome/tag_query_comp.py` | 115 | `from nomarr.helpers.tag_key_mapping import ...` | `get_short_to_versioned_mapping` | 1P |
 | `components/platform/arango_bootstrap_comp.py` | 153 | `from nomarr.helpers.constants.file_states import ALL_STATE_VERTICES` | `_seed_file_states` | 1P |
 | `components/platform/arango_bootstrap_comp.py` | 449 | `from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads_no_db` | `_discover_backbone_ids` | 1P |
 | `components/platform/arango_bootstrap_comp.py` | 474 | `from nomarr.components.ml.onnx.ml_discovery_comp import discover_backbones` | `provision_vectors_track_for_library` | 1P |
 | `components/platform/gpu_monitor_comp.py` | 79 | `from nomarr.components.platform import probe_gpu_availability` | `run` | 1P |
 | `components/platform/gpu_monitor_comp.py` | 82 | `from nomarr.persistence.db import Database` | `run` | 1P |
 | `components/tagging/tag_parsing_comp.py` | 72 | `import ast` | `parse_tag_values` | stdlib |

#### Services Layer (10 violations)

 | File | Line | Import | Function | Type |
 | ------ | ------ | -------- | ---------- | ------ |
 | `services/domain/calibration_svc.py` | 446 | `from nomarr.components.ml.calibration.ml_calibration_state_comp import ...` | `clear_calibration` | 1P |
 | `services/domain/navidrome_svc.py` | 93 | `from nomarr.components.navidrome.tag_query_comp import ...` | `get_tag_values` | 1P |
 | `services/domain/navidrome_svc.py` | 327 | `from nomarr.components.navidrome.subsonic_client_comp import SubsonicClient` | `_get_client` | 1P |
 | `services/domain/navidrome_svc.py` | 400 | `from nomarr.workflows.navidrome.sync_navidrome_wf import ...` | `sync_navidrome` | 1P |
 | `services/domain/navidrome_svc.py` | 434 | `from nomarr.workflows.navidrome.find_similar_tracks_wf import ...` | `get_similar_tracks` | 1P |
 | `services/domain/navidrome_svc.py` | 463 | `from nomarr.workflows.navidrome.ingest_scrobble_wf import ...` | `ingest_scrobble` | 1P |
 | `services/domain/navidrome_svc.py` | 499 | `from nomarr.workflows.navidrome.generate_playlists_wf import ...` | `generate_playlists` | 1P |
 | `services/domain/vector_search_svc.py` | 73-74 | `from nomarr.components.library.file_library_comp import ...` + `ml_vector_retrieve_comp` | `search_similar_tracks` | 1P |
 | `services/domain/vector_search_svc.py` | 236 | `from nomarr.workflows.vectors.get_track_vector_wf import ...` | `get_track_vector` | 1P |
 | `services/infrastructure/ml_svc.py` | 101 | `from nomarr.components.ml.resources.ml_vram_probe_comp import ...` | `clear_vram_measurements` | 1P |

#### Workflows Layer (17 violations)

 | File | Line | Import | Function | Type |
 | ------ | ------ | -------- | ---------- | ------ |
 | `workflows/calibration/apply_calibration_wf.py` | 81 | `import math` | `apply_calibration_wf` | stdlib |
 | `workflows/calibration/apply_calibration_wf.py` | 83-89 | 5 first-party imports | `apply_calibration_wf` | 1P |
 | `workflows/calibration/calibration_loader_wf.py` | 103 | `from ...ml_calibration_state_comp import ...` | `load_calibrations_cached_wf` | 1P |
 | `workflows/calibration/generate_calibration_wf.py` | 338-344 | 3 first-party imports | `generate_histogram_calibration_wf` | 1P |
 | `workflows/calibration/import_calibration_bundle_wf.py` | 161,196,289 | 3 first-party imports | `import_calibration_bundle_wf` / `import_calibration_bundles_from_directory_wf` | 1P |
 | `workflows/calibration/write_calibrated_tags_wf.py` | 205 | `from ...calibration_loader_wf import ...` | `_load_calibrations_from_db` | 1P |
 | `workflows/platform/idle_promotion_vectors_wf.py` | 113,117 | 2 first-party imports | `idle_promotion_vectors_workflow` | 1P |
 | `workflows/processing/write_file_tags_wf.py` | 92 | `from nomarr.components.infrastructure.path_comp import ...` | `_resolve_library_path` | 1P |

#### Interfaces Layer (1 violation, excluding DI factory exceptions)

 | File | Line | Import | Function | Type |
 | ------ | ------ | -------- | ---------- | ------ |
 | `interfaces/api/web/vectors_if.py` | 194-195 | `import asyncio` + `from concurrent.futures import ThreadPoolExecutor` | `get_vector_stats` | stdlib |

`api_app.py`, `auth.py`, `admin_if.py`, and `dependencies.py` are all covered by ADR-026 exception 2 (DI factory modules importing the `application` singleton). See Category 3: Allowed Exceptions.

#### Persistence Layer (3 violations)

 | File | Line | Import | Function | Type |
 | ------ | ------ | -------- | ---------- | ------ |
 | `persistence/constructor/builder.py` | 97 | `from nomarr.persistence.constructor.namespaces import CollectionNamespace` | `build_collection_namespace` | 1P |
 | `persistence/constructor/builder.py` | 169 | `from nomarr.persistence.constructor.namespaces import CollectionNamespace` | `build` | 1P |
 | `persistence/constructor/namespaces.py` | 421 | `from nomarr.persistence.constructor.cascade import CascadeEngine` | `_cascade` | 1P |

#### Migrations (3 occurrences — special case)

 | File | Line | Import | Type |
 | ------ | ------ | -------- | ------ |
 | `migrations/V001_baseline.py` | 45 | `from arango.exceptions import ...` | 3P |
 | `migrations/V021_schema_refactor_v1.py` | 39 | `from arango.exceptions import ...` | 3P |
 | `migrations/V023_library_pipeline_states.py` | 63,80 | `from nomarr.services...` + `from arango.exceptions import ...` | 1P+3P |

Migrations are frozen historical artifacts but will be updated (import-only changes, no logic).

### Category 2: Files with Multiple TYPE_CHECKING Blocks

**None found.** All 157 files using `if TYPE_CHECKING:` have exactly one block. The codebase is already compliant with this rule.

### Category 3: Allowed Exceptions (No Action Required)

 | File | Import | Justification |
 | ------ | -------- | --------------- |
 | `components/ml/audio/ml_audio_comp.py:82` | `import essentia.standard` | Heavy env-conditional lib |
 | `components/ml/audio/ml_preprocess_comp.py:169` | `import essentia.standard` | Heavy env-conditional lib |
 | `components/ml/resources/ml_vram_probe_comp.py:128` | `import onnxruntime` (deferred) | Heavy env-conditional lib — ADR-026 exception 1 |
 | `components/ml/vectors/ml_vector_maintenance_comp.py:81` | `import onnxruntime` (deferred) | Heavy env-conditional lib — ADR-026 exception 1 |
 | `workflows/platform/register_ml_models_wf.py:59` | `import onnxruntime` (deferred) | Heavy env-conditional lib — ADR-026 exception 1 |
 | `components/ml/onnx/ml_base.py:22` | `import onnxruntime` (top-level) | Already compliant — not a violation, not an exception |
 | `app.py` (all ~20 deferred imports) | DI wiring | Factory registration pattern |
 | `services/infrastructure/workers/discovery_worker.py` (all ~40 deferred imports) | DI wiring | Worker subprocess initialization |
 | `start.py` (deferred imports inside `if __name__ == "__main__":` guard) | Entrypoint wiring | Application entrypoint — same pattern as app.py/discovery_worker.py |
 | `interfaces/api/web/dependencies.py` (16 `from nomarr.app import application`) | DI factory | FastAPI Depends() factories — ADR-026 exception 2 |
 | `interfaces/api/api_app.py:36` | DI factory | Lifespan imports application singleton — ADR-026 exception 2 |
 | `interfaces/api/auth.py:17` | DI factory | Auth factory imports application singleton — ADR-026 exception 2 |
 | `interfaces/api/web/admin_if.py:39` | DI factory | Admin restart imports application singleton — ADR-026 exception 2 |

**Note on `onnxruntime`:** Some files import `onnxruntime` at top-level (e.g., `ml_base.py:22`) — these are already compliant and are not violations. Only the deferred (inside-function-body) imports listed above are ADR-026 exception 1 allowances. The DD does not imply all `onnxruntime` imports are deferred.

### Category 4: Stale Circular-Import Workarounds

 | File | Line | Issue | Fix |
 | ------ | ------ | ------- | ----- |
 | `helpers/dto/ml_dto.py` | 37 | `head: Any  # HeadInfo from components - use Any to avoid circular import` | Replace `Any` with proper `HeadInfo` type. Since `ml_dto.py` is in helpers and `HeadInfo` is in components, this is an upward import — use `TYPE_CHECKING` guard instead of `Any`. |

---

## Risk Assessment

### Low Risk (stdlib moves)

Moving `import ast`, `import hashlib`, `import os`, `import math`, `import threading`, `from pathlib import Path`, `import asyncio`, `from concurrent.futures import ThreadPoolExecutor` to top-level has zero risk. These are always available and have no side effects.

### Low Risk (first-party moves within same or lower layer)

Most first-party deferred imports are components importing other components or helpers — lateral or downward. These cannot cause import cycles by construction (import-linter enforces layer boundaries). Risk is near zero.

### Medium Risk: persistence/constructor mutual imports

`builder.py` imports `namespaces.py` and `namespaces.py` imports `cascade.py`. Need to verify no circular reference exists between builder↔namespaces. The fact that the code works today with deferred imports means the modules do reference each other — moving to top-level could surface a cycle. **Verify with import-linter before/after.**

### Medium Risk: dependencies.py pattern

The `from nomarr.app import application` pattern inside Depends factories exists because `application` is a module-level singleton that hasn't been initialized when the module is first imported. Moving it to top-level would import `application` before it's constructed. **This is a genuine runtime-order concern, not a cargo-culted deferral.** Requires a design decision.

### Low Risk: ml_dto.py HeadInfo type

The `head: Any` workaround is for a helpers→components upward import. Using `TYPE_CHECKING` is the standard fix and involves no runtime behavior change.

### Negligible Risk: Migrations

Migrations are frozen, append-only, run-once. Changing their import structure is cosmetically correct but functionally irrelevant.

---

## ADR-006 Interaction

ADR-006 requires that in FastAPI route files using `from __future__ import annotations`, service types used in `Annotated[..., Depends(...)]` must be **runtime-imported** (not under TYPE_CHECKING). This is fully compatible with ADR-026:

- Both ADRs agree: imports belong at the top of the file
- ADR-006 adds: specifically, `Depends()` parameter types must be runtime, not TYPE_CHECKING-guarded
- The current route files (`public_if.py`, `admin_if.py`, `navidrome_v1_if.py`, `vectors_if.py`) already comply with both ADRs

No conflict exists. The refactor should not move any Depends-used types into TYPE_CHECKING blocks.

---

## Scope Summary

 | Category | Files | Import Moves | Complexity |
 | ---------- | ------- | ------------- | ------------ |
 | Stdlib deferred → top-level | 8 files | 10 imports | Trivial |
 | First-party deferred → top-level | 25 files | 50 imports | Low |
 | TYPE_CHECKING consolidation | 0 files | 0 | None needed |
 | Circular-import workaround cleanup | 1 file | 1 type annotation | Low |
 | DI factory exceptions (no action) | 4 files | 0 | Exception 2 |
 | Migrations | 3 files | 4 imports | Low (careful) |
 | **Total** | **34 files** | **64 imports** | **Low-Medium** |

---

## Phasing Strategy

### Phase A: Stdlib Imports (Trivial, Zero Risk)

Move all deferred stdlib imports (`ast`, `hashlib`, `os`, `math`, `threading`, `pathlib.Path`, `asyncio`, `concurrent.futures`) to top-level. ~12 imports across ~8 files. Run lint + tests.

### Phase B: First-Party Component/Helper Imports (Low Risk)

Move all deferred first-party imports within components, persistence, and helpers layers. These are lateral or downward imports. ~25 imports across ~12 files. Run import-linter after to verify no cycles.

### Phase C: First-Party Cross-Layer Imports (Low Risk)

Move deferred imports in services (→ components/workflows) and workflows (→ components). These follow the correct dependency direction. ~20 imports across ~10 files.

### Phase D: Interface Layer + Circular Import Cleanup

- Move `asyncio`/`ThreadPoolExecutor` in `vectors_if.py` to top-level
- Fix `ml_dto.py` `head: Any` → proper `TYPE_CHECKING` import of `HeadInfo`
**Resolved:** `api_app.py`, `auth.py`, `admin_if.py`, and `dependencies.py` are all covered by ADR-026 exception 2 (DI factory modules). No action needed for their `from nomarr.app import application` imports.

### Phase E: Migrations (Careful)

Move deferred imports in V001, V021, V023 to top-level. These are frozen historical files — changes are import-only, no logic changes. Verify each migration still runs correctly after the move.

---

## Verification Strategy

1. **import-linter** — Run `lint-imports` after each phase. Must pass with zero violations.
2. **pyright** — Full type check to confirm no new type errors introduced.
3. **pytest** — Full test suite (unit + integration) to confirm no runtime breakage.
4. **Startup test** — Run `python -c "from nomarr.app import Application"` to verify import-time errors surface.
5. **Grep audit** — After all phases, re-run the deferred-import AST scanner to confirm zero violations remain (excluding allowed exceptions).
6. **TYPE_CHECKING count** — Confirm still exactly 0-1 blocks per file.

---

## Open Questions

*All resolved:*

1. ~~Should `dependencies.py` be covered by ADR-026 exception 2?~~ **Yes.** ADR-026 exception 2 updated to explicitly cover DI factory modules including `dependencies.py`, `api_app.py`, `auth.py`.
2. ~~Should migrations be touched?~~ **Yes.** Import-only changes, no logic. Handle carefully.
3. ~~Should `api_app.py`/`auth.py`/`admin_if.py` be treated the same?~~ **Yes.** Covered by updated exception 2.

---

## Design Goals

- Bring the entire nomarr/ codebase into compliance with ADR-026
- Improve static analysis coverage (import-linter, pyright)
- Surface import errors at startup rather than hiding in runtime paths
- Maintain zero circular imports invariant
- Preserve allowed exceptions for heavy third-party libs and DI wiring

---

## Constraints

- Must not break runtime behavior (all tests pass after each phase)
- Must not introduce circular imports
- Must not move deferred essentia/onnxruntime imports to top-level (env-conditional, ADR-026 exception 1)
- Must not move DI wiring imports in app.py/start.py/discovery_worker.py (entrypoint pattern)
- ADR-006 carve-out for FastAPI Depends types must be preserved
- Migrations are frozen historical artifacts (touching them is optional/low priority)

---
