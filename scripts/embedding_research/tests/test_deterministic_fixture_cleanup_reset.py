"""P1-S6 spec-first: reset --scope analysis + current-format cleanup/recovery fixtures.

Plan ``TASK-frozen-observation-semantic-runtime-corrective-pass-D-deterministic-fixture-
verification`` step P1-S6.  Every scenario runs on a **byte-copy** of the module-scoped
deterministic fixture (the pristine ``out`` tree + ``research.duckdb`` built once below are
never mutated), through the REAL maintenance command bodies the CLI wires:

* ``run._cmd_reset`` / ``cleanup.reset_analysis`` — the exact ``reset --scope analysis`` path;
* ``run._cmd_cleanup`` / ``cleanup.cleanup_current`` — the exact ``cleanup --scope {staging|stray|views}`` path;
* ``run._resolve_command`` — the exact unknown-command gate for retired verbs.

The four deliverables are covered:

1. **reset --scope analysis** — snapshot a recursive sha256 byte-map of Tier-1 durable
   artifacts (``streams/``, ``audio_masks/``, ``observation_commits/``, ``heads/`` incl. the
   ``heads/current/`` CURRENT markers, the ``corpus/`` manifests, and ``catalogs/<id>/`` +
   ``catalogs/current.json``) plus Tier-2 (``research.duckdb`` + ``-wal``/``-shm`` + the
   ``views/`` tree) BEFORE, run ``reset --scope analysis`` (real path; CLI ``--dry-run``
   default semantics — reset removes by default), then assert the Tier-1 byte-map is
   IDENTICAL after, the DB + WAL + whole ``views/`` tree are REMOVED, the exit code is 0 per
   the docs, and with the SentinelRegistry armed the reset makes ZERO audio/model/ONNX/CUDA/
   segmentation calls.
2. **cleanup/recovery fixtures** — exercise cleanup scopes ``staging``/``stray``/``views`` on
   fixture copies with deliberately planted artifacts.  Assert ``staging``/``stray`` are
   report-then-remove with ``--dry-run`` default (nothing removed unless ``dry_run`` is
   explicitly ``False``); the ``views`` scope removes only GC-eligible (unreferenced) view
   keyset dirs and preserves retained-run-referenced views (per the retention-aware semantics
   the Exec-Fixer landed — see ``test_cleanup.py`` regressions); committed Tier-1 payloads and
   the ``catalogs/current.json``-selected catalog are never removed by ANY scope; sentinel
   counts stay zero.  A recovery case restores a removed stray/committed item from the harness
   and re-verifies the tree is clean.
3. **retired scope/command rejection** — ``cleanup --scope <retired>`` and
   ``reset --scope <retired>`` (the obsolete ``dead``/``archival``/``analysis-run`` names) are
   ordinary usage errors exiting ``2`` with no compatibility/fuzzy handling; a retired command
   verb (``stratify``/``segment``/``classify``/``head``) is an ordinary unknown command exiting
   ``2`` (no legacy-alias mapping remains).
4. **post-reset derived rerun** — after ``reset --scope analysis`` the surviving Tier-1 state
   still supports the full derived rerun: ``reindex`` (sentinels armed -> zero forbidden
   calls), then ``analyze``/``head-analysis``/``report`` again; assert zero segmentation
   recompute, durable catalog bytes + ``current.json`` unchanged (no new catalog built), and
   deterministic logical results match the pre-reset baseline modulo the one legitimately
   time-varying provenance field (the 13-digit wall-clock run timestamps), documented below.

Cleanup/reset only ever delete the disposable tier (DB + WAL + ``views/``); they never open
audio/models/sessions/ONNX/CUDA or run segmentation.  All assertions are synthetic; this makes
no empirical retrieval claim.

Methodology notes (kept in the step annotation):

* **Real reset path.** ``reset --scope analysis`` is driven through ``run._cmd_reset`` with
  ``run_mod.OUTPUT_ROOT``/``DB_PATH`` monkeypatched to the working byte-copy — the exact body
  ``run.main`` dispatches after argparse + the run lock.  ``args.dry_run=None`` reproduces the
  CLI default, so reset REMOVES (``bool(None) is False``).
* **Cleanup path.** ``staging``/``stray`` are driven through ``cleanup.cleanup_current`` with
  the exact ``dry_run`` value the CLI computes (default ``True`` = report-only for these two),
  plus an explicit ``dry_run=False`` pass for the destructive case.  The ``views`` scope is
  driven through ``run._cmd_cleanup`` (default removes; it opens a READ-ONLY ``research.duckdb``
  connection to honour retained ``run_provenance`` ``view_refs`` exactly as the CLI does).
* **Retained-run protection.**  A retained ``analyze`` run whose ``view_refs`` names one of the
  fixture's REAL view keyset dirs is written to the copy's DB; ``cleanup --scope views`` then
  deletes only the unreferenced keyset dirs and preserves the referenced one (per the new
  retention-aware semantics + ``test_cleanup.py`` regressions).
* **Tier byte-maps.**  Tier-1 = recursive sha256 over ``streams/``, ``audio_masks/``, ``heads/``
  (incl. the ``heads/current/`` markers), ``observation_commits/``, ``catalogs/`` and
  ``corpus/``.  The synthetic fixture's own ``ingest`` writes no durable ``corpus/songs.json``,
  so the reset test PLANTS valid current-format ``corpus/manifest.json`` + ``corpus/songs.json``
  into the copy before reset to make the corpus-manifest byte-preservation clause non-vacuous
  (``reindex._scan_corpus_state`` accepts ``{}`` / ``[]``, so they are valid current-format and
  never refused).
* **Normalized field.**  The only post-reset vs baseline difference in the derived rerun is the
  13-digit epoch-ms wall-clock ``started_at``/``finished_at`` run timestamps, normalized to a
  fixed token symmetrically on both sides.  No other provenance field varies.
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

from scripts.embedding_research import cleanup
from scripts.embedding_research import run as run_mod
from scripts.embedding_research.db import provenance as _prov
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

#: Derived-phase sentinel seams that must stay ZERO across reset/cleanup/reindex and re-run.
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

#: Tier-1 durable filesystem artifact families (DD Tier-1/2 committed payloads + catalog +
#: corpus manifests).  The disposable ``views/`` tree and regenerated ``report/`` are excluded.
_TIER1_FAMILIES = ("streams", "audio_masks", "heads", "observation_commits", "catalogs", "corpus")

#: Retired cleanup/reset scope names that must be rejected as ordinary usage errors (exit 2).
_RETIRED_SCOPES = ("dead", "archival", "analysis-run")

#: Retired phase command verbs (already ordinary unknown commands after Plan C P1-S7).
_RETIRED_VERBS = ("stratify", "segment", "classify", "head")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tier1_map(root: Path) -> dict[str, str]:
    """Recursive sha256 byte-map (relpath -> sha) over the Tier-1 durable families only."""
    out: dict[str, str] = {}
    for family in _TIER1_FAMILIES:
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


def _digest_name(song: str, backbone: str, suffix: str, hexchar: str = "d") -> str:
    return f"{song}.{backbone}.{hexchar * 64}{suffix}"


def _write(root: Path, rel: str, content: bytes = b"x") -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _plant_corpus_manifests(root: Path) -> None:
    """Plant valid current-format corpus manifests (accepted by reindex._scan_corpus_state).

    The synthetic fixture's ingest writes no durable corpus/songs.json; planting them here makes
    the reset byte-preservation clause for ``corpus/`` non-vacuous.
    """
    _write(root, "corpus/manifest.json", json.dumps({"kind": "corpus", "schema_version": "1"}).encode())
    _write(root, "corpus/songs.json", b"[]")


def _analyze_rows(con, run_id: str) -> list:
    """Every ``analyze_metrics`` value row for *run_id* (strategy_key..value), deterministically sorted."""
    rows = con.execute(
        "SELECT strategy_key, strategy_type, sim_metric, k, metric, value FROM analyze_metrics WHERE run_id = ?",
        [run_id],
    ).fetchall()
    return sorted(repr(r) for r in rows)


def _head_rows(con, run_id: str) -> list:
    """Every ``head_phase_provenance`` row for *run_id* (deterministic cols, run_id excluded)."""
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

    This is disposable corpus-metadata reconstruction (the same rows the pre-reset run's ingest
    registered) — NOT segmentation/inference recompute.  Every deterministic analyze input still
    comes from the surviving durable catalog + committed streams/masks/heads.
    """
    for song in SONGS:
        m = SONG_METADATA[song]
        con.execute(
            "INSERT OR REPLACE INTO songs (song_id, path, artist, album, title, genre) VALUES (?, ?, ?, ?, ?, ?)",
            (song, m["path"], m["artist"], m["album"], m["title"], m["genre"]),
        )


