# Embedding Research — Operational Notes

Research-only pipeline. This directory contains no production code; nothing here changes
production behavior. All execution evidence is synthetic; no real corpus is used for the
threshold-independent Gram geometry migration.

## Geometry contract (current)

The threshold-independent per-song Gram geometry migration is complete. The hard cut removed the
retired filesystem-owned runtime and replaced it with the final geometry architecture described
here. Plans A–J provided the pinned profile, DuckDB-owned `song_patch_geometry`, complete
observation binding, Gram temporal-global derivation, explicit Chebyshev secondary, threshold
batching, transient search collapse, geometry-bound head analysis, and run-scoped lifecycle
primitives. Plan K added the missing corpus owner, and Plans L–U completed deletion, identity
persistence, reporting, phase topology, refusal/reset, proof, synthetic coverage, and final
evidence:

- `common/geometry_analysis.py` owns `GeometrySongRequest`, `GeometryCorpusRequest`,
  `FrozenGeometryEvaluation`, `GeometrySongAnalysis`, `build_geometry_corpus_request`,
  `write_geometries_for_current_songs`, `analyze_geometry_corpus`,
  `score_unique_geometry_representations`, and the `GeometryCorpusAnalysis` result/persistence
  adapters. The corpus owner provides these functions as the final geometry contract.
- The scheduler deterministically orders `(song_id, backbone)`, constructs requests from current
  songs plus one complete committed observation and exact geometry row per item, derives all
  structural/search projections before scoring, collapses only equal ordered search inputs within
  one experiment, and gathers frozen source rows once per unique representation. Primary
  `temporal_global`/unit-space L2 and the explicit `temporal_perdim_chebyshev_secondary`/Chebyshev secondary never
  collapse, including equal thresholds.
- The observed whole-song source medoid is a separate global baseline, never a winner candidate;
  artist, genre, and frozen semantic-head rulers remain independent and missing labels are
  ruler-local exclusions. Publication is finite, exact-identity keyed, run-scoped, and atomic
  through the existing invocation-obligation/terminal-completion lifecycle.
- The primary threshold grid is exactly 171 indexed hypotheses `(0..170)`; the explicit
  `temporal_perdim_chebyshev_secondary`/Chebyshev secondary never collapses with primary `temporal_global`, even at
  equal numeric thresholds.
- `geometry`, `analyze`, `head-analysis`, and `report` are CPU-only. No audio discovery, model,
  ONNX, CUDA, compatibility path, alternate reader, dual write, filesystem view, durable
  threshold-result table, production integration, or real-corpus run is permitted.

See `CONTRACTS.md` for the binding API and `FINDINGS.md` for run conclusions.

## Migration status

The hard cut is complete. The research tree contains no retired ownership module, reader, writer,
dual schema, or dynamic registry; the deleted surfaces and their geometry replacements are
recorded as historical traceability in the formal planning and evidence artifacts. Every active
caller, test, fixture, report, maintenance seam, schema consumer, and serialized phase consumes
the geometry contract. Each migration phase required compileall, clean import smoke, and focused
synthetic tests; no compatibility runtime or dual reader/writer remains. The seven-phase topology,
the geometry-preserving analysis reset, the unavailable geometry reset, stale-evidence refusal,
and the R1–R14 evidence matrix are all final.

- **Design contract**: see `CONTRACTS.md` (the authoritative module/API reference).
- **Findings log**: see `FINDINGS.md` (per-run conclusions, decisions, final semantics).

## CLI phases

`run.py` exposes exactly seven phases. `ingest`, `embed`, and `infer-heads` are AUDIO phases
(they may load models / run ONNX); `geometry`, `analyze`, `head-analysis`, and `report` are
CPU-only DERIVED phases.

| phase | responsibility | class |
| --- | --- | --- |
| `ingest` | discover audio and register normalized corpus songs | AUDIO |
| `embed` | bounded backbone inference into immutable streams/registry | AUDIO |
| `infer-heads` | aligned classifier head streams into registry | AUDIO |
| `geometry` | derive and persist one exact-key geometry per committed observation | CPU |
| `analyze` | run the geometry corpus owner over committed geometry evidence | CPU |
| `head-analysis` | analyze aligned head evidence over completed geometry projections | CPU |
| `report` | render the seven deterministic report sections | CPU |

## Required generated outputs

| artifact | produced by | notes |
| --- | --- | --- |
| stream sidecars + `stream_registry` | `embed` | immutable float32 unit-normed patch arrays per `(song_id, backbone)` |
| aligned silence mask + observation commit | `embed` | committed observation group written last |
| head streams + `head_stream_registry` | `infer-heads` | finite `[T,C]` rows aligned to the backbone patch count |
| `song_patch_geometry` rows | `geometry` | one exact-key complete geometry per `(song_id, backbone)` |
| `geometry_analysis_records` | `analyze` | run-scoped identity-keyed analysis with the observed baseline |
| `geometry_head_evidence` | `head-analysis` | geometry-bound head evidence |
| rendered report | `report` | seven sections: summary, corpus, analysis, winners, head-analysis, provenance, efficiency |
| `phase_timings` / `run_provenance` | every phase | efficiency and reuse/refusal provenance |

## Immutable filesystem artifacts and reindex

The authoritative research artifacts are the immutable stream and head sidecars, their manifests,
the aligned silence masks, and the observation commit markers. Registry rows are rebuildable
index/cache metadata: `reindex` reconciles each registry row to exactly `ready`, `missing`, or
`corrupt` from the on-disk manifests, and only `ready` records that also validate on disk may be
read. Paths are never IDs or SQL keys.

## Report contract

`report` renders exactly seven sections (`summary`, `corpus`, `analysis`, `winners`,
`head-analysis`, `provenance`, `efficiency`) and selects a completed scope per `run_id`; a
contradictory or incomplete run is refused, never silently selected. The `winners` baseline per
`(backbone, sim_metric, k, metric)` is the observed whole-song source medoid baseline, which is
never itself a winner candidate. See `CONTRACTS.md` for the full section contract.

## Running the tests

The research test baseline is:

```bash
python -m pytest scripts/embedding_research/tests/ -x -q
```

Tests are deterministic and synthetic-only; no audio, model, ONNX, or CUDA is required for the
`geometry`, `analyze`, `head-analysis`, and `report` phases.

## Maintenance reset scopes

Maintenance verbs are run-scoped. `verify` revalidates committed observations and geometry;
`reindex` rebuilds registry metadata from disk; `cleanup` removes incomplete or orphaned artifacts;
`reset` accepts only the single `analysis` scope. Streams, masks, and heads are no longer valid
reset scopes (the committed input sidecars they name are immutable and required by upstream
phases), and a geometry reset is explicitly unavailable: `reset --scope geometry` is refused with
`GEOMETRY_RESET_UNAVAILABLE`, because geometry rows and BLOBs are the durable analysis substrate
rather than disposable state. `reset --scope analysis` preserves every geometry row and BLOB
byte-for-byte.
