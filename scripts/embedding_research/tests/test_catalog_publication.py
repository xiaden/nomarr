"""Compact catalog publication + current-catalog verification (Plan C, P1-S13).

Exercises :func:`catalog_storage.publish_catalog_snapshot` and
:func:`catalog_storage.open_current_catalog` (the DD L268-288 durability contract) plus the
§C handle-form :func:`catalog_report.catalog_report(con, catalog)`.  Self-contained: never
touches audio, models, ONNX, CUDA, or the optimizer; a disposable ``research.duckdb`` is only
created so a test can prove a published snapshot survives its deletion.
"""

from __future__ import annotations

import shutil

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import catalog
from scripts.embedding_research import catalog_storage as cs
from scripts.embedding_research.catalog_identity import catalog_fingerprint
from scripts.embedding_research.catalog_report import catalog_report


class _FakeStreamStore:
    def __init__(self, streams: dict[tuple[str, str], np.ndarray]) -> None:
        self._streams = streams

    def load(self, song_id: str, backbone: str):
        return self._streams.get((song_id, backbone))


class _FakeMaskStore:
    def __init__(self, masks: dict[str, np.ndarray] | None = None) -> None:
        self._masks = masks or {}

    def load(self, song_id: str):
        return self._masks.get(song_id)


def _mat(patch_counts: list[int], *, dim: int = 4, seed: float = 1.0) -> np.ndarray:
    sign = 1.0
    rows: list[np.ndarray] = []
    for count in patch_counts:
        block = np.zeros((count, dim), dtype=np.float32)
        block[:, 0] = sign
        block *= seed
        rows.append(block)
        sign *= -1.0
    return np.concatenate(rows, axis=0)


def _cfg(threshold: float) -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
        backbone="effnet",
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _build(root, run_id: str, *, songs, masks=None, thresholds=(1.0, 0.4)):
    """Build a compact catalog into ``root/catalogs/.staging-<run_id>/`` (no lingering handle)."""
    streams = {(_s, "effnet"): _mat([5, 3] if _s.endswith("1") else [4, 5, 4]) for _s in songs}
    rep = catalog.build_segmentation_catalog(
        _FakeStreamStore(streams),
        _FakeMaskStore(masks),
        [_cfg(t) for t in thresholds],
        list(songs),
        output_root=str(root),
        run_id=run_id,
        verify=True,
    )
    assert rep.verify_ok is True
    return rep


def _staging(root, run_id: str):
    return root / "catalogs" / f".staging-{run_id}"


def _publish(root, run_id: str):
    """Checkpoint/clean-close the staged snapshot, derive its manifest, and publish it."""
    staging = _staging(root, run_id)
    con = duckdb.connect(str(staging / cs.CATALOG_DB_FILE), read_only=True)
    try:
        manifest = cs.derive_catalog_manifest(con)
    finally:
        con.close()
    return cs.publish_catalog_snapshot(staging, manifest=manifest)


def _seg_rows(root, run_id: str, order_by: str):
    con = duckdb.connect(str(_staging(root, run_id) / cs.CATALOG_DB_FILE), read_only=True)
    try:
        cols = cs.SEG_META_COLS
        rows = con.execute(f"SELECT {', '.join(cols)} FROM seg_meta ORDER BY {order_by}").fetchall()
    finally:
        con.close()
    return rows


# ── Publication round-trip ────────────────────────────────────────────────────