_REPORT_TS = re.compile(r"\b\d{13}\b")


def _report_normalize(text: str) -> str:
    """Normalize the one legitimately time-varying provenance field in the report machine output."""
    return _REPORT_TS.sub("__RUN_TS__", text)


def _view_keyset_dirs(root: Path) -> list[str]:
    """Existing disposable view keyset dir names under ``root/views`` (non-empty when analyze ran)."""
    views = root / "views"
    if not views.is_dir():
        return []
    return sorted(p.name for p in views.iterdir() if p.is_dir())


def _arm_sentinels(p: _Patch, reg: SentinelRegistry, runner: FixtureCliRunner, *, segmentation: bool) -> None:
    """Install the forbidden audio/model/ONNX/CUDA sentinels (and optionally the segmentation one)."""
    runner._install_forbidden_sentinels(p, reg)
    if segmentation:
        runner._install_segmentation_sentinel(p, reg)


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    """Drive the REAL eight-phase CLI dispatch ONCE over a FILE-backed DuckDB (module scope).

    The pristine ``out`` tree and its ``research.duckdb`` are the canonical pre-reset fixture;
    every reset/cleanup mutation below happens on a ``shutil`` byte-copy so this stays intact and
    re-runnable.  The file-backed DB (not in-memory) is what makes the reset/DB-deletion surface
    real.
    """
    scratch = tmp_path_factory.mktemp("det-cleanup-reset")
    out = scratch / "out"
    db_path = scratch / "research.duckdb"
    con = duckdb.connect(str(db_path))
    ensure_schema(con)
    runner = FixtureCliRunner(con, out, thresholds=THRESHOLDS)
    runner.run_all()
    # Checkpoint + release the DB so the pristine file copy is clean (no -wal/-shm).
    con.close()
    return SimpleNamespace(out=out, db_path=db_path, runner=runner)


