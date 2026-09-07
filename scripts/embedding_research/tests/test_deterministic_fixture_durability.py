"""P1-S5 spec-first: disposable ``research.duckdb`` deletion durability over the P1-S1/S2 fixture.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S5.  This test drives the FULL disposable-DB durability path on a
**byte-copy** of the module-scoped deterministic fixture (never mutating the pristine out tree
or its DB that the module builds once):

1. **PRE-deletion baseline.**  Capture (a) the deterministic LOGICAL results — analyze + head-
   analysis run identities, the per-class execution scope (2 catalog strategy classes), the
   medoid-baseline rows, and every ``analyze_metrics`` / ``head_phase_provenance`` value row —
   plus the report machine artifact (``report/report.json``), and (b) a recursive sha256
   byte-map of ALL durable filesystem artifacts (``streams/``, ``audio_masks/``, ``heads/``,
   ``observation_commits/``, ``catalogs/``) and the current catalog identity/dir listing.
2. **DELETE the disposable DB.**  Close every connection, delete ``research.duckdb`` (+ any
   ``-wal``/``-shm``) and the disposable search-view tree (``views/``).  Assert the durable
   artifacts still exist byte-identical (re-hash).
3. **reindex** via the REAL command path (``run._cmd_reindex``, the exact body the CLI runs)
   with the audio/model/ONNX/CUDA/segmentation sentinels ARMED: it succeeds and rebuilds ONLY
   the registry/index rows from the filesystem manifests, making ZERO forbidden calls.
4. **Re-run** analyze / head-analysis / report against the surviving committed artifacts with
   the derived-phase sentinels armed: all succeed with ZERO audio/model/ONNX/CUDA calls and ZERO
   segmentation recomputation (segmentation sentinel count == 0; catalog bytes/durable content
   untouched; ``catalogs/current.json`` still points at the SAME catalog dir — no new catalog
   was built).
5. **COMPARE** post-deletion results to the baseline: analyze + head-analysis produce byte-
   identical logical rows and the report machine output is byte-identical modulo the one
   legitimately time-varying provenance field class (the 13-digit wall-clock run timestamps
   ``started_at``/``finished_at``), which the comparison normalizes away.  Everything
   deterministic matches exactly.  Durable artifact bytes are identical pre/post.
6. **Prove catalog reuse.**  The catalog was opened/queried by the re-run phases but never
   rebuilt: no new catalog directory appeared and ``current.json`` is unchanged.

The disposable-DB deletion durability contract (DD req 10 / DD L276-278): ``research.duckdb``
holds only rebuildable registry/index rows, disposable corpus metadata, run provenance and
disposable gathered views — never durable committed payloads or the catalog.  The re-run after
deletion + reindex must therefore reproduce the pre-deletion deterministic results WITHOUT any
inference (audio/ONNX/model/CUDA) or segmentation recomputation.

Methodology notes (kept in the annotation):

* **Replayed run ids.**  The post-deletion re-run replays the identical deterministic CLI phase
  sequence into a freshly-recreated research DB, so the deterministic run ids (``analyze-000006``
  etc.) reproduce identically.  This is intentional: it makes the report machine output a pure
  byte-comparison modulo timestamps, and the re-run still creates genuinely NEW
  ``run_provenance`` / ``analyze_metrics`` / ``head_phase_provenance`` / disposable-view rows on
  the fresh DB (a real re-execution, not a cache).  The catalog ``strategy_key`` and disposable
  ``content_hash``/``view_content_hash`` are run-scoped identities (they embed the run id via the
  view ``keyset_hash``), so comparing byte-identical rows pre/post is only meaningful under the
  identical replayed run id — which is exactly what the replay provides.
* **Normalized field.**  The only post-deletion vs baseline difference is the wall-clock
  ``started_at``/``finished_at`` run timestamps (13-digit epoch-ms), which the report
  comparison normalizes to a fixed token.  No other provenance field varies.
* **Corpus metadata reconstruction.**  The synthetic fixture registers corpus ``songs``/artist
  metadata in the research DB only (its ``ingest`` writes no durable ``corpus/songs.json``); the
  deterministic analyze lens requires per-song artist labels.  So after DB deletion + reindex
  (which rebuilds registry/index rows but — matching its documented surface — does not re-derive
  corpus metadata), the test re-establishes the SAME ``SONG_METADATA`` corpus rows in the fresh
  DB.  This mirrors reindex's documented "reconstruct disposable corpus metadata from the corpus
  definition" role and is NOT segmentation/inference recompute — every deterministic analyze
  input still comes from the surviving durable catalog + committed streams/masks/heads.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from types import SimpleNamespace
from typing import TYPE_CHECKING

import duckdb
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.tests.fixture_cli_harness import (
    BASELINE_STRATEGY_KEY,
    SONG_METADATA,
    SONGS,
)
from scripts.embedding_research.tests.fixture_runtime_harness import (
    _SEGMENT_FREE_DERIVED,
    FixtureCliRunner,
    SentinelRegistry,
    _Patch,
)
from scripts.embedding_research.tests.test_deterministic_fixture_outputs import REPORT_METRICS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

THRESHOLDS = (0.9, 1.0, 0.2)

#: Derived-phase sentinel seams that must stay ZERO across reindex and the re-run phases.
_FORBIDDEN_KEYS = [
    "audio.discover_audio",
    "audio.load_audio_mono",
    "model.create_session",
    "onnx.inference_session",
    "cuda.is_available",
    "infer.embed",
    "infer.regenerate_masks",
    "mask.derive_audio_mask",
]
_SEGMENTATION_KEY = "segmentation.run_spherical_segmentation"

#: Durable filesystem artifact families (DD Tier-1/2 committed payloads + catalog).  The
#: disposable ``views/`` tree and regenerated ``report/`` are deliberately EXCLUDED.
_DURABLE_FAMILIES = ("streams", "audio_masks", "heads", "observation_commits", "catalogs")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _durable_map(root: Path) -> dict[str, str]:
    """Recursive sha256 byte-map (relpath -> sha) over the DURABLE artifact families only."""
    out: dict[str, str] = {}
    for family in _DURABLE_FAMILIES:
        base = root / family
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(root))] = _sha(p.read_bytes())
    return out


def _catalog_dirs(root: Path) -> list[str]:
    """Committed catalog dirs under ``root/catalogs`` (excludes staging + current.json)."""
    return sorted(
        str(p.name)
        for p in (root / "catalogs").iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != "current.json"
    )


def _analyze_rows(con, run_id: str) -> list:
    """Every ``analyze_metrics`` value row for *run_id* (strategy_key..value), deterministically sorted."""
    rows = con.execute(
        "SELECT strategy_key, strategy_type, sim_metric, k, metric, value FROM analyze_metrics WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return sorted(repr(r) for r in rows)


def _head_rows(con, run_id: str) -> list:
    """Every ``head_phase_provenance`` row for *run_id* (all deterministic cols, run_id excluded)."""
    rows = con.execute(
        "SELECT config_id, backbone, head, bin_mode, threshold_configured, threshold_effective, "
        "semantics, boundary_source, head_pool_variant, status, reason, n_songs, n_pooled, finite, "
        "scoring_semantics_version, reference_corpus_hash, threshold "
        "FROM head_phase_provenance WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return sorted(repr(r) for r in rows)


def _restore_corpus_songs(con) -> None:
    """Re-establish the fixture corpus ``songs`` metadata rows in a freshly-recreated DB.

    This is disposable corpus metadata reconstruction (the same rows the pre-deletion run's
    ingest registered) — NOT segmentation/inference recompute.  Every deterministic analyze
    input otherwise comes from the surviving durable catalog + committed streams/masks/heads.
    """
    for song in SONGS:
        m = SONG_METADATA[song]
        con.execute(
            "INSERT OR REPLACE INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
            (song, m["path"], m["artist"], m["album"], m["title"], m["genre"]),
        )


_REPORT_TS = re.compile(r"\b\d{13}\b")


def _report_normalize(text: str) -> str:
    """Normalize the one legitimately time-varying provenance field in the report machine output.

    ``started_at``/``finished_at`` are 13-digit epoch-ms wall-clock timestamps; every other field
    is deterministic.  Applied symmetrically to both the baseline and post-deletion reports.
    """
    return _REPORT_TS.sub("__RUN_TS__", text)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Drive the REAL eight-phase CLI dispatch ONCE over a FILE-backed DuckDB (module scope).

    The pristine ``out`` tree and its ``research.duckdb`` are the canonical pre-deletion
    fixture; every durability mutation below happens on a ``shutil`` byte-copy so this stays
    intact and re-runnable.  The file-backed DB (not in-memory) is what makes the deletion
    surface real.
    """
    scratch = tmp_path_factory.mktemp("det-durability")
    out = scratch / "out"
    db_path = scratch / "research.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    runner = FixtureCliRunner(con, out, thresholds=THRESHOLDS)
    runner.run_all()
    # Checkpoint + release the DB so the pristine file copy is clean (no -wal/-shm).
    con.close()
    return SimpleNamespace(out=out, db_path=db_path, runner=runner)


