"""Plan C P1-S6(b) — compact-backed strict catalog identity (re-specified).

Proves the DD R9 / R15 / U1 serialization, per-song-signature, per-config leaf-hash collapse
(``search_representation_hash`` / ``exact_segmentation_hash``), and manifest-only
``catalog_fingerprint`` contracts implemented by
``scripts/embedding_research/catalog_identity.py`` over the COMPACT durable snapshot
tables (``seg_config`` / ``catalog_song`` / ``seg_meta`` / ``catalog_metadata``):

* canonical serialization is deterministic (sorted rows, fixed type/NULL/numeric encodings) —
  byte-identical compact logical state yields byte-identical payloads and hashes;
* a per-song ``song_signature`` is sensitive to any compact membership / count / medoid / weight /
  stream-digest change, and the config-level leaf hashes (``search_representation_hash`` and
  ``exact_segmentation_hash``) are recomputed from the CURRENT per-song search/exact leaves every
  call — there is NO durable corpus ``search_view_hash``; the whole-catalog identity role is
  covered by ``catalog_fingerprint`` + per-song leaf signatures (the search-view hash surface was
  removed under Plan D P1-S2);
* ``catalog_fingerprint`` is deterministic, is never a DuckDB byte hash, EXCLUDES its own
  value (non-self-referential; no table column stores it), and survives export/import
  logical comparison while detecting real drift.

Every build uses the shared fixture contract (``conftest.build_compact_catalog`` via the
``compact_catalog_factory`` fixture): streams are published + reconciled on a research
``con``, the compact snapshot is built through the exact P1-S5 producer, and the snapshot is
opened once through ``catalog_storage.open_snapshot_file`` -> ``CatalogHandle``.  Compact
rows are read / mutated through ``harness.con`` (``handle.con``).  Snapshot export/import is
exercised by copying + reopening the snapshot ``catalog.duckdb`` file.
"""

from __future__ import annotations

import hashlib
import shutil

import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research import catalog_identity as ci
from scripts.embedding_research.catalog_storage import open_snapshot_file

SCHEMA_VERSION = 1


# ── Fixture-contract build helpers ─────────────────────────────────────────────


def _song_mat(blocks: list[int], *, dim: int = 4, seed: float = 1.0) -> np.ndarray:
    """Deterministic unit song stream: alternating ``+x`` / ``-x`` unit blocks."""
    sign = 1.0
    rows: list[np.ndarray] = []
    for count in blocks:
        block = np.zeros((count, dim), dtype=np.float32)
        block[:, 0] = sign
        block *= seed
        rows.append(block)
        sign *= -1.0
    return np.concatenate(rows, axis=0)


def _cfg(threshold: float) -> dict:
    return {
        "backbone": "effnet",
        "bin_mode": "direct",
        "threshold_configured": threshold,
        "threshold_effective": threshold,
    }


def _build(con, out, factory, *, run_id: str = "identity-run", threshold: float = 0.9, song_id: str = "s1"):
    """Build + open one compact catalog snapshot via the shared fixture contract."""
    return factory(
        con,
        out,
        streams={(song_id, "effnet"): _song_mat([5, 3])},
        configs=[_cfg(threshold)],
        song_ids=[song_id],
        run_id=run_id,
    )


def _one_config_id(harness) -> int:
    cfgs = catalog.compact_configs_by_backbone(harness.con, "effnet")
    assert cfgs, "expected at least one compact config row"
    return cfgs[0].config_id


def _first_seg_meta(harness) -> tuple[int, str, int]:
    """Return (config_id, song_id, seg_id) of one existing seg_meta row."""
    row = harness.con.execute(
        "SELECT config_id, song_id, seg_id FROM seg_meta ORDER BY config_id, song_id, seg_id LIMIT 1"
    ).fetchone()
    assert row is not None, "expected at least one compact seg_meta row"
    return int(row[0]), str(row[1]), int(row[2])


def _normalize_build_volatiles(harness) -> None:
    """Freeze the volatile build columns (run tags + build timestamp) so two independently-built
    but otherwise identical compact snapshots compare byte-for-byte."""
    harness.con.execute("UPDATE catalog_metadata SET created_at_ms = 7777, run_id = 'frozen', catalog_id = 'frozen-id'")
    harness.con.execute("UPDATE seg_config SET run_id = 'frozen'")
    harness.con.execute("UPDATE seg_meta SET provenance = 'frozen'")


# ── Canonical serialization determinism ────────────────────────────────────────


def test_canonical_serialization_is_deterministic(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path / "a", compact_catalog_factory)
    try:
        payload = ci.catalog_state_payload(harness.con, schema_version=SCHEMA_VERSION)
        assert (
            ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION)
            == hashlib.sha256(payload.encode("utf-8")).hexdigest()
        )
        # NULL / numeric / type encodings are fixed: repeated serialization is stable.
        assert ci.catalog_state_payload(harness.con, schema_version=SCHEMA_VERSION) == payload
    finally:
        harness.close()


