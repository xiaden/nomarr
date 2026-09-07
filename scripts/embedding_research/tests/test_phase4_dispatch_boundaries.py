"""Plan E P4-S1/S2 — explicit-phase CLI dispatch + CPU/inference boundaries.

DD "CLI and provenance contract" (lines 272-289): the CLI exposes EXACTLY eight
phases — ``ingest embed infer-heads catalog catalog-report analyze head-analysis
report`` — with ``cleanup``/``reset`` as explicit SEPARATE maintenance commands.
Only the first three phases may discover audio / load models / create ML
sessions / run ONNX.  The five derived phases are CPU-only: each derived runner
body may import/reference ONLY ``DERIVED_ALLOWED_IMPORT_ROOTS`` modules and must
never contain ``DERIVED_FORBIDDEN_TOKENS``.  Stratification is catalog input
(config/corpus generation inside the ``catalog`` phase), NOT a phase.  Retired
legacy names (``stratify segment classify head``) are ordinary unknown commands —
they follow the exact same rejection path as any unrecognized verb, with no named
alias or compatibility rejection path.

This file is the structural (phase-call-graph) proof the Phase-4 dispatch
comments in ``run.py`` point to, plus CLI-level dispatch tests and a call-level
sentinel smoke that drives a real derived phase through the dispatch path.
"""

from __future__ import annotations

import ast
import types
from pathlib import Path

import pytest

from scripts.embedding_research import run as run_mod

_RUN_FILE = Path(run_mod.__file__).resolve()
_RUN_SOURCE = _RUN_FILE.read_text(encoding="utf-8")
_RUN_TREE = ast.parse(_RUN_SOURCE)


def _function_body(name: str) -> ast.FunctionDef:
    """Return the FunctionDef node for a module-level ``def name`` in run.py."""
    for node in _RUN_TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"no def {name} in {_RUN_FILE}")


def _research_relative_imports(body: ast.AST) -> list[str]:
    """Return research-relative dotted module paths imported anywhere in ``body``.

    Only ``scripts.embedding_research.*`` imports are considered; everything else
    (stdlib/third-party) is irrelevant to the CPU-only module-boundary proof.
    """
    import_prefix = "scripts.embedding_research."
    import_paths = [
        alias.name[len(import_prefix) :]
        for node in ast.walk(body)
        if isinstance(node, ast.Import)
        for alias in node.names
        if alias.name.startswith(import_prefix)
    ]
    from_paths = [
        (node.module or "")[len(import_prefix) :]
        for node in ast.walk(body)
        if isinstance(node, ast.ImportFrom)
        if (node.module or "").startswith(import_prefix)
    ]
    return import_paths + from_paths


def _allowed_research_path(path: str) -> bool:
    """True when a research-relative dotted import path is a CPU-only allowed root
    or a submodule thereof (segment-aware prefix match on DERIVED_ALLOWED_IMPORT_ROOTS)."""
    return any(path == root or path.startswith(root + ".") for root in run_mod.DERIVED_ALLOWED_IMPORT_ROOTS)


# --------------------------------------------------------------------------- #
# Exactly eight phases + separate maintenance; legacy names rejected            #
# --------------------------------------------------------------------------- #


def test_cli_exposes_exactly_eight_phases_in_order():
    assert run_mod.CLI_PHASES == (
        "ingest",
        "embed",
        "infer-heads",
        "catalog",
        "catalog-report",
        "analyze",
        "head-analysis",
        "report",
    )


def test_audio_are_first_three_derived_are_the_five():
    assert frozenset({"ingest", "embed", "infer-heads"}) == run_mod.AUDIO_PHASES
    assert frozenset(run_mod.CLI_PHASES) - run_mod.AUDIO_PHASES == run_mod.DERIVED_PHASES
    assert len(run_mod.AUDIO_PHASES) == 3
    assert len(run_mod.DERIVED_PHASES) == 5


def test_retired_names_are_unknown_commands_not_phases():
    # The retired names are not phases, runners, or maintenance commands, and the
    # legacy alias map / compatibility rejection path is gone entirely.
    for name in ("stratify", "segment", "classify", "head"):
        assert name not in run_mod.CLI_PHASES
        assert name not in run_mod.CLI_PHASE_RUNNERS
        assert name not in run_mod.MAINTENANCE_COMMANDS
    assert not hasattr(run_mod, "LEGACY_PHASE_ALIASES")