def test_publish_and_open_current_round_trip(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-a", songs=["s1", "s2"])
    handle = _publish(root, "run-a")
    cid = handle.catalog_id
    try:
        # staging directory was atomically renamed away; manifest + current.json published.
        assert not _staging(root, "run-a").exists()
        catalog_dir = root / "catalogs" / cid
        assert (catalog_dir / cs.CATALOG_MANIFEST_FILE).is_file()
        assert (catalog_dir / cs.CATALOG_DB_FILE).is_file()
        assert (root / "catalogs" / cs.CATALOG_CURRENT_FILE).is_file()
        import json

        assert json.loads((root / "catalogs" / cs.CATALOG_CURRENT_FILE).read_text()) == {"catalog_id": cid}
    finally:
        handle.close()

    # open_current_catalog opens ONLY the clean current-format catalog, verify on by default.
    opened = cs.open_current_catalog(root, verify=True)
    try:
        assert opened.catalog_id == cid
        assert opened.root == root / "catalogs" / cid
    finally:
        opened.close()
    # And with verify=False (structural refusal only, no digest cross-check).
    opened_fast = cs.open_current_catalog(root, verify=False)
    opened_fast.close()


def test_manifest_records_derived_digests_matching_live_snapshot(tmp_path):
    """The recorded manifest fingerprint/leaf hashes equal a fresh derive over the snapshot."""
    root = tmp_path / "root"
    _build(root, "run-idm", songs=["s1", "s2"])
    handle = _publish(root, "run-idm")
    cid = handle.catalog_id
    handle.close()
    import json

    recorded = json.loads((root / "catalogs" / cid / cs.CATALOG_MANIFEST_FILE).read_text())
    con = duckdb.connect(str(root / "catalogs" / cid / cs.CATALOG_DB_FILE), read_only=True)
    try:
        derived = cs.derive_catalog_manifest(con)
        assert cs.CatalogManifest(**{**derived.to_dict(), "catalog_id": cid}).to_dict() == recorded
    finally:
        con.close()


def test_shuffled_song_input_is_deterministic_content(tmp_path):
    """Same logical inputs in a different song order => same leaf hashes and structural rows."""
    root_a = tmp_path / "rootA"
    root_b = tmp_path / "rootB"
    _build(root_a, "run-det", songs=["s1", "s2"])
    _build(root_b, "run-det", songs=["s2", "s1"])
    a = _seg_rows(root_a, "run-det", ", ".join(cs.SEG_META_COLS))
    b = _seg_rows(root_b, "run-det", ", ".join(cs.SEG_META_COLS))
    assert a == b
    con_a = duckdb.connect(str(_staging(root_a, "run-det") / cs.CATALOG_DB_FILE), read_only=True)
    con_b = duckdb.connect(str(_staging(root_b, "run-det") / cs.CATALOG_DB_FILE), read_only=True)
    try:
        assert cs.snapshot_leaf_hashes(con_a) == cs.snapshot_leaf_hashes(con_b)
        # Distinct exact vs search representation hashes (distinct preimages).
        exact, search = cs.snapshot_leaf_hashes(con_a)
        assert exact != search
    finally:
        con_a.close()
        con_b.close()


def test_root_relative_portability_after_root_move(tmp_path):
    """Catalog stays openable with unchanged identity after the output root moves."""
    root_a = tmp_path / "rootA"
    _build(root_a, "run-port", songs=["s1", "s2"])
    handle = _publish(root_a, "run-port")
    cid = handle.catalog_id
    manifest_bytes = (root_a / "catalogs" / cid / cs.CATALOG_MANIFEST_FILE).read_bytes()
    fingerprint = catalog_fingerprint(handle.con, schema_version=1)
    handle.close()

    # The manifest is root-relative: it must never embed an absolute path.
    assert str(root_a).encode() not in manifest_bytes

    moved = tmp_path / "rootMoved"
    shutil.move(str(root_a), str(moved))
    opened = cs.open_current_catalog(moved, verify=True)
    try:
        assert opened.catalog_id == cid
        assert catalog_fingerprint(opened.con, schema_version=1) == fingerprint
    finally:
        opened.close()


def test_zero_searchable_metadata_only_song_is_published(tmp_path):
    """A song whose mask silences every patch is metadata-only yet still published + reported."""
    root = tmp_path / "root"
    # s2 is fully silent => zero searchable patches => catalog_song.status == metadata_only.
    masks = {"s1": None, "s2": np.zeros(13, dtype=np.uint8)}  # s2 stream is 13 patches
    _build(root, "run-zero", songs=["s1", "s2"], masks=masks)
    handle = _publish(root, "run-zero")
    cid = handle.catalog_id
    handle.close()
    con = duckdb.connect(str(root / "catalogs" / cid / cs.CATALOG_DB_FILE), read_only=True)
    try:
        statuses = {
            str(r[0]): str(r[1])
            for r in con.execute(
                "SELECT song_id, status FROM catalog_song WHERE status = 'metadata_only' ORDER BY song_id"
            ).fetchall()
        }
        assert statuses == {"s2": "metadata_only"}
        # A fully-silent song contributes no seg_meta rows.
        assert con.execute("SELECT count(*) FROM seg_meta").fetchone()[0] > 0
    finally:
        con.close()
    opened = cs.open_current_catalog(root, verify=True)
    try:
        report = catalog_report(opened.con, opened)
        assert report.catalog_fingerprint
        # The fully-silent song surfaces as metadata-only empty_songs for every config.
        empty_songs = {(cid_, song) for cid_, song in report.empty_songs}
        assert empty_songs
        assert all(song == "s2" for (_cid_, song) in empty_songs)
    finally:
        opened.close()


# ── Refusal paths (never rebuild; typed refusals) ─────────────────────────────


def test_open_refuses_when_nothing_published(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(cs.CatalogMissingError):
        cs.open_current_catalog(root)


def test_open_refuses_when_current_points_to_missing_catalog(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-gone", songs=["s1"])
    handle = _publish(root, "run-gone")
    cid = handle.catalog_id
    handle.close()
    # current.json now selects cid but its directory is deleted => incomplete refusal.
    shutil.rmtree(root / "catalogs" / cid)
    with pytest.raises(cs.CatalogIncompleteError):
        cs.open_current_catalog(root)


def test_open_refuses_when_manifest_missing_or_malformed(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-missing", songs=["s1"])
    handle = _publish(root, "run-missing")
    cid = handle.catalog_id
    handle.close()
    manifest = root / "catalogs" / cid / cs.CATALOG_MANIFEST_FILE
    manifest.unlink()
    with pytest.raises(cs.CatalogIncompleteError):
        cs.open_current_catalog(root, verify=True)
    manifest.write_text("{not-json", encoding="utf-8")
    with pytest.raises(cs.CatalogCorruptionError):
        cs.open_current_catalog(root, verify=True)


def test_open_refuses_wal_bearing_snapshot(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-wal", songs=["s1"])
    handle = _publish(root, "run-wal")
    cid = handle.catalog_id
    handle.close()
    wal = root / "catalogs" / cid / f"{cs.CATALOG_DB_FILE}.wal"
    wal.write_bytes(b"not-a-real-wal-but-nonempty")
    with pytest.raises(cs.CatalogWalError):
        cs.open_current_catalog(root, verify=True)


def test_publish_refuses_wal_bearing_staging_and_mismatched_manifest(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-walpub", songs=["s1"])
    staging = _staging(root, "run-walpub")
    (staging / f"{cs.CATALOG_DB_FILE}.wal").write_bytes(b"x")
    con = duckdb.connect(str(staging / cs.CATALOG_DB_FILE), read_only=True)
    try:
        manifest = cs.derive_catalog_manifest(con)
    finally:
        con.close()
    with pytest.raises(cs.CatalogWalError):
        cs.publish_catalog_snapshot(staging, manifest=manifest)
    (staging / f"{cs.CATALOG_DB_FILE}.wal").unlink()
    # A caller-supplied manifest whose digest disagrees with the staged snapshot is refused.
    bad = cs.CatalogManifest(**{**manifest.to_dict(), "catalog_fingerprint": "0" * 64})
    with pytest.raises(cs.CatalogMismatchError):
        cs.publish_catalog_snapshot(staging, manifest=bad)


def test_open_verify_refuses_corrupt_snapshot(tmp_path):
    """Mutating a compact row breaks the recorded fingerprint => verify refuses (never rebuilds)."""
    root = tmp_path / "root"
    _build(root, "run-corrupt", songs=["s1"])
    handle = _publish(root, "run-corrupt")
    cid = handle.catalog_id
    handle.close()
    db = root / "catalogs" / cid / cs.CATALOG_DB_FILE
    con = duckdb.connect(str(db))  # read-write
    try:
        con.execute("UPDATE seg_meta SET searchable_count = searchable_count + 1 WHERE seg_id = 1")
    finally:
        con.close()
    # Live content disagrees with the recorded manifest (catalog_fingerprint drift) -
    # verify raises CatalogMismatchError (publish's analogous drift does the same);
    # CatalogCorruptionError is reserved for structurally corrupt catalogs (malformed
    # current.json/manifest, duplicate metadata, or an underivable manifest).
    with pytest.raises(cs.CatalogMismatchError):
        cs.open_current_catalog(root, verify=True)
    # verify=False still refuses nothing structurally corrupt: it opens (structural check passes).
    opened = cs.open_current_catalog(root, verify=False)
    opened.close()


def test_snapshot_is_self_contained_survives_research_deletion(tmp_path):
    """Open + report work from the snapshot alone after the disposable research DB is deleted."""
    root = tmp_path / "root"
    root.mkdir(parents=True, exist_ok=True)
    research_db = root / "research.duckdb"
    con = duckdb.connect(str(research_db))
    con.execute("CREATE TABLE corpus_state (id INTEGER)")
    con.close()

    _build(root, "run-sc", songs=["s1", "s2"])
    handle = _publish(root, "run-sc")
    cid = handle.catalog_id
    handle.close()
    assert research_db.is_file()
    research_db.unlink()  # disposable DB gone; the published snapshot must still stand alone

    opened = cs.open_current_catalog(root, verify=True)
    try:
        assert opened.catalog_id == cid
        report = catalog_report(opened.con, opened)
        assert report.catalog_fingerprint
        assert report.canonical_config_ids
    finally:
        opened.close()


# ── §C handle-form catalog_report ─────────────────────────────────────────────


def test_catalog_report_handle_form_cpu_only_no_search_view_identity(tmp_path):
    root = tmp_path / "root"
    _build(root, "run-report", songs=["s1", "s2"], thresholds=(0.9, 1.0))
    handle = _publish(root, "run-report")
    cid = handle.catalog_id
    try:
        report = catalog_report(handle.con, handle)
        # Handle linkage + exact/search representation hashes, NO whole-catalog search-view id.
        assert report.catalog_id == cid
        assert report.catalog_root == str(handle.root)
        assert report.exact_hash and report.search_hash and report.exact_hash != report.search_hash
        # The whole-catalog search-view identity is removed (DD L266): the report carries NO
        # ``search_view_hash`` member/surface at all.
        assert not hasattr(report, "search_view_hash")
        # Evidence axes: structural snapshot (observed medoid), outlier/silence, transient alias.
        assert report.config_snapshots
        assert report.membership_row_total > 0
        assert report.alias_count >= 1  # 0.9 vs 1.0 collapse transiently on this stream
        # No optimizer / index state is created by open+report (CPU-only, no audio/model/ONNX).
        assert handle.con.execute("SELECT * FROM duckdb_indexes()").fetchall() == []
    finally:
        handle.close()
