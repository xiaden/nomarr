"""P1-S4 cleanup/reset semantics tests (current-format only, byte-preserving Tier 1/2).

These exercise the new ``cleanup_current`` (staging | stray | views) and
``reset_analysis`` on synthetic fixtures — never a real corpus/model/audio.
Candidates are derived from the current-format grammar + manifest relationships
alone; bare/.vN/legacy names are never classified or removed.
"""

from __future__ import annotations

from scripts.embedding_research import cleanup


def _digest_name(song: str, backbone: str, suffix: str, hexlen: int = 64) -> str:
    return f"{song}.{backbone}.{'a' * hexlen}{suffix}"


def _write(root, rel: str, content: bytes = b"x") -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


# ── cleanup_current --scope staging ───────────────────────────────────────────


def test_cleanup_staging_dry_run_default_reports_only(tmp_path):
    d = _write(tmp_path, "catalogs/.staging-run1/catalog.duckdb", b"db")
    t = _write(tmp_path, "streams/.staging/stream.tmp", b"tmp")

    report = cleanup.cleanup_current(tmp_path, None, scope="staging")
    assert report.scope == "staging"
    assert report.dry_run is True
    assert len(report.removed) == 2
    assert d.exists() and t.exists()  # report-only by default


def test_cleanup_staging_removes_when_not_dry_run(tmp_path):
    d = _write(tmp_path, "catalogs/.staging-run1/catalog.duckdb", b"db")
    t = _write(tmp_path, "heads/.staging/head.tmp", b"tmp")

    report = cleanup.cleanup_current(tmp_path, None, scope="staging", dry_run=False)
    assert not d.exists()
    assert not t.exists()
    assert report.changed


def test_cleanup_staging_does_not_touch_published_catalog(tmp_path):
    published = _write(tmp_path, "catalogs/abc123/catalog.duckdb", b"db")
    _write(tmp_path, "catalogs/current.json", b'{"catalog_id": "abc123"}')

    cleanup.cleanup_current(tmp_path, None, scope="staging", dry_run=False)
    assert published.exists()


# ── cleanup_current --scope stray ─────────────────────────────────────────────


def test_cleanup_stray_removes_unreferenced_digest_payload_only(tmp_path):
    stray = _write(tmp_path, f"streams/{_digest_name('s1', 'effnet', '.npy')}", b"data")
    referenced = _write(tmp_path, f"streams/{_digest_name('s2', 'effnet', '.npy')}", b"data")
    _write(tmp_path, f"streams/{_digest_name('s2', 'effnet', '.json')}", b'{"kind": "stream"}')

    report = cleanup.cleanup_current(tmp_path, None, scope="stray", dry_run=False)
    assert not stray.exists()  # orphan digest payload removed
    assert referenced.exists()  # payload with a manifest is current, kept
    assert report.changed


def test_cleanup_stray_never_classifies_non_current_names(tmp_path):
    # A bare/.vN/legacy name is NOT a current-format stray and must never be removed.
    legacy = _write(tmp_path, "streams/s1_effnet_v3.npy", b"legacy")
    bare = _write(tmp_path, "streams/song.npy", b"bare")

    report = cleanup.cleanup_current(tmp_path, None, scope="stray", dry_run=False)
    assert not report.changed
    assert legacy.exists() and bare.exists()


def test_cleanup_stray_removes_unselected_valid_catalog(tmp_path):
    selected = _write(tmp_path, "catalogs/aaa/catalog.duckdb", b"db")
    _write(tmp_path, "catalogs/aaa/catalog.manifest.json", b"{}")
    stray_cat = _write(tmp_path, "catalogs/bbb/catalog.duckdb", b"db")
    _write(tmp_path, "catalogs/bbb/catalog.manifest.json", b"{}")
    _write(tmp_path, "catalogs/current.json", b'{"catalog_id": "aaa"}')

    cleanup.cleanup_current(tmp_path, None, scope="stray", dry_run=False)
    assert selected.exists()
    assert not stray_cat.exists()  # valid but not current -> reported for cleanup


