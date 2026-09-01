# Embedding Research — Operational Notes

Research-only pipeline. This directory contains no production code; nothing here changes
production behavior. It runs its own embed/segmentation/analysis pipeline over a fixed song
corpus and emits a static HTML report for offline inspection.

- **Design contract**: see `CONTRACTS.md` (the authoritative module/API reference).
- **Findings log**: see `FINDINGS.md` (per-run conclusions, decisions, final semantics).

## Primary experiment scope (follow-on)

The default primary experiment is deliberately narrow (see `CONTRACTS.md`):

- **backbone**: `effnet` only by default; MusicNN is enabled only by explicit selection
  (`backbones=["effnet","musicnn"]`) and is never part of default runs.
- **flat baseline**: `flat_strategies=["medoid"]` (observed global medoid); **PTC representation**:
  `rep_types=["medoid"]`.
- **primary score variant**: `max_per_candidate_segment` — patch-count-weighted, deduplicated, with
  collision/winner/cosine/contribution traces and explicit tie/collision ambiguity variants.
- **CTP is deferred/archival** (`[archival_ctp] enabled=false`): available and callable, but never
  required for the primary corpus and never in primary winner/delta rows.
- **evaluation lenses**: MAP, MRR, NDCG, Recall, and discrimination are evaluation lenses, not
  optimization objectives, and are never collapsed into one composite.

## Phase order

The pipeline runs these phases in dependency order (see `run.py`):

```
ingest -> embed -> stratify -> segment -> classify -> analyze -> head -> report
```

- **ingest** — load songs and acoustic patch features into the research DB.
- **embed** — produce flat (global-pool) per-song embedding vectors.
- **stratify** — budgeted subset selection for a balanced run.
- **segment** — temporal segmentation of each song's patch stream into bins (PTC and CTP paths).
- **classify** — pool each segment and persist bin-level vectors.
- **analyze** — compute retrieval metrics and the flat-binned correlation for every config.
- **head** — pool classifier head outputs over the shared EffNet PTC boundary (optional, non-blocking).
- **report** — assemble the schema-v2 section dicts and render `report.html`.

## Required generated outputs

After a full run the following must exist under `{OUTPUT_ROOT}` (default
`scripts/outputs/embedding_research`):

| Output | Location |
| --- | --- |
| Report data | `{OUTPUT_ROOT}/report/report.json` |
| Rendered report | `{OUTPUT_ROOT}/report/report.html` |
| Research DB (DuckDB) | `{OUTPUT_ROOT}/research.duckdb` |
| Flat vectors | `{OUTPUT_ROOT}/cache/{backbone}/{strategy}/flat/{song_id}.npy` |
| Medoid flat vectors | `{OUTPUT_ROOT}/cache/{backbone}/medoid/flat/{song_id}.npy` |
| Binned PTC segments | `{OUTPUT_ROOT}/cache/binned_ptc/{tag}/{backbone}/{bin_mode}/{threshold}/{song_id}.npz` |
| Binned CTP segments | `{OUTPUT_ROOT}/cache/binned_ctp/{tag}/{backbone}/{head}/{threshold}/{song_id}.npz` |

`{tag}` is the cache semantics tag (see `cache_identity.py` / `cache_semantics_tag`); changing it
invalidates segment caches by selecting a different root (old roots are orphaned, never deleted).
Representation-pair matrix caches are additionally versioned under
`base/v{scoring_version}/{corpus_hash}` via `versioned_cache_root`, so a stale matching corpus or a
scoring-version change never reuses stale matrix cache entries. CTP segment caches are **archival**:
they are produced but never feed primary rows unless `[archival_ctp] enabled=true`.

## Baseline labels

Every winner/delta/headline claim is measured against the **explicit flat medoid baseline** for the
same backbone and K:

```
global_pool:{backbone}:medoid
```

e.g. `global_pool:effnet:medoid` and `global_pool:musicnn:medoid`. Each backbone is an independent
population with its own matching-corpus manifest and medoid; there is no cross-backbone aggregate and
no max/median/mean-across-flat fallback.

## Report tables

The report includes, per backbone:

- `winner_delta_{backbone}` — one row per `(group, metric, K)` grid cell: the deterministic winner
  (strategy key, type, value) and its delta vs the medoid baseline. 33 columns
  (`WINNER_DELTA_COLUMNS`).
- `factor_summary_{backbone}` — wins/deltas grouped by each configuration factor while retaining
  group × metric × K and the contributing strategy keys. 10 columns (`FACTOR_SUMMARY_COLUMNS`).
- Each `winner_delta_{backbone}` row carries the bounded per-pair trace summary
  (`trace_n_pairs`, `trace_numerator_sum/mean`, `trace_denominator_sum/mean`,
  `trace_collision_count`, `trace_winner_count`, `trace_retained_contributions`,
  `trace_dropped_contributions`, `trace_finite`) and the ambiguity variant
  (`winner_ambiguity_variant`), so collisions, winners, weights, cosines, and contribution
  retention stay visible.

Plus `backbone_summary` (flat medoid `disc_genre`, best binned config, `delta_vs_medoid`),
unified/per-backbone/threshold/binned-mode/head-value/head-output-shared-ptc-boundary/
head-sim-corr/flat-binned-correlation
sections. See `CONTRACTS.md` §6 for the exact section surface.

## Numerical fixture

The three **legacy weighted hypotheses** (opt-in comparison formulas, NOT the primary scoring
method — the primary score is `max_per_candidate_segment`, see `CONTRACTS.md` and
`tests/test_scoring_harness.py`) are pinned by an exact fixture in
`tests/test_weighted_scoring.py`:

```
S   = [[1, .2],
       [.4, .8]]
w_A = [1, 3]      # source (row) patch-count weights
w_B = [2, 1]      # target (column) patch-count weights
```

| Reduction | Input | Value |
| --- | --- | --- |
| `target_weighted(S, w_B)` | forward A→B | `0.6333333333` |
| `target_weighted(S.T, w_A)` | reverse B→A | `0.6000000000` |
| `bidirectional_weighted(S, S.T, w_B, w_A)` | mean of the two directions | `0.6166666667` |
| `normalized_mean_pair_weighted(S, w_A, w_B)` | globally weighted bilinear mean | `0.5833333333` |

Note `target_weighted` is directional (0.6333… vs 0.6000…); the reverse matrix is always supplied
separately, never derived by transposing the forward matrix.

## Running the tests

Full research suite:

```bash
python -m pytest scripts/embedding_research/tests/ -q
```

Early-exit equivalent (stop at first failure), as used by the quality gate:

```bash
python -m pytest scripts/embedding_research/tests/ -x -q
```

Config/doc-adjacent smoke (docs-only phases):

```bash
python -m pytest scripts/embedding_research/tests/test_toml.py scripts/embedding_research/tests/test_quality_gate.py -q
```

Byte-compile and formatter/linter checks:

```bash
python -m compileall scripts/embedding_research
ruff format --check scripts/embedding_research
ruff check scripts/embedding_research
```

Deterministic fixture report generation + validation:

```bash
python scripts/embedding_research/generate_fixture_report.py
python scripts/embedding_research/validate_fixture_report.py
```

The suite pins the fixtures, schema DTOs, score-harness/ambiguity semantics, weighted-hypothesis
fixtures, cache-identity behavior, and corpus identity above. Keep it green; do not weaken existing
assertions when extending the research docs or code. Fixture report numbers are synthetic
(see `FINDINGS.md`) unless a real model/audio run produced them.