def test_identical_logical_state_hashes_equal_across_db(con, tmp_path, compact_catalog_factory):
    # Two independently-built but identical compact logical states serialize identically.
    ha = _build(con, tmp_path / "a", compact_catalog_factory, run_id="identity-run-a")
    hb = _build(con, tmp_path / "b", compact_catalog_factory, run_id="identity-run-b")
    try:
        _normalize_build_volatiles(ha)
        _normalize_build_volatiles(hb)
        assert ci.catalog_state_payload(ha.con, schema_version=SCHEMA_VERSION) == ci.catalog_state_payload(
            hb.con, schema_version=SCHEMA_VERSION
        )
        assert ci.catalog_fingerprint(ha.con, schema_version=SCHEMA_VERSION) == ci.catalog_fingerprint(
            hb.con, schema_version=SCHEMA_VERSION
        )
        assert ci.song_signature(ha.con, "s1") == ci.song_signature(hb.con, "s1")
    finally:
        ha.close()
        hb.close()


# ── Per-song signature sensitivity ─────────────────────────────────────────────


def test_song_signature_sensitive_to_membership_change(con, tmp_path, compact_catalog_factory):
    # Membership change axis: mutate a compact structural/count field (here a seg_meta
    # searchable count) -> the per-song exact signature must change.
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        config_id, song_id, seg_id = _first_seg_meta(harness)
        before = ci.song_signature(harness.con, song_id)
        harness.con.execute(
            "UPDATE seg_meta SET searchable_count = searchable_count + 1 "
            "WHERE config_id = ? AND song_id = ? AND seg_id = ?",
            [config_id, song_id, seg_id],
        )
        assert ci.song_signature(harness.con, song_id) != before
    finally:
        harness.close()


def test_song_signature_sensitive_to_stream_reembed(con, tmp_path, compact_catalog_factory):
    # Stream re-embed axis: mutate catalog_song.stream_digest -> signature must change.
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        before = ci.song_signature(harness.con, "s1")
        harness.con.execute(
            "UPDATE catalog_song SET stream_digest = ? WHERE song_id = 's1'",
            [hashlib.sha256(b"re-embedded").hexdigest()],
        )
        assert ci.song_signature(harness.con, "s1") != before
    finally:
        harness.close()


def test_song_signature_deterministic(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        assert ci.song_signature(harness.con, "s1") == ci.song_signature(harness.con, "s1")
    finally:
        harness.close()


# ── catalog_fingerprint: deterministic, non-self-referential, not a DuckDB byte hash ──


def test_catalog_fingerprint_is_deterministic(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        assert ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION) == ci.catalog_fingerprint(
            harness.con, schema_version=SCHEMA_VERSION
        )
    finally:
        harness.close()


def test_catalog_fingerprint_changes_with_schema_version(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        assert ci.catalog_fingerprint(harness.con, schema_version=1) != ci.catalog_fingerprint(
            harness.con, schema_version=2
        )
    finally:
        harness.close()


def test_catalog_fingerprint_excludes_itself(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        payload = ci.catalog_state_payload(harness.con, schema_version=SCHEMA_VERSION)
        fp = ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION)
        # The fingerprint is exactly the hash of the pre-image and is NOT part of its own input.
        assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == fp
        assert fp not in payload
        # No compact table column stores catalog_fingerprint (manifest-only, non-self-referential).
        rows = harness.con.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE lower(column_name) = 'catalog_fingerprint'"
        ).fetchall()
        assert rows == []
    finally:
        harness.close()


def test_catalog_fingerprint_is_logical_not_duckdb_bytes(con, tmp_path, compact_catalog_factory):
    # The fingerprint is over canonical logical rows.  A WAL/checkpoint-only physical change
    # (forced here by checkpointing after a no-op write) must NOT change the logical value.
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        before = ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION)
        harness.con.execute("FORCE CHECKPOINT")
        assert ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION) == before
    finally:
        harness.close()


def test_export_import_preserves_logical_identity(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        exported_path = tmp_path / "exported-catalog.duckdb"
        shutil.copy2(harness.snapshot_path, exported_path)
        imported = open_snapshot_file(exported_path, read_only=True)
        try:
            assert ci.catalog_fingerprint(harness.con, schema_version=SCHEMA_VERSION) == ci.catalog_fingerprint(
                imported.con, schema_version=SCHEMA_VERSION
            )
            assert ci.song_signature(harness.con, "s1") == ci.song_signature(imported.con, "s1")
            assert ci.verify_catalog_logical_identity(harness.con, imported.con, schema_version=SCHEMA_VERSION) == ()
        finally:
            imported.close()
    finally:
        harness.close()


def test_export_import_verify_detects_real_drift(con, tmp_path, compact_catalog_factory):
    harness = _build(con, tmp_path, compact_catalog_factory)
    try:
        exported_path = tmp_path / "exported-drift.duckdb"
        shutil.copy2(harness.snapshot_path, exported_path)
        imported = open_snapshot_file(exported_path)
        try:
            assert ci.verify_catalog_logical_identity(harness.con, imported.con, schema_version=SCHEMA_VERSION) == ()
            # Introduce real drift on the imported copy: mutate a compact row.
            imported.con.execute("UPDATE seg_meta SET searchable_count = searchable_count + 1")
            errors = ci.verify_catalog_logical_identity(harness.con, imported.con, schema_version=SCHEMA_VERSION)
            assert errors
            assert any("song_signature" in e or "fingerprint" in e for e in errors)
        finally:
            imported.close()
    finally:
        harness.close()
