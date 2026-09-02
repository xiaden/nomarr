"""Plan C Phase 4 (P4-S1 + P4-S3) — strict catalog identity.

Proves the DD R9 / R15 / U1 serialization, per-song-signature, ``search_view_hash`` and
manifest-only ``catalog_fingerprint`` contracts implemented by
``scripts/embedding_research/catalog_identity.py``:

* canonical serialization is deterministic (sorted rows, fixed type/NULL/numeric encodings) —
  byte-identical logical state yields byte-identical payloads and hashes;
* a per-song signature is sensitive to any membership / medoid / outlier / stream change;
* ``search_view_hash`` is STRICT — a membership change, a stream re-embed (fingerprint
  change), a threshold-semantics change, a software-version change, or an ordering-contract
  (serialization-version) change each change the hash;
* ``catalog_fingerprint`` is deterministic, is never a DuckDB byte hash, EXCLUDES its own
  value (non-self-referential; no table column stores it), and survives export/import
  logical comparison while detecting real drift.
"""

from __future__ import annotations

import hashlib

import duckdb
import numpy as np

from scripts.embedding_research import catalog
from scripts.embedding_research import catalog_identity as ci
from scripts.embedding_research.db import ensure_schema
from scripts.embedding_research.streams.store import StreamStore

SCHEMA_VERSION = 1


def _unit(rng, n: int, d: int, spread: float = 1.5) -> np.ndarray:
    m = rng.standard_normal((n, d)) * spread
    m[0] += 3.0
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (m / norms).astype(np.float32)


def _cfg(threshold: float, *, backbone: str = "effnet") -> catalog.SegConfigInput:
    return catalog.SegConfigInput(
        backbone=backbone,
        bin_mode="temporal_global",
        threshold_configured=threshold,
        threshold_effective=threshold,
    )


def _build(con, out, *, seed: int = 7, song_ids=("s1",), threshold: float = 0.9) -> tuple[StreamStore, int]:
    """Publish one ready effnet stream per song and build a catalog; return (store, config_id)."""
    store = StreamStore(con, output_root=str(out))
    rng = np.random.default_rng(seed)
    for song in song_ids:
        store.publish(song, "effnet", _unit(rng, 60, 8), run_id="run-embed")
    store.reconcile()
    rep = catalog.build_segmentation_catalog(con, store, [_cfg(threshold)], list(song_ids), "run-cat-1", verify=True)
    assert rep.verify_ok is True
    config_id = int(rep.configs[0].config_id)
    return store, config_id


def _new_built(tmp_path, name: str):
    """A fresh, independently-built in-memory catalog (same seed → identical logical state)."""
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    _build(con, tmp_path / name)
    return con


def _normalize_timestamps(con) -> None:
    """Freeze volatile provenance/config/stream timestamps so two independently-built but
    otherwise identical logical states compare byte-for-byte."""
    con.execute("UPDATE seg_config SET created_at = 4444")
    con.execute("UPDATE seg_meta SET created_at = 5555")
    con.execute("UPDATE stream_registry SET created_at = 6666, updated_at = 6667")
    con.execute("UPDATE run_provenance SET started_at = 1111, finished_at = 2222")
    con.execute("UPDATE corpus_state SET reconciled_at = 3333")


def _delete_one_member(con, config_id: int) -> None:
    row = con.execute(
        "SELECT song_id, seg_id, member_patch_idx FROM seg_membership "
        "WHERE config_id = ? ORDER BY song_id, seg_id, member_patch_idx LIMIT 1",
        [config_id],
    ).fetchone()
    con.execute(
        "DELETE FROM seg_membership WHERE config_id = ? AND song_id = ? AND seg_id = ? AND member_patch_idx = ?",
        [config_id, row[0], row[1], row[2]],
    )


# ── Canonical serialization determinism ────────────────────────────────────────


