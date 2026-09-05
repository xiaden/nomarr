---
name: embedding-research
description: Use when working on any file in scripts/embedding_research/. Covers research-only scope, the authoritative contracts source (scripts/embedding_research/CONTRACTS.md), change protocol, and test baselines for the embedding research scripts.
---

# Skill: Embedding Research Scripts

## Scope

**Research-only.** `scripts/embedding_research/` is a standalone research codebase, NOT production code. Work here never touches `nomarr/`, `frontend/`, or production schemas. Contracts, tests, docs, and formal planning artifacts under `scripts/embedding_research/` are the entire scope.

Load this skill before reading or editing any file under `scripts/embedding_research/`.

## Authoritative contracts source: `scripts/embedding_research/CONTRACTS.md`

`CONTRACTS.md` is the **single binding reference** for the embedding-research API/schema, frozen invariants, storage model, deletion inventory, and change surface. Treat it as authoritative over any skill or doc text.

- Contracts are **consolidated in `CONTRACTS.md`** — there are no `_contracts_part_1.md`…`_contracts_part_7.md` split files and no `RULES.md`; earlier text referring to those files is stale.
- `FINDINGS.md` and `README.md` hold narrative/audit context (incl. the legacy-fidelity audit and Plan A inventory); `CONTRACTS.md` is the binding contract.
- The tree is under active corrective-pass development. Detailed phase plans, line references, and the deletion inventory in `CONTRACTS.md`/`FINDINGS.md` change as the corrective pass proceeds — do not restate them from memory; read the current file.

## Frozen invariants (verified; do not regress)

The following invariants are current in the working tree (see `CONTRACTS.md` "Scope and invariants" and `tests/test_frozen_invariants.py`):

- **`disc_album` does not exist** — never SELECT, upsert, guard, or reference it anywhere.
- **`act[1]` is the class-1 probability** (`act = [p0, p1]`) for head scores, disc, binning.
- **`bin_idx` formula is frozen**: `np.minimum((h_scores * 10).astype(np.int32), 9)`.
- PTC segmentation uses a running spherical centroid, strict `>`, `OUTLIER_WINDOW=3`, and direct L2 / per-dimension distance modes.
- Medoids are observed source rows with smallest-index ties; absorbed outliers are represented exactly; global flat identity is `global_pool:{backbone}:medoid`.
- No `agg_method=medoid`, no synthetic (coordinate-wise) median, no non-finite output, no cross-backbone corpus mixing.
- Exactly ONE threshold contract: finite DIRECT L2 between normalized unit vectors with `configured == effective` exactly (`helpers/thresholds.py`); `std_scaled`/calibration/p50 vocabulary is historical.

> **Invariant-verification caveat:** the legacy flat/binned retrieval-metric-layer invariants older versions of this skill asserted (zero-exclusion-of-zeroes in `disc_general`, `as_tuple()`-vs-INSERT column order, "5-layer atomic metric updates", and the old `FLAT_COLUMNS`/`BINNED_COLUMNS` lists) belong to the legacy metric layer that the corrective pass consolidates under the frozen stream/catalog contract. Those were not re-asserted as current here because the relevant modules are under active corrective-pass change in this working tree — the authoritative statement of what remains is `CONTRACTS.md` and the live code.

## Structural map (stable top-level modules — confirm before relying on any sub-module)

Confirmed present at read time (sub-module layout is changing; verify before editing):

- `run.py` — CLI orchestration
- `streams/` — StreamStore (patch/head stream publication & reconciliation)
- `search_views.py`, `bounded_scoring.py`, `scoring_harness.py`, `catalog.py`, `catalog_identity.py`, `catalog_report.py` — catalog + search-view + scoring surface
- `db/` — DuckDB scalar/metadata/catalog schema (`_schema.py`) and writers
- `helpers/` — `thresholds.py`, `toml.py`, `binning.py`, `segmentation.py` (pure, dependency-light helpers)
- `common/` — shared embed / head-analysis / stratify logic
- `report/` — report rendering (`_base.py`, `_retrieval.py`, `_binned.py`, …)
- `strategy_{global_pool,ptc,ctp}/`, `strategy_binned/` — pooling/segment strategy modules
- `pooling.py`, `similarity.py`, `classify.py`, `head_pooling.py`, `config.py`, `corpus.py`, `vector_types.py`, `cache_identity.py`
- `tests/` — research test suite; `generate_fixture_report.py` / `validate_fixture_report.py` — fixture report harness
- `research_config.toml` — executable config (strict loader `helpers/toml.py`)