def test_delete_reindex_rerun_reuse_durability(run, tmp_path, monkeypatch):
    """The six-point disposable-DB durability proof on a byte-copy of the fixture."""
    out, db_path, runner = run.out, run.db_path, run.runner

    # -- (1) PRE-deletion baseline ------------------------------------------------ #
    # Deterministic run ids from the pristine run (analyze-000006 / head-analysis-000007 /
    # report-000008).  The post-deletion re-run replays the SAME ids into the fresh DB.
    analyze_rid = runner.evidence.phase_run_id("analyze")
    head_rid = runner.evidence.phase_run_id("head-analysis")
    report_rid = runner.evidence.phase_run_id("report")
    assert analyze_rid.startswith("analyze-") and head_rid.startswith("head-analysis-")

    base_con = duckdb.connect(str(db_path))
    try:
        baseline_analyze = _analyze_rows(base_con, analyze_rid)
        baseline_head = _head_rows(base_con, head_rid)
        # Per-class execution scope + medoid-baseline rows must exist pre-deletion.
        n_catalog_classes = base_con.execute(
            "SELECT count(DISTINCT strategy_key) FROM analyze_metrics WHERE run_id = ? AND strategy_type = 'catalog'",
            [analyze_rid],
        ).fetchone()[0]
        n_baseline = base_con.execute(
            "SELECT count(*) FROM analyze_metrics WHERE run_id = ? AND strategy_key = ?",
            [analyze_rid, BASELINE_STRATEGY_KEY],
        ).fetchone()[0]
        base_report_run = base_con.execute(
            "SELECT count(*) FROM run_provenance WHERE run_id = ?", [report_rid]
        ).fetchone()[0]
    finally:
        base_con.close()
    assert len(baseline_analyze) > 0, "pre-deletion analyze must produce analyze_metrics rows"
    assert len(baseline_head) > 0, "pre-deletion head-analysis must produce head_phase_provenance rows"
    assert n_catalog_classes == 2, "fixture collapses to two per-class executions pre-deletion"
    assert n_baseline == len(REPORT_METRICS), "one medoid-baseline value row per active REPORT_METRIC"
    assert base_report_run == 1, "report phase must have a recorded run row pre-deletion"

    # The report machine artifact must exist pre-deletion.
    baseline_report_json = (out / "report" / "report.json").read_text()

    baseline_durable = _durable_map(out)
    baseline_catalog_dirs = _catalog_dirs(out)
    baseline_current = json.loads((out / "catalogs" / "current.json").read_text())
    assert baseline_durable, "pre-deletion durable byte-map must be non-empty"
    assert len(baseline_catalog_dirs) == 1, "exactly one committed catalog dir pre-deletion"

    # -- (2) Make a hermetic COPY, DELETE the disposable DB + views ----------------- #
    work = tmp_path / "durability-copy"
    work_out = work / "out"
    work_db = work / "research.duckdb"
    shutil.copytree(out, work_out)
    shutil.copy2(db_path, work_db)
    # Durable bytes are identical in the copy.
    assert _durable_map(work_out) == baseline_durable

    # Close nothing else is open on work_db (fresh copy).  Delete the disposable DB + WAL/SHM.
    for suffix in ("", "-wal", "-shm"):
        (work / f"research.duckdb{suffix}").unlink(missing_ok=True)
    assert not work_db.exists(), "research.duckdb must be deleted"
    # Delete the disposable search-view tree; durable artifact bytes must be unchanged.
    views = work_out / "views"
    assert views.is_dir(), "the disposable search-view tree must exist post-analyze"
    shutil.rmtree(views)
    assert not views.exists()
    assert _durable_map(work_out) == baseline_durable, "deleting the disposable DB/views must not touch durable bytes"

    # -- (3) reindex via the REAL command path, sentinels ARMED ----------------------- #
    reindex_reg = SentinelRegistry()
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    monkeypatch.setattr(run_mod, "DB_PATH", work_db)
    with _Patch() as p:
        runner._install_forbidden_sentinels(p, reindex_reg)
        runner._install_segmentation_sentinel(p, reindex_reg)
        # The exact body the CLI dispatches for `reindex` (real DB_PATH/OUTPUT_ROOT flow).
        run_mod._cmd_reindex(SimpleNamespace())
    assert reindex_reg.zero_for(_FORBIDDEN_KEYS), f"reindex must make zero forbidden calls: {reindex_reg.counts}"
    assert reindex_reg[_SEGMENTATION_KEY] == 0, "reindex must make zero segmentation calls"

    # Reindex rebuilt only the registry/index rows from the surviving manifests.
    recon = duckdb.connect(str(work_db))
    ensure_schema(recon)
    try:
        ready_streams = recon.execute("SELECT count(*) FROM stream_registry WHERE status = 'ready'").fetchone()[0]
        ready_heads = recon.execute("SELECT count(*) FROM head_stream_registry WHERE status = 'ready'").fetchone()[0]
    finally:
        recon.close()
    assert ready_streams == len(SONGS), "reindex must rebuild all committed stream registry rows"
    assert ready_heads == len(SONGS), "reindex must rebuild all marker-selected head registry rows"

    # -- (4) Re-run analyze / head-analysis / report on the surviving committed state --- #
    rerun_reg = SentinelRegistry()
    work_con = duckdb.connect(str(work_db))
    ensure_schema(work_con)
    try:
        # Re-establish disposable corpus metadata (see module docstring) in the fresh DB.
        _restore_corpus_songs(work_con)
        for phase, rid in (("analyze", analyze_rid), ("head-analysis", head_rid), ("report", report_rid)):
            with _Patch() as p:
                runner._install_forbidden_sentinels(p, rerun_reg)
                if phase in _SEGMENT_FREE_DERIVED:
                    runner._install_segmentation_sentinel(p, rerun_reg)
                run_mod._run_single_phase(work_con, phase, runner._cfg(phase, rid), db_path=str(work_db))
        post_analyze = _analyze_rows(work_con, analyze_rid)
        post_head = _head_rows(work_con, head_rid)
        post_catalog_classes = work_con.execute(
            "SELECT count(DISTINCT strategy_key) FROM analyze_metrics WHERE run_id = ? AND strategy_type = 'catalog'",
            [analyze_rid],
        ).fetchone()[0]
        post_baseline = work_con.execute(
            "SELECT count(*) FROM analyze_metrics WHERE run_id = ? AND strategy_key = ?",
            [analyze_rid, BASELINE_STRATEGY_KEY],
        ).fetchone()[0]
        post_report_run = work_con.execute(
            "SELECT count(*) FROM run_provenance WHERE run_id = ?", [report_rid]
        ).fetchone()[0]
    finally:
        work_con.close()

    assert rerun_reg.zero_for(_FORBIDDEN_KEYS), f"re-run phases made forbidden calls: {rerun_reg.counts}"
    assert rerun_reg[_SEGMENTATION_KEY] == 0, "no segmentation recomputation may occur during the re-run"
    assert len(post_analyze) > 0 and len(post_head) > 0
    assert post_catalog_classes == 2 and post_baseline == len(REPORT_METRICS) and post_report_run == 1

    # -- (5) COMPARE post-deletion to the pre-deletion baseline ------------------------ #
    # Logical rows reproduce byte-for-byte (same replayed run ids => same run-scoped keys).
    assert post_analyze == baseline_analyze, "analyze results must reproduce identically post-deletion"
    assert post_head == baseline_head, "head-analysis results must reproduce identically post-deletion"

    # Report machine output reproduces modulo the one time-varying provenance field (run ts).
    post_report_json = (work_out / "report" / "report.json").read_text()
    assert _report_normalize(post_report_json) == _report_normalize(baseline_report_json), (
        "report machine output must be byte-identical modulo the wall-clock run timestamps"
    )

    # Durable artifact bytes are identical pre/post (deletion did not disturb them, and the
    # re-run phases wrote nothing into the durable families).
    assert _durable_map(work_out) == baseline_durable, "durable artifact bytes must be identical pre/post"

    # -- (6) Prove catalog reuse (opened/queried, never rebuilt) ----------------------- #
    assert _catalog_dirs(work_out) == baseline_catalog_dirs, "no new catalog directory may appear"
    post_current = json.loads((work_out / "catalogs" / "current.json").read_text())
    assert post_current == baseline_current, "catalogs/current.json must still point at the same catalog"


