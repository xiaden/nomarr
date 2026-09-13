# Phase 1 Gram/Chebyshev evidence

> **Historical/test-oracle only — superseded by the corrective repair.** Every scalar operation and comparison described below is historical evidence and test-only. Active production is NumPy row-normalization plus float32 `np.matmul`; scalar arithmetic is not a selectable engine, compatibility path, or production obligation (see `CONTRACTS.md` and the pending DD). This file must not be read as production authority.

## Call graph

`gram_from_stream -> normalize_float32`; `derive_all_temporal_global -> derive_temporal_global_from_gram -> _validate_gram, _threshold, _row_distance`; `_row_distance -> _add, _sqrt`. The Gram module has no import or call edge to vector segmentation or Chebyshev.

## Comparison boundary

`tests/test_chebyshev_gram_proof.py` contains the scalar-stream comparison oracle and branch fixtures. It is test-only and is not imported by production orchestration. `helpers/chebyshev_segmentation.py` is explicitly named `temporal_perdim_chebyshev_secondary`, accepts coordinate inputs, has no Gram import, and has no primary cache identity.

## Semantic evidence

The tests cover all 171 primary threshold indices, strict equality and one float32 ULP below the boundary, zero norms, source order, renormalized centroids, transient absorption and hard split, observed-medoid ties/zero/empty/nonfinite refusal, exact binary masks, absorbed membership, and normalized positive weight partition.