# ── cleanup_current --scope views ─────────────────────────────────────────────


def test_cleanup_views_removes_view_tree(tmp_path):
    v = _write(tmp_path, "views/xyz/payload.npy", b"view")
    report = cleanup.cleanup_current(tmp_path, None, scope="views", dry_run=False)
    assert not v.exists()
    assert not (tmp_path / "views").exists()
    assert report.changed


def test_cleanup_views_dry_run_reports(tmp_path):
    v = _write(tmp_path, "views/xyz/payload.npy", b"view")
    report = cleanup.cleanup_current(tmp_path, None, scope="views", dry_run=True)
    assert v.exists()
    # Nothing is retained-run-protected, so a real run would empty ``views/`` and the report
    # claims both the keyset dir and the parent ``views/`` removal on the simulated post-state.
    assert str(tmp_path / "views" / "xyz") in report.removed
    assert str(tmp_path / "views") in report.removed


def test_cleanup_views_dry_run_protected_parent_not_reported(con, tmp_path):
    """A dry-run views GC with a retained-run-referenced keyset dir must report the protected
    dir as skipped, the unprotected dir as removed, and must NOT claim the parent ``views/``
    removal (a real run would not empty it).  Nothing is deleted in a dry run."""
    root = tmp_path / "root"
    protected_keyset = _hashref("d")
    unprotected_keyset = _hashref("e")
    _seed_view(root, protected_keyset)
    _seed_view(root, unprotected_keyset)
    _write_retained_run(con, view_refs=f"k1|c1|views/{protected_keyset}")

    report = cleanup.cleanup_current(root, con, scope="views", dry_run=True)

    assert str(root / "views" / protected_keyset) in report.skipped
    assert str(root / "views" / unprotected_keyset) in report.removed
    assert str(root / "views") not in report.removed, "views/ survives because a protected dir is kept"
    assert (root / "views" / protected_keyset).is_dir()
    assert (root / "views" / unprotected_keyset).is_dir()


# ── reset_analysis --scope analysis ───────────────────────────────────────────


def _seed_tree(root, db_path):
    root.mkdir(parents=True, exist_ok=True)
    db = _write(root, str(db_path), b"research-duckdb")
    wal = _write(root, f"{db_path}.wal", b"wal")
    view = _write(root, "views/k/p.npy", b"view")
    # Tier 1/2 payloads (must be preserved byte-for-byte)
    tier12 = [
        "corpus/manifest.json",
        "corpus/songs.json",
        "streams/s1.effnet.npy",
        "audio_masks/s1.effnet.npy",
        "heads/s1.effnet.npz",
        "observation_commits/s1.effnet.json",
        "catalogs/current.json",
        "catalogs/aaa/catalog.duckdb",
    ]
    preserved = {rel: _write(root, rel, bytes([i % 251 for i in range(len(rel))])) for rel in tier12}
    return db, wal, view, preserved


def test_reset_analysis_removes_db_and_views_preserves_tier12(tmp_path):
    db_path = tmp_path / "research.duckdb"
    db, wal, view, preserved = _seed_tree(tmp_path, db_path)
    before = {rel: path.read_bytes() for rel, path in preserved.items()}

    report = cleanup.reset_analysis(tmp_path, db_path, dry_run=False)

    assert not db.exists()
    assert not wal.exists()
    assert not view.exists()
    assert report.scope == "analysis"
    for rel, content in before.items():
        assert preserved[rel].read_bytes() == content  # byte-for-byte preserved


def test_reset_analysis_dry_run_removes_nothing(tmp_path):
    db_path = tmp_path / "research.duckdb"
    db, wal, view, _ = _seed_tree(tmp_path, db_path)
    cleanup.reset_analysis(tmp_path, db_path, dry_run=True)
    assert db.exists() and wal.exists() and view.exists()