def test_cleanup_reset_are_maintenance_not_phase_runners():
    for maint in ("cleanup", "reset"):
        assert maint not in run_mod.CLI_PHASES
        assert maint not in run_mod.CLI_PHASE_RUNNERS
        assert run_mod._resolve_command(maint) == maint  # routed, not a phase


def test_cli_phase_runners_map_exactly_the_eight_phases():
    assert set(run_mod.CLI_PHASE_RUNNERS) == set(run_mod.CLI_PHASES)
    assert run_mod.CLI_PHASE_RUNNERS["head-analysis"].__name__ == "_run_head_analysis"
    assert run_mod.CLI_PHASE_RUNNERS["catalog"].__name__ == "_run_catalog"


@pytest.mark.parametrize("unknown", ["frobnicate", "stratify", "segment", "classify", "head"])
def test_resolve_command_rejects_unknown_command(caplog, unknown):
    # Retired names (stratify/segment/classify/head) are ordinary unknown commands:
    # identical exit code and ``unknown command`` message to any other unrecognized
    # verb — no named alias or compatibility rejection path special-cases them.
    with pytest.raises(SystemExit) as exc:
        run_mod._resolve_command(unknown)
    assert exc.value.code == 2
    msgs = [r.message for r in caplog.records]
    assert any("unknown command" in m for m in msgs)


@pytest.mark.parametrize("phase", run_mod.CLI_PHASES)
def test_resolve_command_accepts_each_phase(phase):
    assert run_mod._resolve_command(phase) == phase


def test_stratification_is_catalog_input_not_a_phase():
    assert "stratify" not in run_mod.CLI_PHASES
    body = ast.get_source_segment(_RUN_SOURCE, _function_body("_run_catalog"))
    # catalog performs corpus/config selection (stratification) as catalog input —
    # it reaches the canonical stratify/budget selection helper and builds configs.
    assert ("run_stratify" in body) or ("_catalog_seg_configs" in body) or ("_catalog_corpus_song_ids" in body)


# --------------------------------------------------------------------------- #
# Structural CPU-only proof for the five derived runners                       #
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("phase", sorted(run_mod.DERIVED_PHASES))
def test_derived_runner_imports_only_cpu_roots(phase):
    runner_name = run_mod.CLI_PHASE_RUNNERS[phase].__name__
    body = _function_body(runner_name)
    imports = _research_relative_imports(body)
    assert imports, f"derived runner {runner_name} must import from CPU-only roots"
    bad = [p for p in imports if not _allowed_research_path(p)]
    assert not bad, f"derived runner {runner_name} reaches non-CPU modules: {bad}"


def _referenced_identifier_components(body: ast.AST) -> set[str]:
    """Every identifier component referenced in ``body`` (Names + Attribute-chain parts).

    Substring-style forbidden-token checks false-positive on identifiers that embed a
    forbidden surface name (e.g. ``head_pooling``), so we match forbidden surfaces at
    whole-identifier granularity instead.
    """
    comps: set[str] = set()
    for node in ast.walk(body):
        if isinstance(node, ast.Name):
            comps.add(node.id)
        elif isinstance(node, ast.Attribute):
            cur: ast.AST | None = node
            while isinstance(cur, ast.Attribute):
                comps.add(cur.attr)
                cur = cur.value
            if isinstance(cur, ast.Name):
                comps.add(cur.id)
    return comps


@pytest.mark.parametrize("phase", sorted(run_mod.DERIVED_PHASES))
def test_derived_runner_has_no_forbidden_tokens(phase):
    runner_name = run_mod.CLI_PHASE_RUNNERS[phase].__name__
    referenced = _referenced_identifier_components(_function_body(runner_name))
    hits = sorted(t for t in run_mod.DERIVED_FORBIDDEN_TOKENS if t in referenced)
    assert not hits, f"derived runner {runner_name} references forbidden surfaces: {hits}"


def test_head_analysis_runner_uses_canonical_cpu_runner_not_legacy_classify():
    """head-analysis must invoke common.head_analysis.run_shared_catalog_head_analysis and
    never the classify.py LEGACY live-ONNX runner."""
    runner_name = run_mod.CLI_PHASE_RUNNERS["head-analysis"].__name__
    body = _function_body(runner_name)
    imports = _research_relative_imports(body)
    # imports the canonical CPU shared-head runner
    assert any(p == "common.head_analysis" or p.startswith("common.head_analysis.") for p in imports)
    src = ast.get_source_segment(_RUN_SOURCE, body) or ""
    assert "run_shared_catalog_head_analysis" in src
    # ...and never the classify.py / head_pooling.py LEGACY surfaces.  Imports are
    # already asserted above to come only from common.head_analysis; the identifier
    # check below guards against any inline reference to the LEGACY symbols.
    referenced = _referenced_identifier_components(body)
    assert "classify" not in referenced
    assert "head_pooling" not in referenced