def _copy_fixture(run, tmp_path: Path, name: str) -> tuple[Path, Path]:
    """Byte-copy the pristine fixture into *tmp_path/name*; returns ``(work_out, work_db)``."""
    work = tmp_path / name
    work_out = work / "out"
    work_db = work / "research.duckdb"
    shutil.copytree(run.out, work_out)
    shutil.copy2(run.db_path, work_db)
    return work_out, work_db


# ─────────────────────────────────────────────────────────────────────────── #
# Deliverable 1 — reset --scope analysis                                      #
# ─────────────────────────────────────────────────────────────────────────── #
def test_reset_analysis_removes_disposable_tier_and_preserves_tier1(run, tmp_path, monkeypatch):
    """reset --scope analysis (real path, CLI dry-run default) removes DB+WAL+views and
    byte-preserves every Tier-1 durable artifact incl. corpus manifests."""
    _out, _db_path, runner = run.out, run.db_path, run.runner
    work_out, work_db = _copy_fixture(run, tmp_path, "reset-copy")
    # The fixture's own ingest writes no durable corpus files; plant valid current-format corpus
    # manifests so the reset must demonstrably byte-preserve the corpus family too.
    _plant_corpus_manifests(work_out)

    tier1_before = _tier1_map(work_out)
    assert tier1_before, "pre-reset Tier-1 byte-map must be non-empty"
    assert any(rel.startswith("corpus/") for rel in tier1_before), "planted corpus manifests must be in the map"
    assert work_db.exists(), "research.duckdb must exist pre-reset (Tier-2 present)"
    assert (work_out / "views").is_dir(), "disposable views tree must exist pre-reset (analyze ran)"

    reg = SentinelRegistry()
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    monkeypatch.setattr(run_mod, "DB_PATH", work_db)
    with _Patch() as p:
        _arm_sentinels(p, reg, runner, segmentation=True)
        # The exact body the CLI dispatches for `reset --scope analysis`.  dry_run=None is the
        # CLI default => reset REMOVES (bool(None) is False).  Exit code 0 = returns cleanly.
        result = run_mod._cmd_reset(SimpleNamespace(scope="analysis", dry_run=None))
    assert result is None, "reset returns cleanly (exit 0 per docs)"

    # Tier-2 disposable surface removed.
    assert not work_db.exists(), "research.duckdb must be removed by reset"
    assert not (work_out / "views").exists(), "the whole disposable views tree must be removed by reset"
    assert not work_db.with_name(work_db.name + ".wal").exists(), "no WAL may survive reset"

    # Tier-1 durable artifacts byte-preserved (identical recursive sha256 map).
    assert _tier1_map(work_out) == tier1_before, "reset must byte-preserve every Tier-1 durable artifact"

    # Sentinel counts are zero — reset performs no audio/model/ONNX/CUDA/segmentation work.
    assert reg.zero_for(_FORBIDDEN_KEYS), f"reset made forbidden calls: {reg.counts}"
    assert reg[_SEGMENTATION_KEY] == 0, "reset must make zero segmentation calls"