def test_reset_analysis_missing_db_is_noop(tmp_path):
    db_path = tmp_path / "research.duckdb"
    report = cleanup.reset_analysis(tmp_path, db_path, dry_run=False)
    assert report.removed == []


def _hashref(hexchar: str) -> str:
    return hexchar * 64


def _seed_view(root, keyset: str, rel: str = "payload.npy") -> None:
    _write(root, f"views/{keyset}/{rel}", b"view")


def _write_retained_run(db_con, **extra):
    """Ensure schema on *db_con* and record a retained analyze run referencing a view."""
    from scripts.embedding_research.db import provenance as _prov
    from scripts.embedding_research.db._schema import ensure_schema

    ensure_schema(db_con)
    _prov.write_run_provenance(
        db_con,
        run_id="retained-run",
        phase="analyze",
        status="complete",
        started_at=0,
        finished_at=0,
        retained=True,
        **extra,
    )


def test_cleanup_views_preserves_retained_run_refs_deletes_unretained_run(con, tmp_path):
    """GC may delete only views not referenced by a retained run; protected keyset dirs
    survive and ``views/`` is only removed once empty."""
    root = tmp_path / "root"
    retained_keyset = _hashref("b")
    unretained_keyset = _hashref("a")
    _seed_view(root, retained_keyset)
    _seed_view(root, unretained_keyset)
    from scripts.embedding_research.db import provenance as _prov

    _prov.write_run_provenance(
        con,
        run_id="retained-run",
        phase="analyze",
        status="complete",
        started_at=0,
        finished_at=0,
        retained=True,
        view_refs=f"k1|c1|views/{retained_keyset}",
    )

    report = cleanup.cleanup_current(root, con, scope="views", dry_run=False)

    assert not (root / "views" / unretained_keyset).exists(), "un-retained view must be GC'd"
    assert (root / "views" / retained_keyset).is_dir(), "retained-run-referenced view survives"
    assert str(root / "views" / retained_keyset) in report.skipped
    assert (root / "views").is_dir(), "views/ parent stays because a protected dir survives"


def test_cleanup_views_no_db_deletes_all_views(tmp_path):
    """research.duckdb absent (no conn -> no retained refs): every view is GC-eligible and the
    whole ``views/`` tree is removed."""
    root = tmp_path / "root"
    _seed_view(root, _hashref("a"))
    _seed_view(root, _hashref("b"))

    report = cleanup.cleanup_current(root, None, scope="views", dry_run=False)

    assert not (root / "views").exists()
    assert report.skipped == [], "no DB -> nothing is retained-protected"
    assert report.changed


def test_reset_analysis_removes_views_regardless_of_retention(tmp_path):
    """reset --scope analysis removes research.duckdb + WAL + the whole views/ tree regardless
    of a retained run (retained protection lives only for ``cleanup --scope views``; the
    retained view_refs are deleted along with the research DB)."""
    import duckdb as duckdb_mod

    root = tmp_path / "root"
    db_path = root / "research.duckdb"
    keyset = _hashref("c")
    _seed_view(root, keyset)
    _write(root, "research.duckdb.wal", b"wal")
    # A real research.duckdb holding a retained analyze run that references the view.
    db_con = duckdb_mod.connect(str(db_path))
    try:
        _write_retained_run(db_con, view_refs=f"k1|c1|views/{keyset}")
    finally:
        db_con.close()
    assert (root / "views" / keyset).is_dir()

    report = cleanup.reset_analysis(root, db_path, dry_run=False)

    assert report.removed, "reset must remove the disposable tier"
    assert not db_path.exists(), "research.duckdb removed despite retained run"
    assert not (root / "research.duckdb.wal").exists()
    assert not (root / "views").exists(), "views tree removed regardless of retention"
    assert not (root / "views" / keyset).exists()
