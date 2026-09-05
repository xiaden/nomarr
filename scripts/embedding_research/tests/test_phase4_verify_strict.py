"""Plan E P4-S3 — ``--verify`` / ``--verify --strict`` provenance, reuse, and refusal.

DD "CLI and provenance contract": every phase run records command line, software
versions, inputs/outputs, warnings, reuse decisions, and run IDs in
``run_provenance``.  ``--verify --strict`` REFUSES (nonzero exit / raised error)
on corruption, unresolved duplicates, incomplete required artifacts, or a failed
post-crash canary.  Plain ``--verify`` records the same conditions as warnings and
continues — never blocks on a warning.

Design decisions under test (for QA arbitration):
* ``--strict`` REQUIRES ``--verify``: ``--strict`` without ``--verify`` is rejected
  (SystemExit 2), never silently implying verify.
* Verification for the four derived CONSUMER phases (catalog-report / analyze /
  head-analysis / report) is a gate BEFORE the runner reads: a rollback-only canary
  (S4) plus required-input presence checks.  The ``catalog`` phase's own
  verification stays inside ``build_segmentation_catalog(verify=...)`` (S1/S3).
* Under ``--verify`` a missing required artifact / unresolved duplicate is recorded
  as a warning note; under ``--strict`` the same condition is a hard refusal raised
  from the preflight gate (recorded as a ``failed`` provenance row, propagated).
* Reuse decisions + warnings are recorded via ``run_provenance.warning_count`` and
  ``structural_change_summary`` (free-text) — no new schema columns.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from scripts.embedding_research import run as run_mod


def _unit(rng, n: int, d: int) -> np.ndarray:
    m = rng.standard_normal((n, d)) * 1.5
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _seed_songs(con):
    for i, song in enumerate(("s1", "s2", "s3", "s4")):
        artist = "A" if i < 2 else "B"
        con.execute(
            "INSERT INTO songs (song_id, path, artist) VALUES (?, ?, ?)",
            (song, f"/audio/{song}.mp3", artist),
        )


def _seed_catalog(con, out) -> str:
    """Register songs, publish ready effnet streams, build a VERIFIED COMPACT catalog.

    The catalog is written to the compact snapshot layout
    ``out/catalogs/.staging-run-cat-vs/catalog.duckdb`` (never the research DB).  Returns
    the snapshot file path so duplicate/missing-artifact setup can open and mutate the
    SNAPSHOT connection (the connection the derived-phase preflight now reads).
    """
    from scripts.embedding_research import catalog
    from scripts.embedding_research.streams import make_current_stream_resolver
    from scripts.embedding_research.streams.store import StreamStore

    songs = ("s1", "s2", "s3", "s4")
    _seed_songs(con)
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(3)
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
        run_id="run-cat-vs",
        verify=True,
    )
    assert rep.verify_ok is True
    # Durably publish so current.json is authoritative (derived phases select by current.json).
    import duckdb as _duckdb

    from scripts.embedding_research import catalog_storage as _cs

    staging_dir = Path(out) / "catalogs" / ".staging-run-cat-vs"
    dcon = _duckdb.connect(str(staging_dir / _cs.CATALOG_DB_FILE), read_only=True)
    try:
        _manifest = _cs.derive_catalog_manifest(dcon)
    finally:
        dcon.close()
    _ph = _cs.publish_catalog_snapshot(staging_dir, manifest=_manifest)
    published_path = str(Path(out) / "catalogs" / _ph.catalog_id / _cs.CATALOG_DB_FILE)
    _ph.close()
    return published_path


def _duplicate_snapshot_config(snapshot_path: str) -> None:
    """Duplicate the single canonical ``seg_config`` row inside the COMPACT snapshot.

    Copies the row under a NEW ``config_id`` keeping the same ``canonical_config_hash``
    (the compact snapshot has only canonical configs — no ``alias_of_config_id``) so the
    preflight's duplicate-identity probe, which reads the SNAPSHOT ``seg_config``, sees an
    unresolved duplicate.  The write connection is closed on exit so the later read-only
    snapshot open in ``_run_single_phase`` is the sole live handle.
    """
    from scripts.embedding_research.catalog_storage import connect as _cat_connect

    with _cat_connect(snapshot_path, read_only=False) as sc:
        src = sc.execute("SELECT * FROM seg_config ORDER BY config_id LIMIT 1").fetchone()
        cols = [c[0] for c in sc.execute("DESCRIBE seg_config").fetchall()]
        dup = dict(zip(cols, src, strict=False))
        dup["config_id"] = int(sc.execute("SELECT COALESCE(MAX(config_id), 0) + 1 FROM seg_config").fetchone()[0])
        dup["run_id"] = "run-dup"
        keys = ", ".join(f'"{c}"' for c in cols)
        ph = ", ".join("?" for _ in cols)
        sc.execute(f"INSERT INTO seg_config ({keys}) VALUES ({ph})", [dup[c] for c in cols])
        assert sc.execute("SELECT count(*) FROM seg_config").fetchone()[0] == 2


def _cfg(out, *, verify: bool, strict: bool) -> dict:
    return {
        "verify": verify,
        "strict": strict,
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


def _latest_prov(con, phase: str):
    return con.execute(
        "SELECT phase, status, warning_count, structural_change_summary "
        "FROM run_provenance WHERE phase = ? ORDER BY started_at DESC LIMIT 1",
        (phase,),
    ).fetchone()


# --------------------------------------------------------------------------- #
# --strict / --verify flag semantics                                          #
# --------------------------------------------------------------------------- #


def test_strict_without_verify_is_rejected():
    with pytest.raises(SystemExit) as exc:
        run_mod._validate_verify_flags(verify=False, strict=True)
    assert exc.value.code == 2
    # the meaningful combinations are all accepted
    for verify, strict in ((True, True), (True, False), (False, False)):
        run_mod._validate_verify_flags(verify=verify, strict=strict)  # no raise


# --------------------------------------------------------------------------- #
# --verify records reuse decisions + warnings in provenance (no new columns)  #
# --------------------------------------------------------------------------- #


def test_verify_run_records_canary_and_reuse_notes(con, tmp_path):
    """A --verify derived run records the canary result + a reuse decision note."""
    _seed_catalog(con, tmp_path / "out")
    run_mod._run_single_phase(con, "catalog-report", _cfg(tmp_path / "out", verify=True, strict=False))

    row = _latest_prov(con, "catalog-report")
    assert row is not None
    assert row[1] == "completed"
    summary = row[3]
    # canary exercised the non-empty PK table (songs) and the empty legacy tables;
    # a clean reuse decision is recorded as a note.
    assert "canary ok:" in summary
    assert "reuse existing verified catalog/analyze inputs" in summary
    assert int(row[2]) >= 1  # each note counted as a warning-level provenance signal
    # provenance fields that were ALWAYS present still carry through.
    full = con.execute(
        "SELECT command_line, software_versions, run_id FROM run_provenance "
        "WHERE phase='catalog-report' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    assert full[0] and full[1] and full[2].startswith("catalog-report-")


def test_verify_warns_not_refuses_when_required_artifact_missing(con, tmp_path):
    """Plain --verify on a consumer with NO catalog records a warning, does not refuse."""
    _seed_songs(con)  # songs present so build_catalog_report has a registry, but NO catalog
    run_mod._run_single_phase(con, "catalog-report", _cfg(tmp_path / "out", verify=True, strict=False))

    row = _latest_prov(con, "catalog-report")
    assert row is not None and row[1] == "completed"  # completed, not refused
    assert "warning: phase 'catalog-report': no canonical catalog" in row[3]


# --------------------------------------------------------------------------- #
# --verify --strict REFUSES on missing/incomplete required artifacts           #
# --------------------------------------------------------------------------- #


def test_strict_refuses_analyze_without_catalog_rows(con, tmp_path):
    """--verify --strict analyze with NO canonical catalog is a hard refusal."""
    _seed_songs(con)  # some state, but the catalog the analyze phase requires is absent
    cfg = _cfg(tmp_path / "out", verify=True, strict=True)

    with pytest.raises(run_mod._MissingArtifactError):
        run_mod._run_single_phase(con, "analyze", cfg)

    # the refusal was recorded as a failed provenance row for the phase.
    row = _latest_prov(con, "analyze")
    assert row is not None and row[1] == "failed"


def test_strict_refuses_report_without_run_scoped_analyze_metrics(con, tmp_path):
    """--verify --strict report: canonical catalog present but NO run-scoped analyze_metrics.

    This is the ONLY untested consumer branch in ``_preflight_derived_phase``: the
    ``phase == "report" and not _has_analyze_metrics`` refusal (run.py L1323-1327).
    ``_seed_catalog`` leaves ``analyze_metrics`` empty, so ``_has_canonical_catalog``
    is True and the report-only branch is reached -> hard refusal.
    """
    _seed_catalog(con, tmp_path / "out")
    cfg = _cfg(tmp_path / "out", verify=True, strict=True)

    with pytest.raises(run_mod._MissingArtifactError) as exc:
        run_mod._run_single_phase(con, "report", cfg)

    assert "no run-scoped analyze_metrics" in str(exc.value)
    # the refusal was recorded as a failed provenance row for the phase.
    row = _latest_prov(con, "report")
    assert row is not None and row[1] == "failed"


def test_verify_report_warns_not_refuses_without_analyze_metrics(con, tmp_path):
    """Plain --verify report with a catalog but NO run-scoped analyze_metrics warns, completes."""
    _seed_catalog(con, tmp_path / "out")
    run_mod._run_single_phase(con, "report", _cfg(tmp_path / "out", verify=True, strict=False))

    row = _latest_prov(con, "report")
    assert row is not None and row[1] == "completed"  # warned, not refused
    assert "no run-scoped analyze_metrics" in row[3]


# --------------------------------------------------------------------------- #
# --verify --strict REFUSES on an unresolved duplicate canonical identity      #
# --------------------------------------------------------------------------- #


def test_strict_refuses_unresolved_duplicate_canonical_config(con, tmp_path):
    """A duplicated canonical config identity (same canonical_config_hash) in the snapshot."""
    snapshot = _seed_catalog(con, tmp_path / "out")
    # Duplicate the single canonical config row under a NEW config_id inside the COMPACT
    # snapshot, keeping the same canonical_config_hash -> an unresolved duplicate.
    _duplicate_snapshot_config(snapshot)

    cfg = _cfg(tmp_path / "out", verify=True, strict=True)
    with pytest.raises(run_mod._DuplicateIdentityError):
        run_mod._run_single_phase(con, "catalog-report", cfg)

    row = _latest_prov(con, "catalog-report")
    assert row is not None and row[1] == "failed"


def test_verify_duplicate_records_warning_not_refusal(con, tmp_path):
    """Plain --verify on the same snapshot duplicate records a warning and does not refuse."""
    snapshot = _seed_catalog(con, tmp_path / "out")
    _duplicate_snapshot_config(snapshot)

    run_mod._run_single_phase(con, "catalog-report", _cfg(tmp_path / "out", verify=True, strict=False))

    row = _latest_prov(con, "catalog-report")
    assert row is not None and row[1] == "completed"  # warned, not refused
    assert "unresolved duplicate canonical config identity" in row[3]