## Before Any Edit

1. Read the current `scripts/embedding_research/CONTRACTS.md` (scope + invariants + any contract for the file you'll touch).
2. Read the relevant tests under `scripts/embedding_research/tests/` for the area (they encode the frozen behavior).
3. Run the research test baseline before and after changes:
   `python -m pytest scripts/embedding_research/tests/ -x -q`
   (must pass before submitting).
4. Follow repo Python conventions for the research tree (ruff format/check on the research package).

## Working-tree cautions

- The `scripts/embedding_research/` subtree may carry uncommitted changes from an in-flight feature. **Do not stage, revert, or overwrite unrelated working-tree changes** in that subtree; read the current state, don't assume it matches git HEAD.
- Never treat `nomarr/` or `frontend/` paths as in-scope from here.

## Stream/head publication path — current state (characterized 2026-09-04, pre digest-named rewrite)

Verified in the working tree at characterization time (read-only). The executor is about to rewrite this to a digest-named immutable layout; do NOT re-derive these facts from memory after that lands — re-read the files.

- **Naming is identity-encoded, not digest-named**: first artifact at `(song_id, backbone)` is the BARE canonical name; every re-publish is a monotonic `.{vN}` suffix. StreamStore: `patches/{sid}.{backbone}.npy`, then `.v2.npy`… (`_default_subdir="patches"`, `_suffix=".npy"`, store.py:437-441). HeadStreamStore: `heads/{sid}.{backbone}.npz`, then `.v2.npz`… (`_default_subdir="heads"`, `_suffix=".npz"`, store.py:636-640).
- **Version selection**: `_family_versions` (store.py:222-247; bare name == version 1; scans `scan_root` glob `*{suffix}` + registry row) → `_next_artifact_ref` (store.py:249-261) returns bare name when no prior bytes, else `{subdir}/{sid}.{backbone}.v{max+1}{suffix}`. Filename→identity parse: `parse_artifact_name` + `_VERSION_RE` (publication.py:51, 225-255) — song_id = first dot-free segment (12-hex digest). No digest-name parsing exists anywhere.
- **Durable primitive**: `durable_write` (publication.py:183-208) — write full payload to `os.open(tmp, O_WRONLY|O_CREAT|O_TRUNC, 0o644)`, `ops.fsync_file`, `ops.close_fd`, `ops.rename` (=`os.replace`), open dest dir `os.O_RDONLY`, `ops.fsync_dir`. Staging sibling: `staging_path_for` → `.staging/{final-name}.tmp` (publication.py:211-219). Syscalls route through `FileOps` (61-83) / `RecordingFileOps` (86-136) — the Phase-4 lifecycle-test seam (never monkeypatch).
- **Registry write happens AFTER bytes land** (publication.py:19-23). `StreamStore.publish` (store.py:457-520) validates 2-D float32 finite, `npy_bytes`, sha256, then `self.replace(record, status="pending")` = transactional delete-then-insert (`_register_impl`, store.py:163-180). `register_legacy` (store.py:522-586, insert-only, status="ready") has **zero production callers**. Promote to ready via `reconcile()` called from `embed.py:117` (`_record_embed_run`) and `infer_heads.py:179`. `verify(strict=True)` has no production callers (CLI wiring is a later plan).
- **Live writers**: embed phase (run.py:507-515 `_embed_phase` and run.py:1102-1114 `_run_embed` both call `common.embed.embed`) → `_embed_song_raw` (embed.py:34-95) publishes at **embed.py:94** `store.publish(sid, backbone_name, embeddings, run_id=run_id)` — no provenance kwargs (all defaults); skip = `store.has_ready(sid, backbone)` when `not force` (embed.py:63-64). common/embed.py no longer `np.save`s bare sidecars — **FINDINGS.md:383-385 is STALE on this point**. infer-heads phase (run.py:1117-1130) → `infer_heads_for_song` (infer_heads.py:87-160), which gathers the full backbone stream (`StreamStore.lookup`+full-range `batch_gather`, infer_heads.py:255-260) and publishes the suite at **infer_heads.py:147-159** (`head_store.publish`, `ALIGNMENT_VERSION="1"`/`FORMAT_VERSION="1"` at infer_heads.py:58/61).
- **Gather/integrity**: `StreamStore.batch_gather` (store.py:588-623) — ready-gated, SHA-256 + dtype/shape/finite checks, index range/duplicate validation. HeadStreamStore.batch_gather (store.py:667-705) concatenates per-head rows in canonical sorted head order.
- **Downstream bare-path readers** (silently break for any superseded `.v{N}` artifact): `config.patches_path` = `PATCHES_DIR/{sid}.{backbone}.npy` (config.py:107-109); read at common/segment.py:73, classify.py:77/132/476/881, strategy_global_pool/_embed.py:53, strategy_binned/_optimize.py:523.
- **Rewrite constraint**: tokens `register_legacy`, `_classify_rowless`, `_family_versions`, `_next_artifact_ref` are executable ONLY inside `streams/store.py` (tests/test_audit_forbidden_vocabulary.py:67-70 + allowlist 144-147). Moving/renaming/removing them must keep that audit test green.
- **No MaskRecord / audio-mask code** exists under scripts/embedding_research (case-insensitive `mask` hits are boolean dataframe masks in report/_base.py:158+, report/_binned.py:755, similarity.py:357+; prose in tests/test_audit_forbidden_vocabulary.py:305). Head-side "legacy" semantics live in db/_schema.py:622 `LEGACY_RUN_ID="legacy"` + db/head_phase.py — outside streams/.

## Key Findings: corpus/catalog manifest surfaces (Plan B P1-S5 reindex research, 2026-09-04)

**Corrected-grammar paths are design targets, NOT code.** `corpus/manifest.json`, `corpus/songs.json`,
`catalogs/current.json`, `catalogs/<id>/catalog.manifest.json`, `catalogs/<id>/catalog.duckdb` have ZERO
literal occurrences in production `.py` under `scripts/embedding_research/`. They appear only in
`artifacts/designs/pending/DD-frozen-observation-corrective-pass.md` (lines ~272-293),
`artifacts/designs/parts/frozen-observation-corrective-pass/CONTRACTS.md` (:34-35, :68), and pending Plan B
`TASK-frozen-observation-corrective-pass-B-filesystem-observations.md` (P1-S5). Implementers must NOT assume
a writer/reader exists — the design describes a future state.

**What exists today (authoritative surfaces):**
- Corpus = DuckDB `songs` table (`db/_schema.py:93-100`), written by `strategy_meta.ingest`
  (`strategy_meta.py:39-74`, via `db/songs.py::upsert_song` :10-22); embed also lazily upserts
  (`common/embed.py:65-75`). In-memory corpus identity = `MatchingCorpusManifest`
  (`corpus.py:56-109`; built in `run.py:_build_backbone_manifests` :657-697). No corpus dir on disk.
- Catalog = durable COMPACT FILESYSTEM segmentation-catalog snapshots (NOT DuckDB tables in
  `research.duckdb`): one pass writes `catalogs/.staging-<run-id>/catalog.duckdb` which is then
  durably published to `catalogs/<catalog-id>/catalog.duckdb` + `catalog.manifest.json` with
  `catalogs/current.json` selecting the current snapshot. The five compact tables
  (`catalog_metadata`/`seg_config`/`catalog_song`/`seg_meta`/`run_provenance`) have their
  DDL/connection home and the publish/open lifecycle in `catalog_storage.py`
  (`publish_catalog_snapshot` ~:979, `open_current_catalog` ~:1100); the producer
  `catalog.py::build_segmentation_catalog` (`catalog.py:768`) writes only the staging snapshot
  through `con`. Exact searchable membership is reconstructed on read (structural ranges +
  sparse absorbed indices + song mask), never stored per-patch; configs are canonical-only (no
  `alias_of_config_id`). `research.duckdb` holds only registries/provenance — the old research
  `seg_config`/`seg_meta`/`seg_membership` tables were removed (P1-S12). `catalog-report` reads
  the compact snapshot and emits a single text file.
- Filesystem artifacts (digest grammar `streams/<sid>.<bb>.<64hex>.npy` + self-describing `.json` manifest
  sibling, `audio_masks/`, `observation_commits/`): `streams/records.py:503-516`,
  `streams/publication.py:283-306`, `streams/store.py:170-211` (manifest dict = full record row minus
  `created_at`/`updated_at` + `kind`/`schema_version`/`payload_sha256`/`byte_size`).
- WAL: no production `CHECKPOINT` on the `research.duckdb` path; the compact-catalog publish path runs a `CHECKPOINT` + clean close on the staging snapshot before `catalog.manifest.json` is written (`catalog_storage.py::publish_catalog_snapshot`, :1014). `FORCE CHECKPOINT` only in `tests/test_catalog_identity.py:316`.
  `.duckdb.wal`: `run.py:_reset_db` deletes db+wal (`run.py:427-449`), `cleanup.py::reset_db`
  (`cleanup.py:311-326`), `db/canary.py::detect_post_crash` treats a surviving `.wal` as post-crash
  (`db/canary.py:197-219`, wired at `run.py:1328-1332`). Connections close via
  `with duckdb.connect(str(DB_PATH)) as con:` (`run.py:1604`).
- Reconcile/verify (REAL today): `_RegistryStore.reconcile` (`streams/store.py:329-385`) and `.verify`
  (:387-411) are ROW-walks that validate registry rows against payload+manifest; their docstring
  explicitly defers rowless-orphan/stray and manifest-only reindex to "Phase-5" (:340-343).
  `ReindexReport` dataclass exists TYPE-ONLY at `streams/records.py:611-633` (zero producers).
  `catalog.py::_post_build_verify` :540-626; `cleanup.py` scopes (staging:159, views:203, dead:231,
  archival:274, reset_db:311, reset_cache_dirs:329, reset_analysis_run:354).
- CLI: exactly 8 phases + `cleanup`/`reset` maintenance (`run.py:893-902`, :907, :1577-1587); `verify` is
  only a `--verify`/`--strict` flag (:1546-1553, preflight :1308-1357). No `reindex`/`verify` subcommand.
- Root constants: `OUTPUT_ROOT = WORKSPACE / "scripts/outputs/embedding_research"` (`config.py:22`);
  `DB_PATH` with `RESEARCH_DB_PATH` env override (`config.py:33`). No `get_output_root()` helper — override
  seams are `StreamStore(con, output_root=...)` (`streams/store.py:146-148`) and
  `cfg["output_root"]`/`cfg["report_dir"]` (`run.py:1650-1651`).

## Plan B Frozen-Stream Layer — Test Conventions (streams/, tests/; research 2026-09-04)

Facts gathered for spec-first P1-S5 tests of `reindex(root, con)` / `reconcile_current_manifests(root, con)` (functions do NOT exist yet in scripts/embedding_research/ — confirmed by search; store.reconcile() docstring at streams/store.py:340-343 explicitly defers rowless-file scanning to "the Phase-5 filesystem-authoritative reconcile/reindex").

- **DuckDB con**: in-memory `duckdb.connect(":memory:")` + `ensure_schema(c)` — shared fixture in tests/conftest.py:16-22 OR identical local shadow in each test file (test_db.py:37-43, test_stream_store.py:65-70, test_stream_digest_spec.py:45-50, test_stream_cpu_boundary.py:58-63, test_infer_heads.py:33-38, test_head_suite_spec.py:49-54, test_stream_write_proxy.py:45-50). test_stream_publication.py / test_embed.py / test_observation_masks.py rely on the conftest con.
- **Store construction**: `StreamStore(con, output_root=tmp_path)` — con positional, output_root keyword-only (store.py:146-148; default is real OUTPUT_ROOT, must be overridden). Canonical ready-tree seeder = test_stream_cpu_boundary.py:79-95 `_seed_readables` (publish → reconcile → lookup status 'ready').
- **Pending→ready**: publish()/HeadStreamStore.publish() register status='pending' (store.py:448-512, 984-1102); only reconcile() promotes (store.py:356-357). Head/stream registry rows live in stream_registry + head_stream_registry; NO table exists for masks/observation commits — observation groups are filesystem-only (marker + stream + mask verify via observation_group_ready(), store.py:764-806).
- **Dirs under output_root**: streams/, heads/, audio_masks/, observation_commits/, plus .staging for tmp. Grammar `<subdir>/<sid>.<bb>.<64hex>.npy|.npz` + `.json` manifest sibling (manifest ref = artifact_ref[:-4]+".json" via payload_to_manifest_ref).
- **nomarr.components.ml is NOT importable** (fresh subprocess: ModuleNotFoundError psutil; essentia/onnxruntime/torch NOT installed). Stub pattern: parent packages as bare `ModuleType` in sys.modules, then the fake leaf module (test_observation_masks.py:172-222, test_embed.py:234-262); real ml_preprocess_comp.py loads standalone via importlib.util.spec_from_file_location (top-level essentia-free) — test_observation_masks.py:75-88.
- **CPU sentinels**: raising sentinel monkeypatched onto config.discover_audio (always attachable) + onnxruntime.InferenceSession/torch.cuda.is_available (guarded try/except) — test_stream_cpu_boundary.py:98-135; assert workload completes AND zero calls (172-193).
- **Markers/invocation**: only `unit` used in this tree (registered pyproject.toml:97); conftest pytest_configure adds legacy_scaled/sigkill_bookkeeping/blocklayer_durability. addopts -v --strict-markers --tb=short. Run: `python -m pytest scripts/embedding_research/tests/ -x -q` from repo root.
- **Import style**: absolute `from scripts.embedding_research.<pkg>.<mod> import ...`; never sys.path hacks; subprocess guard tests set PYTHONPATH=str(repo root) (test_stream_cpu_boundary.py:239-247).

## Compact-catalog CPU-only reads — searchable-membership & mask resolution map (research 2026-09-05)

For any CPU-only derived read over compact snapshot segments (e.g. head analysis gathering head-stream rows over exact searchable indices), the membership formula is `M_g = structural[start_idx, end_idx) − absorbed_indices − {mask[i] == 0}`, reconstructed — never read from the inclusive range.

- **Canonical reconstructor:** `helpers/segmentation.py::reconstruct_searchable_indices(meta, mask, patch_count) -> np.ndarray` (L178-211). `meta` is duck-typed, needs `.start_idx` (inclusive), `.end_idx` (EXCLUSIVE), `.absorbed_indices` (iterable of ints). `mask` = whole-song `uint8` (1=searchable, 0=silent) or `None` (rows beyond a shorter mask count searchable). Returns a SORTED int ndarray. Build-time `StructuralSegment` (L61-76): `seg_id/start_idx/end_idx/absorbed_indices`.
- **Call sites of reconstruct (non-test, active):** producer `catalog.py:706` inside `_build_and_persist_song`; `common/head_analysis.py:494` (aliased `_reconstruct_mg`) inside `_collect_segment_membership` L421 / `run_shared_ptc_head_pooling`. search_views.py and common/catalog_analysis.py do NOT import it.
- **How silence exclusion is ACTUALLY achieved in derived reads:**
  * *Producer (catalog.py)* `_build_and_persist_song` L706 reconstructs with the real mask from a duck-typed `mask_store.load(song_id) -> uint8[P] | None` (`_load_song_mask` L458, fails open on None). `run.py::_run_catalog` L1179-1181 passes `mask_store=None` ("None == no silence at this research layer") — so real runs persist NO silence exclusion.
  * Silence + outlier exclusion is ENCODED AT BUILD TIME into `seg_meta` columns: `searchable_count` = `|M_g|`; `search_medoid_source_patch_idx` = observed medoid chosen OVER the reconstructed searchable set only (`select_observed_medoid_source_index`, catalog.py:568; None when empty/no finite-nonzero); `searchable_weight` = `searchable_count / total_searchable` (catalog.py:565).
  * *search_views.py* `materialize_search_view` L295 never touches a mask: `_collect_rows` L175-190 takes row addresses ONLY from `seg_meta.search_medoid_source_patch_idx` (NULL rows dropped); `_gather_vectors` L193 gathers via `StreamStore.batch_gather` by that index; `_row_weights` L216-251 uses `seg_meta.searchable_weight` (finite-positive enforced).
  * *common/catalog_analysis.py* `materialize_corpus_view` L256 delegates to `sv.materialize_search_view`; `candidate_weights_from_catalog` L227-247 re-reads `seg_meta.searchable_weight` per canonical row (the analysis weight seam).
  * *common/head_analysis.py* `run_shared_ptc_head_pooling` L442 IS the CPU-only reconstruction path: `_collect_segment_membership` L421 yields `(seg_id, searchable_indices, |M_g|)` per segment; `mask = mask_store.load(song) if mask_store is not None else None` L552; `mask_store: Any = None` param documented "optional injected per-song silence-mask provider (tests only)". Production `run.py::_run_head_analysis` L1316 omits it → active head-analysis path does NO silence exclusion; tests inject `_SilenceStore`.
- **Real masks DO exist on disk (audio phase, P1-S3):** `common/embed.py` L111-117 derives via `streams/masks.py::derive_audio_mask(audio, backbone, stream_record, *, audio_fingerprint) -> MaskPayload` (L209) then `StreamStore.publish_observation_group` (store.py:647) writes content-addressed `audio_masks/<sid>.<bb>.<sha256>.npy` + `.json` manifest and `observation_commits/<sid>.<bb>.<sha>.json` markers (doc carries `mask_ref`/`stream_ref`/`alignment_token` = `stream_ref:mask_ref`). `MaskPayload` (masks.py:163): `song_id/backbone/patch_count/mask(uint8[P], values 0|1, P == stream patch_count)/.../mask_semantics_version="1"`. `MaskRecord` = metadata only (records.py:522+). **No public mask-array loader method exists** on the store — surface is `publish_mask`/`_mask_payload_ok` (np.load verify)/`observation_group_ready`/`read_committed_mask_audio_fingerprint`; newest-commit walk is internal `_commit_documents` store.py:721. `catalog_song.mask_digest` = sha256 of build-time mask bytes, or literal `"no-mask"`. A new CPU-only mask-backed reader must resolve `mask_ref` from the newest commit doc itself and `np.load` the `.npy`.
- **Reader records/fields** (catalog.py): `CompactConfigRecord` L1124 `config_id/backbone/bin_mode/threshold_configured/threshold_effective/threshold_semantics/outlier_window/strategy_version/canonical_config_hash/run_id`; `CompactSegRecord` L1151 `config_id/song_id/seg_id/start_idx/end_idx/absorbed_indices(tuple)/absorbed_count/searchable_count/search_medoid_source_patch_idx(int|None)/searchable_weight/structural_identity/provenance`; `CatalogSongRecord` L255 `config_id/song_id/stream_digest/mask_digest/patch_count/total_searchable_count/exact_leaf/search_leaf/encoder_version/params_id/status`. Reader functions: `compact_configs_by_backbone(con, backbone)` L1202, `compact_config_by_id(con, config_id)` L1216, `compact_segments_by_config_song(con, config_id, song_id)` L1225 (ordered by seg_id), `compact_catalog_songs_by_config(con, config_id)` L1234, `compact_catalog_song(con, config_id, song_id)` L1243. All accept a compact `con` (`handle.con`).
- **Schema/connection home** (catalog_storage.py): tables `CATALOG_TABLES` L112 = `catalog_metadata, seg_config, catalog_song, seg_meta, run_provenance`; column order `SEG_CONFIG_COLS` L133 / `CATALOG_SONG_COLS` L146 / `SEG_META_COLS` L160. Open seams: `open_snapshot_file(path, *, read_only=False) -> CatalogHandle` L426, `open_current_catalog(root, *, verify=True) -> CatalogHandle` L1104; `CatalogHandle(catalog_id, root, con)` L372.
- **Correction to stale note above:** the older claim "No MaskRecord/audio-mask code exists under scripts/embedding_research" predates P1-S3; the observation-mask layer (audio_masks/ + observation_commits/ + records.MaskRecord + masks.py producer) is real and present.
