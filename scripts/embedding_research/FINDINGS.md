# Embedding Research Findings

Ongoing notes from research runs. Add findings as they emerge — don't wait for a "final" result.

## Current-state note (geometry hard cut)

The research pipeline is the threshold-independent per-song Gram geometry pipeline. One committed
observation group — the immutable stream, the aligned audio-derived silence mask, and the commit
marker written last — is the only usable evidence. The CLI exposes exactly seven phases
(`ingest`, `embed`, `infer-heads`, `geometry`, `analyze`, `head-analysis`, `report`); the
`geometry` phase derives and persists one exact-key complete geometry per `(song_id, backbone)`;
the `analyze` phase runs the corpus owner `common/geometry_analysis.py` over the exact 171-index
primary threshold grid; the `report` phase renders exactly seven sections. There is no per-patch
membership table and no durable threshold-result table. All execution evidence is deterministic
synthetic fixtures; no real corpus/model/audio/ONNX result is claimed here.

## Threshold and distance semantics

There is one threshold contract: the finite threshold-*application* semantics `direct_distance`,
with `configured == effective` exactly, resolved in `helpers/thresholds.py`. The primary Gram engine
compares rows by unit-vector L2 and derives all 171 primary thresholds from one decoded Gram; the
Chebyshev path is an explicit, separately-named secondary experiment (`temporal_perdim_chebyshev_secondary`) over
canonical coordinates, never a legacy threshold-selector variant of the primary path. The strict loader
`helpers/toml.py` rejects scaled, calibration, optimizer, weighted, and pooling settings, and never
warns-and-returns an empty mapping.

## Geometry evidence and identity

- A geometry is bound to its committed observation commit digest, `geometry_semantics_version`,
  `numerical_profile_digest`, and the complete observation evidence tuple;
  `verify_geometry_binding` compares that persisted tuple without rebinding or repair.
- A missing mask, provenance value, or payload digest is an integrity refusal; it is never filled
  from a default or treated as an all-searchable observation.
- Structural ranges yield the exact searchable membership reconstructed on read; absorbed outliers
  are represented exactly and segment medoids are stored as observed source patch indices.
- The observed whole-song source medoid is a separate baseline used for comparison, never a winner
  candidate, and no synthetic/coordinate-wise medoid is permitted.
- Strategy-key identity is decoded from `geometry:{backbone}:{score_variant}:v{version}:{keyset}`.

## Rulers and report

Artist, genre, and frozen semantic-head are three independent rulers; a missing or blank label
excludes the song from that ruler only, never into an `unknown` bucket. The report renders
`summary`, `corpus`, `analysis`, `winners`, `head-analysis`, `provenance`, and `efficiency`,
selecting a completed scope per `run_id` and refusing contradictory or incomplete runs. The
`winners` baseline is the observed whole-song source medoid baseline, which is never itself a
winner candidate.

## Deferred experiments

- The Chebyshev secondary path (`temporal_perdim_chebyshev_secondary`) is an explicitly-named experimental comparison,
  not a configurable legacy threshold-selector variant of the primary Gram engine.
- No real-corpus execution is planned inside this research tree; deterministic synthetic fixtures
  remain the only execution evidence.