# ─────────────────────────────────────────────────────────────────────────── #
# Deliverable 2 — cleanup staging / stray / views + recovery                   #
# ─────────────────────────────────────────────────────────────────────────── #
def test_cleanup_staging_report_then_remove_keeps_committed(run, tmp_path):
    """staging is report-then-remove with --dry-run default; the destructive pass (dry_run=False)
    removes only leftover ``.staging`` tmp writes and never touches committed Tier-1 payloads."""
    out = run.out
    work_out, _ = _copy_fixture(run, tmp_path, "staging-copy")
    leftover = _write(work_out, "streams/.staging/s1.effnet.stage.tmp", b"leftover")
    baseline_tier1 = _tier1_map(out)

    # --dry-run default (report only; nothing removed).
    report = cleanup.cleanup_current(work_out, None, scope="staging")
    assert report.scope == "staging" and report.dry_run is True
    assert str(leftover) in report.removed, "dry-run must report the leftover staging tmp"
    assert leftover.exists(), "--dry-run default must not remove anything"

    # Explicit destructive pass removes the leftover; committed payloads untouched.
    cleanup.cleanup_current(work_out, None, scope="staging", dry_run=False)
    assert not leftover.exists(), "staging cleanup must remove the leftover .tmp"
    assert _tier1_map(work_out) == baseline_tier1, "staging cleanup must never remove committed Tier-1 payloads"


def test_cleanup_stray_report_then_remove_preserves_committed_and_current(run, tmp_path):
    """stray is report-then-remove with --dry-run default; removal deletes only a digest-named
    orphan payload + an unselected current-format catalog, never committed payloads or the
    current-selected catalog."""
    out = run.out
    work_out, _ = _copy_fixture(run, tmp_path, "stray-copy")
    baseline_tier1 = _tier1_map(out)

    # Current-selected catalog dir (the fixture's one committed catalog).
    current = json.loads((work_out / "catalogs" / "current.json").read_text())
    current_catalog = work_out / "catalogs" / current["catalog_id"]
    assert current_catalog.is_dir()

    # Plant an orphan digest-named stray stream payload (no sibling manifest) + an unselected
    # valid current-format catalog dir.
    orphan = _write(work_out, f"streams/{_digest_name('sx', 'effnet', '.npy')}", b"orphan-payload")
    stray_cat = work_out / "catalogs" / ("f" * 64)
    _write(stray_cat, "catalog.duckdb", b"db")
    _write(stray_cat, "catalog.manifest.json", b'{"kind": "catalog", "schema_version": "1"}')

    # --dry-run default (report only).
    report = cleanup.cleanup_current(work_out, None, scope="stray")
    assert report.scope == "stray" and report.dry_run is True
    assert str(orphan) in report.removed and str(stray_cat) in report.removed
    assert orphan.exists() and stray_cat.is_dir(), "--dry-run default must not remove anything"

    # Explicit destructive pass removes only the genuine strays.
    cleanup.cleanup_current(work_out, None, scope="stray", dry_run=False)
    assert not orphan.exists(), "stray cleanup must remove the digest orphan payload"
    assert not stray_cat.exists(), "stray cleanup must remove the unselected current-format catalog"
    assert current_catalog.is_dir(), "stray cleanup must never remove the current-selected catalog"
    assert _tier1_map(work_out) == baseline_tier1, "stray cleanup must never remove committed Tier-1 payloads"


