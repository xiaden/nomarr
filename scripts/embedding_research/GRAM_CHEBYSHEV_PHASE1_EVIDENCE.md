# Phase 1 Gram/Chebyshev evidence

## Call graph

`gram_from_stream -> normalize_float32`; `derive_all_temporal_global -> derive_temporal_global_from_gram -> _validate_gram, _threshold, _row_distance`; `_row_distance -> _add, _sqrt`. The Gram module has no import or call edge to vector segmentation or Chebyshev.

## Comparison boundary

`tests/test_chebyshev_gram_proof.py` contains the scalar-stream comparison oracle and branch fixtures. It is test-only and is not imported by production orchestration. `helpers/chebyshev_segmentation.py` is explicitly named `temporal_perdim_chebyshev_secondary`, accepts coordinate inputs, has no Gram import, and has no primary cache identity.

## Semantic evidence

The tests cover all 171 primary threshold indices, strict equality and one float32 ULP below the boundary, zero norms, source order, renormalized centroids, transient absorption and hard split, observed-medoid ties/zero/empty/nonfinite refusal, exact binary masks, absorbed membership, and normalized positive weight partition.