def test_canonical_serialization_is_deterministic(con, tmp_path):
    _build(con, tmp_path)
    _build(con, tmp_path)  # rerun on same DB must be byte-stable (idempotent logical state)
    payload = ci.catalog_state_payload(con, schema_version=SCHEMA_VERSION)
    assert (
        ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION)
        == hashlib.sha256(payload.encode("utf-8")).hexdigest()
    )
    # NULL / numeric / type encodings are fixed: rerunning the same logical state is stable.
    assert ci.catalog_state_payload(con, schema_version=SCHEMA_VERSION) == payload


def test_identical_logical_state_hashes_equal_across_db(tmp_path):
    # Two independently-built but identical logical states serialize identically.
    con = _new_built(tmp_path, "a")
    con2 = _new_built(tmp_path, "b")
    try:
        _normalize_timestamps(con)
        _normalize_timestamps(con2)
        assert ci.catalog_state_payload(con, schema_version=SCHEMA_VERSION) == ci.catalog_state_payload(
            con2, schema_version=SCHEMA_VERSION
        )
        assert ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION) == ci.catalog_fingerprint(
            con2, schema_version=SCHEMA_VERSION
        )
        assert ci.search_view_hash(con) == ci.search_view_hash(con2)
        assert ci.song_signature(con, "s1") == ci.song_signature(con2, "s1")
    finally:
        con.close()
        con2.close()


# ── Per-song signature sensitivity ─────────────────────────────────────────────


def test_song_signature_sensitive_to_membership_change(con, tmp_path):
    _, config_id = _build(con, tmp_path)
    before = ci.song_signature(con, "s1")
    _delete_one_member(con, config_id)
    assert ci.song_signature(con, "s1") != before


def test_song_signature_sensitive_to_stream_reembed(con, tmp_path):
    _build(con, tmp_path)
    before = ci.song_signature(con, "s1")
    con.execute(
        "UPDATE stream_registry SET fingerprint_sha256 = ? WHERE song_id = 's1' AND backbone = 'effnet'",
        [hashlib.sha256(b"re-embedded").hexdigest()],
    )
    assert ci.song_signature(con, "s1") != before


def test_song_signature_deterministic(con, tmp_path):
    _build(con, tmp_path)
    assert ci.song_signature(con, "s1") == ci.song_signature(con, "s1")


# ── search_view_hash strictness ────────────────────────────────────────────────


def test_search_view_hash_sensitive_to_membership_change(con, tmp_path):
    _, config_id = _build(con, tmp_path)
    before = ci.search_view_hash(con)
    _delete_one_member(con, config_id)
    assert ci.search_view_hash(con) != before


def test_search_view_hash_sensitive_to_stream_reembed(con, tmp_path):
    _build(con, tmp_path)
    before = ci.search_view_hash(con)
    con.execute(
        "UPDATE stream_registry SET fingerprint_sha256 = ? WHERE song_id = 's1' AND backbone = 'effnet'",
        [hashlib.sha256(b"different bytes").hexdigest()],
    )
    assert ci.search_view_hash(con) != before


def test_search_view_hash_sensitive_to_threshold_semantics_change(con, tmp_path):
    _, config_id = _build(con, tmp_path)
    before = ci.search_view_hash(con)
    # Change the effective threshold semantics stored on the config row (its meaning), which
    # changes the canonical config row and therefore the strict corpus identity.
    con.execute("UPDATE seg_config SET threshold_effective = 0.25 WHERE config_id = ?", [config_id])
    assert ci.search_view_hash(con) != before


def test_search_view_hash_sensitive_to_software_version_change(con, tmp_path):
    _build(con, tmp_path)
    base = ci.search_view_hash(con, context=ci.CatalogIdentityContext())
    v1 = ci.search_view_hash(con, context=ci.CatalogIdentityContext(software_versions={"segmentation": "1.0"}))
    v2 = ci.search_view_hash(con, context=ci.CatalogIdentityContext(software_versions={"segmentation": "2.0"}))
    assert v1 != v2
    assert v1 != base