# --------------------------------------------------------------------------- #
# Plan D Phase 2 (P2-S3): fresh analyze run over the SAME catalog — disposable #
# view identity changes while the durable semantic hash stays stable.          #
# --------------------------------------------------------------------------- #
def test_fresh_analyze_run_changes_disposable_but_semantic_hash_stable(run, tmp_path):
    """P2-S3: semantic search hashes stay stable across a fresh analyze run (disposable changes).

    The disposable view ``keyset_hash`` / ``view_content_hash`` are run-scoped (the keyset
    preimage embeds the run id), so re-running the analyze phase over the IDENTICAL compact
    catalog with a FRESH run id regenerates the disposable search views with a DIFFERENT
    disposable identity while the durable semantic ``search_representation_hash`` — a pure
    function of the catalog's search inputs — stays identical.  This proves report/durable
    comparison is by durable SEMANTIC identity, never by the disposable view/keyset identity,
    complementing the byte-stability proof in
    ``test_delete_reindex_rerun_reuse_durability`` (which replays identical run ids).
    """
    from scripts.embedding_research.db.analyze_scope import parse_analyze_scope

    out, db_path, runner = run.out, run.db_path, run.runner
    original_rid = runner.evidence.phase_run_id("analyze")

    # Hermetic copy so the fresh run's new views never touch the pristine module fixture.
    work = tmp_path / "fresh-run"
    work_out = work / "out"
    work_db = work / "research.duckdb"
    shutil.copytree(out, work_out)
    shutil.copy2(db_path, work_db)
    assert _durable_map(work_out)  # copy must carry the durable committed artifact bytes.

    work_con = duckdb.connect(str(work_db))
    ensure_schema(work_con)
    try:
        fresh_rid = "analyze-999999"
        cfg = runner._cfg("analyze", fresh_rid)
        cfg["output_root"] = work_out  # write disposable views into the copy, never the pristine tree.
        cfg["report_dir"] = work_out / "report"
        reg = SentinelRegistry()
        with _Patch() as p:
            runner._install_forbidden_sentinels(p, reg)
            runner._install_segmentation_sentinel(p, reg)
            run_mod._run_single_phase(work_con, "analyze", cfg, db_path=str(work_db))
        assert reg.zero_for(_FORBIDDEN_KEYS), f"fresh analyze made forbidden calls: {reg.counts}"
        assert reg[_SEGMENTATION_KEY] == 0, "no segmentation recompute may occur during a fresh analyze"

        def _class_scope(run_id: str) -> tuple[set[str], set[str]]:
            semantic: set[str] = set()
            keysets: set[str] = set()
            rows = work_con.execute(
                "SELECT output_artifact_hashes FROM run_provenance WHERE run_id=? AND phase='analyze'",
                [run_id],
            ).fetchall()
            for (blob,) in rows:
                if not blob:
                    continue
                for line in blob.splitlines():
                    p = parse_analyze_scope(line.strip())
                    if p and p.get("scope_kind") == "catalog_class" and p.get("search_representation_hash"):
                        semantic.add(p["search_representation_hash"])
                        keysets.add(p["view_keyset_hash"])
            return semantic, keysets

        sem_a, keys_a = _class_scope(original_rid)
        sem_b, keys_b = _class_scope(fresh_rid)
        assert len(sem_a) == 2 and len(sem_b) == 2, "each analyze run records exactly the two search classes"
        # Durable SEMANTIC identity is stable across the fresh (disposable-regenerating) run.
        assert sem_a == sem_b, "semantic search hashes must stay stable across a fresh analyze run"
        # Disposable view keyset identity CHANGED (run-scoped), so rows are compared by semantic
        # identity, never by disposable identity — and never equal to a semantic hash.
        assert keys_a, "class scopes must record a disposable view keyset"
        assert keys_a.isdisjoint(keys_b), "a fresh run must produce a different disposable view keyset"
        assert sem_a.isdisjoint(keys_a | keys_b), "a semantic hash must never equal a disposable keyset"
    finally:
        work_con.close()
