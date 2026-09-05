"""Plan E P4-S1/S2 — explicit-phase CLI dispatch + CPU/inference boundaries.

DD "CLI and provenance contract" (lines 272-289): the CLI exposes EXACTLY eight
phases — ``ingest embed infer-heads catalog catalog-report analyze head-analysis
report`` — with ``cleanup``/``reset`` as explicit SEPARATE maintenance commands.
Only the first three phases may discover audio / load models / create ML
sessions / run ONNX.  The five derived phases are CPU-only: each derived runner
body may import/reference ONLY ``DERIVED_ALLOWED_IMPORT_ROOTS`` modules and must
never contain ``DERIVED_FORBIDDEN_TOKENS``.  Stratification is catalog input
(config/corpus generation inside the ``catalog`` phase), NOT a phase.  Retired
legacy names (``stratify segment classify head``) are rejected loudly, never
silently aliased.

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


def test_legacy_aliases_are_never_silent_phase_aliases():
    # The retired names are a disjoint, explicit reject set — never a phase.
    assert frozenset({"stratify", "segment", "classify", "head"}) == run_mod.LEGACY_PHASE_ALIASES
    assert run_mod.LEGACY_PHASE_ALIASES.isdisjoint(run_mod.CLI_PHASES)
    assert run_mod.LEGACY_PHASE_ALIASES.isdisjoint(run_mod.CLI_PHASE_RUNNERS)


def test_cleanup_reset_are_maintenance_not_phase_runners():
    for maint in ("cleanup", "reset"):
        assert maint not in run_mod.CLI_PHASES
        assert maint not in run_mod.CLI_PHASE_RUNNERS
        assert run_mod._resolve_command(maint) == maint  # routed, not a phase


def test_cli_phase_runners_map_exactly_the_eight_phases():
    assert set(run_mod.CLI_PHASE_RUNNERS) == set(run_mod.CLI_PHASES)
    assert run_mod.CLI_PHASE_RUNNERS["head-analysis"].__name__ == "_run_head_analysis"
    assert run_mod.CLI_PHASE_RUNNERS["catalog"].__name__ == "_run_catalog"


@pytest.mark.parametrize("legacy", ["stratify", "segment", "classify", "head"])
def test_resolve_command_rejects_each_legacy_alias(caplog, legacy):
    with pytest.raises(SystemExit) as exc:
        run_mod._resolve_command(legacy)
    assert exc.value.code == 2
    msgs = [r.message for r in caplog.records]
    assert any("retired/legacy phase name" in m and "Valid phases" in m for m in msgs)
    assert any(all(p in m for p in ("ingest", "catalog", "head-analysis", "report")) for m in msgs)


def test_resolve_command_rejects_unknown_command(caplog):
    with pytest.raises(SystemExit) as exc:
        run_mod._resolve_command("frobnicate")
    assert exc.value.code == 2
    msgs = [r.message for r in caplog.records]
    assert any("unknown command" in m for m in msgs)


@pytest.mark.parametrize("phase", run_mod.CLI_PHASES)
def test_resolve_command_accepts_each_phase(phase):
    assert run_mod._resolve_command(phase) == phase


def test_stratification_is_catalog_input_not_a_phase():
    assert "stratify" not in run_mod.CLI_PHASES
    assert "stratify" in run_mod.LEGACY_PHASE_ALIASES
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
    from scripts.embedding_research.streams import make_current_stream_resolver
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
        store.publish(song, "effnet", _unit(rng, 10, 6), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(
        make_current_stream_resolver(store),
        None,
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
    n = con.execute("SELECT count(*) FROM analyze_metrics WHERE run_id <> 'legacy'").fetchone()[0]
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