# --------------------------------------------------------------------------- #
# CLI dispatch smoke: drive real derived phases through the dispatch path       #
# --------------------------------------------------------------------------- #


def _unit(rng, n: int, d: int) -> object:
    import numpy as np

    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _publish_committed_stream(store, song_id: str, matrix, *, run_id: str, backbone: str = "effnet"):
    """Publish a stream AND its complete committed observation group (all-searchable mask).

    P1-S3: the store-backed current-stream resolver resolves ONLY complete committed
    groups, so every helper that builds a catalog does so from the complete committed
    groups published here, resolving the mask through the two-key store-backed seam
    ``make_current_mask_resolver(store)`` (stream via ``make_current_stream_resolver``).
    """
    import hashlib as _hashlib

    import numpy as _np

    from scripts.embedding_research.streams.masks import MaskPayload

    matrix = _np.ascontiguousarray(matrix, dtype=_np.float32)
    record = store.publish(song_id, backbone, matrix, run_id=run_id)
    store.publish_observation_group(
        record,
        MaskPayload(
            song_id=song_id,
            backbone=backbone,
            patch_count=matrix.shape[0],
            mask=_np.ones(matrix.shape[0], dtype=_np.uint8),
            params_id="0" * 64,
            audio_content_sha256=_hashlib.sha256(b"fixture-audio-content").hexdigest(),
            run_id=run_id,
            created_at=1,
        ),
    )
    return record