def test_cleanup_stray_recovery_restores_and_reverifies_clean(run, tmp_path, monkeypatch):
    """Recovery: after a stray cleanup removed a formerly-committed payload, restoring it from the
    harness (pristine fixture) makes the tree clean again — strict verify passes and a further
    stray cleanup reports nothing to remove."""
    out, _db_path, _runner = run.out, run.db_path, run.runner
    work_out, _ = _copy_fixture(run, tmp_path, "recovery-copy")
    baseline_tier1 = _tier1_map(out)

    # Pick one real committed stream payload and delete its sibling .json manifest -> the payload
    # is now an orphan (digest payload with no manifest) that stray cleanup will remove.
    stream_dir = work_out / "streams"
    payload = next(p for p in sorted(stream_dir.glob("*.npy")))
    manifest = payload.with_suffix(".json")
    assert manifest.is_file(), "a committed stream payload must have a sibling manifest"
    manifest.unlink()

    # stray cleanup removes the orphaned payload.
    cleanup.cleanup_current(work_out, None, scope="stray", dry_run=False)
    assert not payload.exists(), "stray cleanup must remove the payload whose manifest was removed"

    # RECOVERY: restore the removed committed group (payload + its manifest) from the pristine
    # harness fixture — the artifact is committed again and no longer classified as stray.
    pristine_payload = out / "streams" / payload.name
    pristine_manifest = pristine_payload.with_suffix(".json")
    shutil.copy2(pristine_payload, payload)
    shutil.copy2(pristine_manifest, manifest)

    # Re-verify clean: a further stray cleanup reports nothing (restored artifact is committed),
    # and strict verify (real command body) passes on the restored tree.
    rerun = cleanup.cleanup_current(work_out, None, scope="stray", dry_run=False)
    assert rerun.removed == [], "restored committed group must not be classified as stray again"
    assert _tier1_map(work_out) == baseline_tier1, "restored Tier-1 bytes must equal the pristine baseline"

    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    # Strict verify against the restored copy returns cleanly (exit 0 per docs: no refusals).
    result = run_mod._cmd_verify(SimpleNamespace(strict=True))
    assert result is None, "strict verify on the restored copy must pass (no refusals -> exit 0)"


def test_cleanup_views_no_retained_run_removes_all_views(run, tmp_path, monkeypatch):
    """cleanup --scope views with no retained analysis run (the fixture's analyze rows are all
    retained=False) GCs every disposable view keyset dir and removes the whole ``views/`` tree,
    leaving Tier-1 bytes untouched."""
    out = run.out
    work_out, work_db = _copy_fixture(run, tmp_path, "views-copy")
    baseline_tier1 = _tier1_map(out)
    assert _view_keyset_dirs(work_out), "analyze must have materialized disposable views pre-cleanup"

    reg = SentinelRegistry()
    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    monkeypatch.setattr(run_mod, "DB_PATH", work_db)
    with _Patch() as p:
        _arm_sentinels(p, reg, run.runner, segmentation=True)
        # The exact body the CLI dispatches for `cleanup --scope views` (default dry-run=False =>
        # removes; opens a READ-ONLY research.duckdb to read retained view_refs).
        result = run_mod._cmd_cleanup(SimpleNamespace(scope="views", dry_run=None))
    assert result is None, "cleanup --scope views returns cleanly (exit 0 per docs)"
    assert not (work_out / "views").exists(), "no retained run -> every view is GC-eligible and the tree is removed"
    assert _tier1_map(work_out) == baseline_tier1, "views cleanup must never remove Tier-1 payloads"
    assert reg.zero_for(_FORBIDDEN_KEYS), f"views cleanup made forbidden calls: {reg.counts}"
    assert reg[_SEGMENTATION_KEY] == 0, "views cleanup must make zero segmentation calls"


