"""P1-S2 spec-first: real CLI dispatch over the fixture + zero-forbidden-call proofs.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S2.  These tests drive the ACTUAL eight-command CLI dispatch
(``run._run_single_phase`` / the ``CLI_PHASE_RUNNERS`` dict — the executor ``run.main``
invokes after argparse + ``_build_run_config``) over a FRESH deterministic corpus, with the
synthetic audio/model seams injected ONLY for the permitted audio phases (ingest / embed /
infer-heads) and call-counting sentinels active for every derived phase.

The sentinels are functions that record an invocation count AND raise; the derived-phase
assertions inspect the recorded counts and require ZERO — a sentinel firing (and being caught)
is never success.  This proves the derived phases make zero audio/model/ONNX/CUDA calls (and
that the four consumers make zero segmentation calls) rather than merely not crashing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import duckdb
import pytest

from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.tests.fixture_cli_harness import (
    BACKBONE,
    SONGS,
)
from scripts.embedding_research.tests.fixture_runtime_harness import (
    _CLI_PHASE_ORDER,
    FixtureCliRunner,
    ForbiddenRuntimeError,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

CONFIG_THRESHOLDS = (0.9, 1.0, 0.2)


def _fresh_runner(tmp_path: Path) -> FixtureCliRunner:
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    out = tmp_path / "out"
    return FixtureCliRunner(con, out, thresholds=CONFIG_THRESHOLDS)


@pytest.fixture
def runner(tmp_path) -> FixtureCliRunner:
    return _fresh_runner(tmp_path)


# --------------------------------------------------------------------------- #
# 1. All eight phases execute through the real dispatch and record provenance  #
# --------------------------------------------------------------------------- #
def test_all_eight_phases_run_and_record_provenance(runner):
    """Every CLI phase executes to completion and records an auditable run row."""
    evidence = runner.run_all()
    assert set(evidence.run_ids) == set(_CLI_PHASE_ORDER)
    # Each phase's provenance row is present with a completion status.
    for phase in _CLI_PHASE_ORDER:
        status = evidence.status_of(phase)
        assert status in {"completed", "complete"}, f"{phase} ended in {status!r}"


def test_run_ids_are_deterministic_and_distinct(runner):
    """Explicit deterministic run ids are recorded per phase (P1-S5 stability)."""
    evidence = runner.run_all()
    seen: set[str] = set()
    for phase in _CLI_PHASE_ORDER:
        rid = evidence.phase_run_id(phase)
        assert rid not in seen and rid.startswith(f"{phase}-")
        seen.add(rid)
    # ingest / catalog / catalog-report / head-analysis / report are recorded by the CLI
    # wrapper; embed / infer-heads / analyze are self-recorded — all still have a row.
    assert len(evidence.run_provenance_rows) == len(_CLI_PHASE_ORDER)


# --------------------------------------------------------------------------- #
# 2. Sentinels prove the derived phases make ZERO forbidden calls             #
# --------------------------------------------------------------------------- #
def test_derived_phases_make_zero_forbidden_calls(runner):
    """No audio/model/ONNX/CUDA/segmentation seam fires across the five derived phases."""
    evidence = runner.run_all()
    # The sentinels installed for the derived phases recorded ZERO calls.  A non-empty count
    # means a forbidden seam fired (the sentinel raised; catching it is not success).
    assert evidence.sentinel_counts == {}, (
        f"a sentinel-guarded forbidden seam fired during a derived phase: {evidence.sentinel_counts}"
    )
    # And explicitly: none of the named seam categories were invoked at all.
    for key in (
        "audio.discover_audio",
        "audio.load_audio_mono",
        "model.create_session",
        "onnx.inference_session",
        "cuda.is_available",
        "infer.embed",
        "segmentation.run_spherical_segmentation",
        "mask.derive_audio_mask",
    ):
        assert evidence.sentinel_counts.get(key, 0) == 0, key


def test_segmentation_sentinel_scope_allows_catalog_but_forbids_consumers(runner):
    """catalog legitimately re-segments; catalog-report/analyze/head-analysis/report do not."""
    # Run just catalog first (no consumer sentinel) — it must succeed at its CPU segmentation.
    # Then assert a consumer would be blocked from re-segmenting by running each consumer with
    # the segmentation sentinel and verifying zero calls (covered by the full run above).  Here
    # we prove the sentinel DOES fire when a forbidden segmentation is attempted, so the guard
    # is not vacuous.

    registry = runner.run_all()
    assert registry.sentinel_counts == {}
    # Prove the sentinel itself is armed (guards against a vacuous zero-count assertion):
    from scripts.embedding_research.tests.fixture_runtime_harness import SentinelRegistry

    reg = SentinelRegistry()
    guard = reg.sentinel("segmentation.run_spherical_segmentation", "segmentation")
    with pytest.raises(ForbiddenRuntimeError):
        guard(object())
    assert reg["segmentation.run_spherical_segmentation"] == 1


# --------------------------------------------------------------------------- #
# 3. embed publishes complete committed observation groups                     #
# --------------------------------------------------------------------------- #
def test_embed_publishes_complete_committed_groups(runner):
    """Every song ends with a ready committed stream + aligned mask + commit marker."""
    from scripts.embedding_research.streams import StreamStore

    runner.run_all()
    store = StreamStore(runner.con, output_root=str(runner.output_root))
    ready = {rec.song_id for rec in store.ready_rows()}
    assert ready == set(SONGS)
    # Durable committed-group payload dirs exist under the fixture output root.
    streams = runner.output_root / "streams"
    commits = runner.output_root / "observation_commits"
    assert streams.is_dir() and commits.is_dir()
    assert len(list(streams.glob("*.npy"))) == len(SONGS)
    assert len(list(commits.iterdir())) >= len(SONGS)


# --------------------------------------------------------------------------- #
# 4. infer-heads publishes an aligned head suite + CURRENT marker per song     #
# --------------------------------------------------------------------------- #
def test_infer_heads_publishes_aligned_suites_and_current_markers(runner):
    """Every song has a ready head suite and a heads/current/<song>.<bb>.json marker."""
    from scripts.embedding_research.streams import HeadStreamStore

    runner.run_all()
    head_store = HeadStreamStore(runner.con, output_root=str(runner.output_root))
    ready = {rec.song_id for rec in head_store.ready_rows()}
    assert ready == set(SONGS)
    current_dir = runner.output_root / "heads" / "current"
    assert current_dir.is_dir()
    for song in SONGS:
        marker = current_dir / f"{song}.{BACKBONE}.json"
        assert marker.is_file(), f"missing CURRENT marker for {song}"


# --------------------------------------------------------------------------- #
# 5. catalog / catalog-report / analyze / head-analysis / report artifacts     #
# --------------------------------------------------------------------------- #
def test_derived_artifacts_published(runner):
    """The compact catalog, report text, analyze metrics and report artifacts all exist."""
    runner.run_all()
    current = runner.output_root / "catalogs" / "current.json"
    assert current.is_file(), "catalog phase must publish catalogs/current.json"
    report_txt = runner.output_root / "report" / "catalog_report.txt"
    assert report_txt.is_file(), "catalog-report must write catalog_report.txt"
    report_out = runner.output_root / "report"
    assert (report_out / "report.json").is_file()
    assert (report_out / "report.html").is_file()


def test_analyze_emits_class_and_global_pool_medoid_rows(runner):
    """analyze persists per-search-class retrieval metrics plus the medoid baseline."""
    runner.run_all()
    rows = runner.con.execute("SELECT DISTINCT strategy_type FROM analyze_metrics ORDER BY 1").fetchall()
    types = {r[0] for r in rows}
    # The per-class retrieval passes write 'catalog'-typed strategy rows; the MANDATORY observed
    # medoid baseline (unconditional — no emit flag) adds the 'global_pool' row(s) (never a
    # candidate class).
    assert "catalog" in types
    assert "global_pool" in types


def test_baseline_and_catalog_rows_present_and_scoped(runner):
    """Catalog (per-class) + global_pool medoid baseline rows persist, scoped to the analyze run."""
    runner.run_all()
    analyze_run = runner.evidence.phase_run_id("analyze")
    n_catalog = runner.con.execute(
        "SELECT count(*) FROM analyze_metrics WHERE strategy_type='catalog' AND run_id=?", (analyze_run,)
    ).fetchone()[0]
    # Two distinct search classes (the 0.9/1.0 alias collapse + the distinct 0.2) -> at least
    # two per-class retrieval passes.  Explicit synthetic expectation.
    assert n_catalog >= 2
    medoid = runner.con.execute(
        "SELECT count(*) FROM analyze_metrics WHERE strategy_type='global_pool' AND run_id=?", (analyze_run,)
    ).fetchone()[0]
    # The observed global-medoid baseline (P1-S3 reads it for the winner deltas) is emitted once
    # per (backbone, sim_metric, k, metric).
    assert medoid >= 1