def _seed_compact_catalog(con, out) -> None:
    """Register songs, publish ready effnet streams, build a VERIFIED COMPACT catalog.

    P1-S11 dedicated analyze-dispatch setup: writes the compact snapshot to
    ``out/catalogs/.staging-run-cat-an/catalog.duckdb`` (never the research DB) and leaves
    NO live snapshot handle open, so ``_run_single_phase``'s own read-only open is the sole
    handle.  Kept separate from the shared ``_seed_cataloged`` helper (which the report/
    head dispatch fixtures still migrate in P1-S13) so this step touches only what the
    analyze dispatch test needs.
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.streams import make_current_mask_resolver, make_current_stream_resolver
    from scripts.embedding_research.streams.store import StreamStore

    songs = ("s1", "s2", "s3", "s4")
    artists = {"s1": "A", "s2": "A", "s3": "B", "s4": "B"}
    for song in songs:
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", artists[song]),
        )
    store = StreamStore(con, output_root=str(out))
    rng = __import__("numpy").random.default_rng(3)
    for song in songs:
        _publish_committed_stream(store, song, _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(
        make_current_stream_resolver(store),
        make_current_mask_resolver(store),
        [
            catalog.SegConfigInput(
                backbone="effnet",
                bin_mode="temporal_global",
                threshold_configured=0.7,
                threshold_effective=0.7,
            )
        ],
        list(songs),
        output_root=str(out),
        run_id="run-cat-an",
        verify=True,
    )
    assert rep.verify_ok is True
    # Durably publish the staged catalog so current.json is authoritative for derived phases.
    from scripts.embedding_research import catalog_storage as _cs

    staging_dir = Path(out) / "catalogs" / ".staging-run-cat-an"
    dcon = __import__("duckdb").connect(str(staging_dir / _cs.CATALOG_DB_FILE), read_only=True)
    try:
        _manifest = _cs.derive_catalog_manifest(dcon)
    finally:
        dcon.close()
    _ph = _cs.publish_catalog_snapshot(staging_dir, manifest=_manifest)
    _ph.close()


def _seed_analyze_rows(con, store, *, run_id="run-an-seed"):
    from scripts.embedding_research.common import catalog_analysis as ca
    from scripts.embedding_research.db import analyze_scope

    cfg = ca.CatalogAnalysisConfig(
        run_id=run_id,
        backbone="effnet",
        song_ids=("s1", "s2", "s3", "s4"),
        artists={"s1": "A", "s2": "A", "s3": "B", "s4": "B"},
    )
    result = ca.run_catalog_analysis(store, con, cfg)
    assert result.finite is True
    analyze_scope.write_catalog_analyze_rows(con, run_id=run_id, result=result)


def _install_audio_sentinels(monkeypatch) -> dict[str, int]:
    """Raising sentinels at the real audio/ML call sites (CPU-only proof)."""
    from scripts.embedding_research.config import discover_audio as _config_discover_audio

    events: list[str] = []
    installed: dict[str, list[str]] = {}

    def _make(name):
        def _raise(*_a, **_k):
            events.append(name)
            raise AssertionError(f"forbidden call during a CPU-only derived phase: {name}")

        return _raise

    sentinel_name = "config.discover_audio"
    monkeypatch.setattr(_config_discover_audio.__module__ + ".discover_audio", _make(sentinel_name))
    installed[sentinel_name] = events
    try:  # pragma: no cover - env dependent
        import onnxruntime  # type: ignore[import-not-found]

        monkeypatch.setattr(onnxruntime, "InferenceSession", _make("onnxruntime.InferenceSession"))
        installed["onnxruntime.InferenceSession"] = events
    except Exception:  # pragma: no cover - absent platform
        pass
    try:  # pragma: no cover - env dependent
        import torch  # type: ignore[import-not-found]

        monkeypatch.setattr(torch.cuda, "is_available", _make("torch.cuda.is_available"))
        installed["torch.cuda.is_available"] = events
    except Exception:  # pragma: no cover - absent platform
        pass
    return dict(installed.items())


def _assert_zero_sentinel_calls(events_by_name: dict[str, list[str]]) -> None:
    assert events_by_name, "at least config.discover_audio must be guarded"
    calls = {name: len(ev) for name, ev in events_by_name.items()}
    assert all(c == 0 for c in calls.values()), calls


def _base_cfg(out) -> dict:
    return {
        "verify": False,
        "strict": False,
        "retained": False,
        "force": False,
        "k": 10,
        "backbones": ["effnet"],
        "heads": None,
        "output_root": str(out),
        "report_dir": str(out / "report"),
        "run_id": None,
        "config_hash": "testcfg",
    }


def test_catalog_report_dispatch_smoke_zero_forbidden_calls(con, tmp_path, monkeypatch):
    """catalog-report driven through the real dispatch completes, no audio/ML calls."""
    _seed_compact_catalog(con, tmp_path / "out")
    sentinels = _install_audio_sentinels(monkeypatch)
    cfg = _base_cfg(tmp_path / "out")

    run_mod._run_single_phase(con, "catalog-report", cfg)

    row = con.execute(
        "SELECT phase, status, output_artifact_hashes FROM run_provenance WHERE phase='catalog-report' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert row and row[0] == "catalog-report" and row[1] == "completed"
    assert "catalog_report.txt" in (row[2] or "")
    _assert_zero_sentinel_calls(sentinels)


def test_analyze_dispatch_smoke_zero_forbidden_calls(con, tmp_path, monkeypatch):
    """analyze driven through the real dispatch completes via bounded CPU scoring."""
    _seed_compact_catalog(con, tmp_path / "out")
    sentinels = _install_audio_sentinels(monkeypatch)
    cfg = _base_cfg(tmp_path / "out")

    run_mod._run_single_phase(con, "analyze", cfg)

    # analyze self-records its run-scoped metrics (its own run_id), no forbidden call.
    # Every analyze_metrics row is run-scoped (no legacy partition), so presence is the assertion.
    n = con.execute("SELECT count(*) FROM analyze_metrics").fetchone()[0]
    assert n >= 1
    _assert_zero_sentinel_calls(sentinels)


def test_head_analysis_dispatch_invokes_canonical_runner_not_classify(con, tmp_path, monkeypatch):
    """head-analysis dispatch wiring calls common.head_analysis.run_shared_catalog_head_analysis
    (the canonical CPU runner) — never the classify.py LEGACY runner."""
    from scripts.embedding_research.common import head_analysis as _head_analysis_mod

    _seed_compact_catalog(con, tmp_path / "out")
    calls: list[str] = []

    def _fake_manifest(*_a, **_k):
        calls.append("run_shared_catalog_head_analysis")
        return types.SimpleNamespace(
            done=0,
            skipped=0,
            errors=0,
            finite=True,
            song_ids=(),
            config_ids=(),
            run_id="x",
            results=[],
        )

    monkeypatch.setattr(_head_analysis_mod, "run_shared_catalog_head_analysis", _fake_manifest)
    cfg = _base_cfg(tmp_path / "out")

    run_mod._run_single_phase(con, "head-analysis", cfg)

    assert calls == ["run_shared_catalog_head_analysis"], "head-analysis must invoke the canonical CPU runner"


# ---------------------------------------------------------------------------
# P1-S5: the real ``catalog`` runner must wire committed mask/stream resolvers
# ---------------------------------------------------------------------------


def test_run_catalog_wires_a_stream_resolver_not_none(con):
    """P1-S5 spec: ``_run_catalog`` hands ``build_segmentation_catalog`` resolver expressions,
    never a literal ``None`` stream/mask loader.  Expected RED until P1-S5 replaces the
    fail-open ``None == no silence`` research seam.
    """
    import ast
    import inspect

    _ = con
    src = inspect.getsource(run_mod._run_catalog)
    call = next(
        n
        for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "build_segmentation_catalog"
    )
    assert len(call.args) >= 2
    # Both the stream and mask loaders are resolver expressions (not None), so silence is
    # never silently dropped at the run.py catalog entry point.
    for pos in (0, 1):
        arg = call.args[pos]
        is_literal_none = isinstance(arg, ast.Constant) and arg.value is None
        assert not is_literal_none, f"build_segmentation_catalog argument {pos} must not be a literal None"


def test_run_catalog_constructs_a_committed_mask_resolver():
    """P1-S5 spec: the real catalog runner builds the mask loader from StreamStore, so the
    run.py catalog path consumes the committed mask (silent patches excluded), matching FS
    reindex readiness.  Expected RED until P1-S5 wires ``make_current_mask_resolver``.
    """
    import inspect

    from scripts.embedding_research.streams.store import make_current_mask_resolver  # red until P1-S5

    src = inspect.getsource(run_mod._run_catalog)
    assert "make_current_mask_resolver" in src, "_run_catalog must construct the current mask resolver"
    _ = make_current_mask_resolver


# --------------------------------------------------------------------------- #
# P1-S5: the real run.py catalog path excludes deliberately silent patches      #
# --------------------------------------------------------------------------- #


def _publish_committed_stream_with_mask(store, song_id: str, matrix, mask, *, run_id: str, backbone: str = "effnet"):
    """Publish a stream AND its complete committed observation group with an EXPLICIT mask.

    The committed mask (``uint8[P]``, 0 == silent) is what the store-backed committed-mask
    resolver the run.py catalog path builds will serve ``build_segmentation_catalog``, so a
    deliberately silent region in *mask* is excluded from the durable catalog exactly as the
    FS-reindex readiness predicate resolves it.
    """
    import hashlib as _hashlib

    import numpy as _np

    from scripts.embedding_research.streams.masks import MaskPayload

    matrix = _np.ascontiguousarray(matrix, dtype=_np.float32)
    mask = _np.asarray(mask, dtype=_np.uint8)
    record = store.publish(song_id, backbone, matrix, run_id=run_id)
    store.publish_observation_group(
        record,
        MaskPayload(
            song_id=song_id,
            backbone=backbone,
            patch_count=int(matrix.shape[0]),
            mask=mask,
            params_id="0" * 64,
            audio_content_sha256=_hashlib.sha256(b"fixture-audio-content").hexdigest(),
            run_id=run_id,
            created_at=1,
        ),
    )
    return record


def _unit_constant_rows(n: int, dim: int = 4) -> object:
    """n identical unit rows (all ``+x``): zero pair distance => no segmentation splits and no
    absorbed geometric outliers, so every non-silent patch belongs to exactly one segment."""
    import numpy as np

    rows = np.zeros((n, dim), dtype=np.float32)
    rows[:, 0] = 1.0
    return rows


def test_run_catalog_path_excludes_deliberately_silent_patches(con, tmp_path):
    """P1-S5 (authoritative): the REAL run.py catalog function path durably publishes a compact
    catalog whose searchable membership ``M_g``, observed source-index medoid, searchable totals
    and weights all EXCLUDE a deliberately silent region of a committed stream, while a fully
    silent song stays metadata-only.  Drives ``run_mod._run_catalog`` (via the CLI dispatch
    single-phase wrapper) with complete committed observation groups — never a re-implementation
    of the build.
    """
    import numpy as np

    from scripts.embedding_research import catalog
    from scripts.embedding_research import catalog_storage as _cs
    from scripts.embedding_research.helpers.segmentation import (
        reconstruct_searchable_indices,
        select_observed_medoid_source_index,
    )
    from scripts.embedding_research.streams.store import StreamStore

    out_root = tmp_path / "out"
    # Song s1: 8 identical patches with a deliberately silent region at source indices {2, 6}.
    # Song s2: fully silent (all patches masked) => zero-searchable metadata-only retention.
    silent = {2, 6}
    committed_masks = {
        "s1": np.array([1, 1, 0, 1, 1, 1, 0, 1], dtype=np.uint8),
        "s2": np.zeros(8, dtype=np.uint8),
    }
    for song in ("s1", "s2"):
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", "A"),
        )
    store = StreamStore(con, output_root=str(out_root))
    mat = _unit_constant_rows(8)
    for song in ("s1", "s2"):
        _publish_committed_stream_with_mask(store, song, mat, committed_masks[song], run_id="run-embed")
    store.reconcile()

    cfg = {
        "output_root": out_root,
        "verify": False,
        "strict": False,
        "retained": False,
        "force": False,
        "backbones": ["effnet"],
        "catalog_bin_modes": ["temporal_global"],
        "catalog_thresholds": [1.0],
    }
    # Drive the ACTUAL run.py catalog command path (preflight thin gate + _run_catalog wiring +
    # durable snapshot publication).
    run_mod._run_single_phase(con, "catalog", cfg)

    handle = _cs.open_current_catalog(out_root, verify=True)
    try:
        configs = catalog.compact_configs_by_backbone(handle.con, "effnet")
        assert len(configs) == 1
        config_id = configs[0].config_id

        songs = {s.song_id: s for s in catalog.compact_catalog_songs_by_config(handle.con, config_id)}
        # s1 searchable TOTAL excludes the deliberately silent patches (8 - 2 = 6).
        assert int(songs["s1"].total_searchable_count) == 6
        # s2 fully silent => metadata-only, zero searchable.
        assert int(songs["s2"].total_searchable_count) == 0
        assert songs["s2"].status == "metadata_only"

        # s1 exactly one segment (identical rows never split) whose exact searchable membership
        # M_g = structural range minus silence excludes every silent source index.
        segs = catalog.compact_segments_by_config_song(handle.con, config_id, "s1")
        assert len(segs) == 1
        seg = segs[0]
        mask = committed_masks["s1"]
        searchable = np.asarray(reconstruct_searchable_indices(seg, mask, patch_count=8), dtype=int)
        assert silent.isdisjoint({int(i) for i in searchable})
        assert {int(i) for i in searchable} == {0, 1, 3, 4, 5, 7}
        assert int(seg.searchable_count) == len(searchable) == 6

        # Medoid selection happens over the reconstructed searchable set: never a silent index.
        assert seg.search_medoid_source_patch_idx is not None
        assert seg.search_medoid_source_patch_idx not in silent
        unit = catalog._l2_normalize_rows(mat)
        recomputed_medoid, _centrality = select_observed_medoid_source_index(unit, list(searchable))
        assert seg.search_medoid_source_patch_idx == recomputed_medoid
        assert 0 <= recomputed_medoid < 8

        # Weight = this segment's searchable mass over s1's whole-song searchable total (6/6).
        assert float(seg.searchable_weight) == pytest.approx(1.0)

        # Fully silent s2 produced NO seg_meta rows (metadata-only retention).
        assert catalog.compact_segments_by_config_song(handle.con, config_id, "s2") == ()
    finally:
        handle.close()


def test_catalog_preflight_refuses_incomplete_committed_group_under_strict(con, tmp_path):
    """P1-S5: ``_preflight_derived_phase`` refuses (--strict) a requested catalog input whose
    committed observation group is incomplete (stream published but NO committed mask/commit
    marker) BEFORE any catalog construction treats it as valid."""

    from scripts.embedding_research.streams.store import StreamStore

    out_root = tmp_path / "out"
    con.execute(
        "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
        ("s1", "/audio/s1.mp3", "A"),
    )
    store = StreamStore(con, output_root=str(out_root))
    # Publish ONLY the stream — no committed mask / commit marker => INCOMPLETE committed group.
    store.publish("s1", "effnet", _unit_constant_rows(4), run_id="run-embed")

    cfg = {
        "output_root": out_root,
        "verify": True,
        "strict": True,
        "retained": False,
        "force": False,
        "backbones": ["effnet"],
    }
    with pytest.raises(run_mod._MissingArtifactError) as exc:
        run_mod._run_single_phase(con, "catalog", cfg)
    assert "incomplete" in str(exc.value) or "lack a complete committed observation group" in str(exc.value)