def test_cleanup_views_preserves_retained_run_referenced_view(run, tmp_path, monkeypatch):
    """cleanup --scope views is retention-aware: a REAL fixture view keyset dir referenced by a
    retained analyze run survives GC while every unreferenced view is removed."""
    out = run.out
    work_out, work_db = _copy_fixture(run, tmp_path, "views-retained-copy")
    baseline_tier1 = _tier1_map(out)

    # Pick one of the real disposable view keyset dirs to protect; plant an unreferenced one.
    protected = _view_keyset_dirs(work_out)[0]
    protected_dir = work_out / "views" / protected
    assert protected_dir.is_dir()
    unreferenced_dir = _write(work_out, f"views/{'e' * 64}/payload.npy", b"unreferenced")
    unreferenced_dir = unreferenced_dir.parent

    # Record a retained analyze run referencing the protected view keyset dir in the copy's DB.
    wcon = duckdb.connect(str(work_db))
    try:
        ensure_schema(wcon)
        _prov.write_run_provenance(
            wcon,
            run_id="retained-run",
            phase="analyze",
            status="complete",
            started_at=0,
            finished_at=0,
            retained=True,
            view_refs=f"k1|c1|views/{protected}",
        )
    finally:
        wcon.close()

    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    monkeypatch.setattr(run_mod, "DB_PATH", work_db)
    run_mod._cmd_cleanup(SimpleNamespace(scope="views", dry_run=None))

    assert protected_dir.is_dir(), "retained-run-referenced view keyset dir must survive GC"
    assert not unreferenced_dir.exists(), "unreferenced view keyset dir must be GC'd"
    assert (work_out / "views").is_dir(), "views/ parent stays because a protected dir survives"
    # All OTHER fixture view keyset dirs (unreferenced by any retained run) are GC-eligible.
    surviving = _view_keyset_dirs(work_out)
    assert surviving == [protected], f"only the retained-referenced view may survive: {surviving}"
    assert _tier1_map(work_out) == baseline_tier1, "views cleanup must never remove Tier-1 payloads"


# ─────────────────────────────────────────────────────────────────────────── #
# Deliverable 3 — retired scope / command rejection (exit 2, no compat)        #
# ─────────────────────────────────────────────────────────────────────────── #
def test_cli_cleanup_staging_and_stray_scopes_exit_zero_zero_forbidden(run, tmp_path, monkeypatch):
    """P3-S1: cleanup --scope staging|stray driven through the real ``run._cmd_cleanup`` seam
    returns cleanly (exit 0) on a clean fixture copy and makes ZERO audio/model/ONNX/CUDA/
    segmentation calls.

    ``test_cleanup_views_*`` already drive ``cleanup --scope views`` through ``run._cmd_cleanup``;
    this closes the corresponding real-CLI exit-0 boundary for the staging and stray scopes
    (the destructive ``dry_run=False`` pass removes nothing from the already-clean fixture copy
    and never touches committed Tier-1 payloads).
    """
    for scope in ("staging", "stray"):
        work_out, work_db = _copy_fixture(run, tmp_path, f"cleanup-{scope}-cli")
        baseline_tier1 = _tier1_map(run.out)
        reg = SentinelRegistry()
        monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
        monkeypatch.setattr(run_mod, "DB_PATH", work_db)
        with _Patch() as p:
            _arm_sentinels(p, reg, run.runner, segmentation=True)
            # The exact body the CLI dispatches for `cleanup --scope {staging|stray}`.  A clean
            # fixture copy has no leftover staging writes / strays, so the destructive pass
            # removes nothing and returns cleanly (exit 0 per docs: no refusals).
            result = run_mod._cmd_cleanup(SimpleNamespace(scope=scope, dry_run=False))
        assert result is None, f"cleanup --scope {scope} must return cleanly (exit 0)"
        assert reg.zero_for(_FORBIDDEN_KEYS), f"cleanup --scope {scope} made forbidden calls: {reg.counts}"
        assert reg[_SEGMENTATION_KEY] == 0, f"cleanup --scope {scope} must make zero segmentation calls"
        assert _tier1_map(work_out) == baseline_tier1, "cleanup must never remove committed Tier-1 payloads"


