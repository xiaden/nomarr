# Task: Replace LABEL_PAIRS with Structural Head-Based Suppression

## Problem Statement

The `ml_known_models.py` refactor replaced raw model output names with human-readable labels and moved label definitions into the DB, seeded from `KNOWN_MODELS`. This broke `LABEL_PAIRS` in `mood_labels_comp.py`, which drives conflict suppression in `_compute_suppressed_keys` and display mapping in `_build_label_map` via `simplify_label(label) == pos_pat` pattern matching.

Patching `LABEL_PAIRS` to match the new label strings is the wrong fix. `LABEL_PAIRS` was a workaround for unstructured label data. Two distinct suppression cases now need separate, correct handling:

**Case 1 — Intra-head conflict:** Two outputs of the *same* head instance both get tiers (e.g. `mood_happy` fires both `"happy"` and `"sad"` with tiers from a single scan). These share `ho.head` identity by definition and can be suppressed structurally.

**Case 2 — Cross-head conflict (the important one):** Two *different* head instances both get tiers on semantically opposing labels (e.g. `mood_happy` fires `"happy"` AND `mood_sad` fires `"sad"`). These have different `ho.head` objects — structural grouping misses them. `LABEL_PAIRS` was specifically protecting against this case.

Both cases are solvable without a manually maintained table. `KNOWN_MODELS` already declares which labels are semantic opponents: any two labels defined as co-outputs of the same model stem are mutual opponents (e.g. `mood_happy` defines `"happy"` and `"sad"`, so they oppose each other). Build a derived opponent map at startup from `KNOWN_MODELS` (or from the DB's `ml_model_outputs`). Cross-head suppression then becomes: if tiered output A and tiered output B carry opposing labels per the derived map, and they come from *different* heads, suppress both.

The label-mapping job of `_build_label_map` is already done by `KNOWN_MODELS` — labels are display terms at assignment time, so no post-hoc remapping is needed. `simplify_label` and `LABEL_PAIRS` become dead code once suppression is restructured.

## Phases

### Phase 1: Build derived opponent map from KNOWN_MODELS

- [x] Add a function `build_opponent_map(known_models: dict) -> dict[str, set[str]]` in `ml_known_models.py`: for each model stem, all labels co-defined in that stem are mutual opponents; return a flat map of `label -> set of opponent labels`
- [x] Export the pre-computed map as a module-level constant `OPPONENT_MAP` derived from `KNOWN_MODELS` so callers import it without re-computing

### Phase 2: Replace suppression logic in tagging_aggregation_comp.py

- [x] Replace `_compute_suppressed_keys` with a two-pass implementation: (a) intra-head pass — group tiered outputs by `id(ho.head)`, suppress weaker when >1 tiered output from the same head; (b) cross-head pass — for each remaining tiered output, check if any other tiered output from a *different* head carries an opponent label per `OPPONENT_MAP`; suppress both when found
- [x] Remove `_build_label_map` and its call site in `aggregate_mood_tiers`; `ho.label` is already the display term
- [x] Update `aggregate_mood_tiers` to pass no `label_pairs` argument and use `ho.label` directly as the display term in `_build_tier_term_sets`
- [x] Remove the `label_pairs` parameter from `_compute_suppressed_keys` signature

### Phase 3: Remove dead code

- [x] Remove `LABEL_PAIRS` list and its docstring from `mood_labels_comp.py`
- [x] Check if `simplify_label` is referenced anywhere outside `tagging_aggregation_comp.py`; if not, remove it from `mood_labels_comp.py`
- [x] Remove the `LABEL_PAIRS` import from `tagging_aggregation_comp.py` and confirm no other importers remain

### Phase 4: Verify and validate

- [x] Search codebase for remaining references to `LABEL_PAIRS`, `_build_label_map`, `simplify_label` to confirm all call sites are gone
- [x] Run `lint_project_backend(path="nomarr/components/tagging")` and confirm zero errors
- [x] Run `lint_project_backend(path="nomarr/components/ml")` and confirm zero errors

## Completion Criteria

- `OPPONENT_MAP` is derived from `KNOWN_MODELS` with no hardcoded label strings outside `KNOWN_MODELS`
- `_compute_suppressed_keys` handles both intra-head (structural grouping) and cross-head (opponent map lookup) suppression
- `LABEL_PAIRS` list is deleted
- `_build_label_map` is deleted
- `simplify_label` is deleted or confirmed used elsewhere for a separate purpose
- Cross-head suppression correctly fires for `happy`/`sad` and `aggressive`/`relaxed` conflicting across distinct head instances
- `lint_project_backend` reports zero errors on affected modules

## References

- `nomarr/components/ml/ml_known_models.py` — authoritative label definitions; add `build_opponent_map` and `OPPONENT_MAP` here
- `nomarr/components/tagging/mood_labels_comp.py` — `LABEL_PAIRS`, `simplify_label` to remove
- `nomarr/components/tagging/tagging_aggregation_comp.py` — `_compute_suppressed_keys`, `_build_label_map`, `aggregate_mood_tiers` to update
- `nomarr/helpers/dto/ml_dto.py` — `HeadOutput.head` field used for intra-head structural grouping