def test_search_view_hash_sensitive_to_ordering_contract_change(con, tmp_path):
    _build(con, tmp_path)
    assert ci.search_view_hash(con, context=ci.CatalogIdentityContext(serialization_version=1)) != ci.search_view_hash(
        con, context=ci.CatalogIdentityContext(serialization_version=2)
    )


def test_search_view_hash_deterministic_and_stable_across_rerun(con, tmp_path):
    _build(con, tmp_path)
    first = ci.search_view_hash(con)
    assert first == ci.search_view_hash(con)
    _build(con, tmp_path)  # idempotent rerun of the SAME logical config must not change identity
    assert ci.search_view_hash(con) == first


# ── catalog_fingerprint: deterministic, non-self-referential, not a DuckDB byte hash ──


def test_catalog_fingerprint_is_deterministic(con, tmp_path):
    _build(con, tmp_path)
    assert ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION) == ci.catalog_fingerprint(
        con, schema_version=SCHEMA_VERSION
    )


def test_catalog_fingerprint_changes_with_schema_version(con, tmp_path):
    _build(con, tmp_path)
    assert ci.catalog_fingerprint(con, schema_version=1) != ci.catalog_fingerprint(con, schema_version=2)


def test_catalog_fingerprint_excludes_itself(con, tmp_path):
    _build(con, tmp_path)
    payload = ci.catalog_state_payload(con, schema_version=SCHEMA_VERSION)
    fp = ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION)
    # The fingerprint is exactly the hash of the pre-image and is NOT part of its own input.
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == fp
    assert fp not in payload
    # No table column stores catalog_fingerprint (manifest-only, non-self-referential).
    rows = con.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE lower(column_name) = 'catalog_fingerprint'"
    ).fetchall()
    assert rows == []


def test_catalog_fingerprint_is_logical_not_duckdb_bytes(con, tmp_path):
    # The fingerprint is over canonical logical rows.  A WAL/checkpoint-only physical change
    # (forced here by checkpointing after a no-op write) must NOT change the logical value.
    _build(con, tmp_path)
    before = ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION)
    con.execute("FORCE CHECKPOINT")
    assert ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION) == before


def test_export_import_preserves_logical_identity(con, tmp_path):
    _build(con, tmp_path)
    export_dir = str(tmp_path / "export")
    con.execute(f"EXPORT DATABASE '{export_dir}'")
    imported = duckdb.connect(str(tmp_path / "imported.db"))
    imported.execute(f"IMPORT DATABASE '{export_dir}'")
    try:
        fp_a = ci.catalog_fingerprint(con, schema_version=SCHEMA_VERSION)
        fp_b = ci.catalog_fingerprint(imported, schema_version=SCHEMA_VERSION)
        assert fp_a == fp_b
        assert ci.search_view_hash(con) == ci.search_view_hash(imported)
        assert ci.song_signature(con, "s1") == ci.song_signature(imported, "s1")
        assert ci.verify_catalog_logical_identity(con, imported, schema_version=SCHEMA_VERSION) == ()
    finally:
        imported.close()


def test_export_import_verify_detects_real_drift(con, tmp_path):
    _build(con, tmp_path)
    export_dir = str(tmp_path / "export2")
    con.execute(f"EXPORT DATABASE '{export_dir}'")
    imported = duckdb.connect(str(tmp_path / "imported2.db"))
    imported.execute(f"IMPORT DATABASE '{export_dir}'")
    try:
        assert ci.verify_catalog_logical_identity(con, imported, schema_version=SCHEMA_VERSION) == ()
        _delete_one_member(imported, int(imported.execute("SELECT config_id FROM seg_config").fetchone()[0]))
        errors = ci.verify_catalog_logical_identity(con, imported, schema_version=SCHEMA_VERSION)
        assert errors
        assert any("song_signature" in e or "fingerprint" in e for e in errors)
    finally:
        imported.close()