def test_cleanup_rejects_retired_scopes_exit2():
    """cleanup --scope <retired-scope-name> is an ordinary usage error (exit 2) with no
    compatibility handling or fuzzy suggestion of retired names."""
    # Guard against any real-path side effects: these are rejected before any IO.
    for retired in _RETIRED_SCOPES:
        with pytest.raises(SystemExit) as exc:
            run_mod._cmd_cleanup(SimpleNamespace(scope=retired, dry_run=None))
        assert exc.value.code == 2, f"cleanup --scope {retired} must exit 2 (got {exc.value.code})"


def test_reset_rejects_retired_scopes_exit2():
    """reset --scope <retired-scope-name> is an ordinary usage error (exit 2) — only ``analysis``
    is a valid reset scope."""
    for retired in _RETIRED_SCOPES:
        with pytest.raises(SystemExit) as exc:
            run_mod._cmd_reset(SimpleNamespace(scope=retired, dry_run=None))
        assert exc.value.code == 2, f"reset --scope {retired} must exit 2 (got {exc.value.code})"


def test_retired_command_verbs_are_unknown_commands_exit2():
    """Retired command verbs are ordinary unknown commands (exit 2), identical to an unrecognized
    verb — no named alias/compatibility path remains."""
    # The legacy-alias surface is gone from run.py (Plan C P1-S7).
    assert not hasattr(run_mod, "LEGACY_PHASE_ALIASES"), "LEGACY_PHASE_ALIASES must stay removed"
    for verb in (*_RETIRED_VERBS, "frobnicate"):
        with pytest.raises(SystemExit) as exc:
            run_mod._resolve_command(verb)
        assert exc.value.code == 2, f"unknown command {verb!r} must exit 2 (got {exc.value.code})"


# ─────────────────────────────────────────────────────────────────────────── #
# Deliverable 4 — post-reset reindex + derived rerun matches the baseline       #
# ─────────────────────────────────────────────────────────────────────────── #
def test_post_reset_reindex_and_derived_rerun_match_baseline(run, tmp_path, monkeypatch):
    """After reset --scope analysis, the surviving Tier-1 state supports the full derived rerun:
    reindex (sentinels armed -> zero forbidden calls), then analyze/head-analysis/report again
    with ZERO segmentation recompute, durable catalog bytes + current.json unchanged (no new
    catalog), and deterministic logical results matching the pre-reset baseline modulo the one
    legitimately time-varying run-timestamp field."""
    out, db_path, runner = run.out, run.db_path, run.runner

    # -- Pre-reset baseline (from the pristine fixture). ---------------------- #
    analyze_rid = runner.evidence.phase_run_id("analyze")
    head_rid = runner.evidence.phase_run_id("head-analysis")
    report_rid = runner.evidence.phase_run_id("report")
    assert analyze_rid.startswith("analyze-") and head_rid.startswith("head-analysis-")

    base_con = duckdb.connect(str(db_path))
    try:
        baseline_analyze = _analyze_rows(base_con, analyze_rid)
        baseline_head = _head_rows(base_con, head_rid)
        n_catalog_classes = base_con.execute(
            "SELECT count(DISTINCT strategy_key) FROM analyze_metrics WHERE run_id = ? AND strategy_type = 'catalog'",
            [analyze_rid],
        ).fetchone()[0]
        n_baseline = base_con.execute(
            "SELECT count(*) FROM analyze_metrics WHERE run_id = ? AND strategy_key = ?",
            [analyze_rid, BASELINE_STRATEGY_KEY],
        ).fetchone()[0]
    finally:
        base_con.close()
    assert len(baseline_analyze) > 0 and len(baseline_head) > 0
    assert n_catalog_classes == 2 and n_baseline == len(REPORT_METRICS)

    baseline_report_json = (out / "report" / "report.json").read_text()
    baseline_tier1 = _tier1_map(out)
    baseline_catalog_dirs = _catalog_dirs(out)
    baseline_current = json.loads((out / "catalogs" / "current.json").read_text())
    assert baseline_tier1 and len(baseline_catalog_dirs) == 1

    # -- Byte-copy, then reset --scope analysis (real path). ------------------ #
    work_out, work_db = _copy_fixture(run, tmp_path, "reset-rerun-copy")
    assert _tier1_map(work_out) == baseline_tier1, "copy Tier-1 bytes must match the baseline"
    assert (work_out / "views").is_dir()

    monkeypatch.setattr(run_mod, "OUTPUT_ROOT", work_out)
    monkeypatch.setattr(run_mod, "DB_PATH", work_db)
    run_mod._cmd_reset(SimpleNamespace(scope="analysis", dry_run=None))
    assert not work_db.exists() and not (work_out / "views").exists()
    assert _tier1_map(work_out) == baseline_tier1, "reset must not disturb Tier-1 bytes"

    # -- reindex via the REAL command path, sentinels ARMED ------------------- #
    reindex_reg = SentinelRegistry()
    with _Patch() as p:
        _arm_sentinels(p, reindex_reg, runner, segmentation=True)
        # _cmd_reindex opens a fresh DB connection to DB_PATH (now absent) and rebuilds registries.
        run_mod._cmd_reindex(SimpleNamespace())
    assert reindex_reg.zero_for(_FORBIDDEN_KEYS), f"reindex made forbidden calls: {reindex_reg.counts}"
    assert reindex_reg[_SEGMENTATION_KEY] == 0, "reindex must make zero segmentation calls"

    recon = duckdb.connect(str(work_db))
    ensure_schema(recon)
    try:
        ready_streams = recon.execute("SELECT count(*) FROM stream_registry WHERE status = 'ready'").fetchone()[0]
        ready_heads = recon.execute("SELECT count(*) FROM head_stream_registry WHERE status = 'ready'").fetchone()[0]
    finally:
        recon.close()
    assert ready_streams == len(SONGS), "reindex must rebuild every committed stream registry row"
    assert ready_heads == len(SONGS), "reindex must rebuild every marker-selected head registry row"

    # -- Derived rerun on the surviving committed state (sentinels armed) ----- #
    rerun_reg = SentinelRegistry()
    work_con = duckdb.connect(str(work_db))
    ensure_schema(work_con)
    try:
        _restore_corpus_songs(work_con)
        for phase, rid in (("analyze", analyze_rid), ("head-analysis", head_rid), ("report", report_rid)):
            with _Patch() as p:
                _arm_sentinels(p, rerun_reg, runner, segmentation=(phase in _SEGMENT_FREE_DERIVED))
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
    finally:
        work_con.close()

    assert rerun_reg.zero_for(_FORBIDDEN_KEYS), f"derived re-run made forbidden calls: {rerun_reg.counts}"
    assert rerun_reg[_SEGMENTATION_KEY] == 0, "no segmentation recomputation may occur post-reset"
    assert post_catalog_classes == 2 and post_baseline == len(REPORT_METRICS)

    # -- COMPARE to the pre-reset baseline ------------------------------------ #
    assert post_analyze == baseline_analyze, "analyze results must reproduce identically post-reset"
    assert post_head == baseline_head, "head-analysis results must reproduce identically post-reset"
    post_report_json = (work_out / "report" / "report.json").read_text()
    assert _report_normalize(post_report_json) == _report_normalize(baseline_report_json), (
        "report machine output must be byte-identical modulo the wall-clock run timestamps"
    )

    # Durable Tier-1 bytes identical pre/post; catalog not rebuilt.
    assert _tier1_map(work_out) == baseline_tier1, "Tier-1 bytes must be identical pre/post reset+rerun"
    assert _catalog_dirs(work_out) == baseline_catalog_dirs, "no new catalog directory may appear post-reset"
    post_current = json.loads((work_out / "catalogs" / "current.json").read_text())
    assert post_current == baseline_current, "catalogs/current.json must still select the same catalog"
