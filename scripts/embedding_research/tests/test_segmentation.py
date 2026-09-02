"""Plan C Phase 1 tests — segmentation-catalog schema and application integrity.

The three catalog tables (``seg_config`` / ``seg_meta`` / ``seg_membership``) carry
deliberately NO ``PRIMARY KEY``/``UNIQUE`` constraint and NO vector/BLOB column (DuckDB
ART/WAL policy in the DD).  All uniqueness and referential soundness therefore live in
application code (``db.segmentation``), which these tests pin down: duplicate config ids,
duplicate canonical config identities, duplicate segment identities, duplicate membership
rows, member indices validated against the verified ``ready`` frozen source stream, and
orphaned metadata rejection.  All tests use an in-memory DuckDB connection.
"""

from __future__ import annotations

import duckdb
import pytest

from scripts.embedding_research.db import (
    SegConfigNotFoundError,
    SegDuplicateConfigIdError,
    SegDuplicateMembershipRowError,
    SegDuplicateSegmentError,
    SegMemberIndexError,
    SegmentationError,
    SegOrphanError,
    SegStreamNotReadyError,
    raise_if_canonical_config_duplicate,
    raise_if_config_id_duplicate,
    raise_if_member_outside_verified_stream,
    raise_if_membership_duplicate,
    raise_if_orphan_membership,
    raise_if_orphan_seg_meta,
    raise_if_segment_duplicate,
)
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.db.segmentation import (
    seg_config_columns,
    seg_membership_columns,
    seg_meta_columns,
)

# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------

SEG_CONFIG_EXPECTED = {
    "config_id": "INTEGER",
    "backbone": "VARCHAR",
    "bin_mode": "VARCHAR",
    "threshold_configured": "DOUBLE",
    "threshold_effective": "DOUBLE",
    "semantics": "VARCHAR",
    "calibration_record": "VARCHAR",
    "outlier_window": "INTEGER",
    "strategy_version": "INTEGER",
    "alias_of_config_id": "INTEGER",
    "canonical_config_hash": "VARCHAR",
    "created_at": "BIGINT",
    "run_id": "VARCHAR",
}

SEG_META_EXPECTED = {
    "config_id": "INTEGER",
    "song_id": "VARCHAR",
    "seg_id": "INTEGER",
    "start_idx": "INTEGER",
    "end_idx": "INTEGER",
    "member_count": "INTEGER",
    "absorbed_outlier_count": "INTEGER",
    "weight": "INTEGER",
    "medoid_source_patch_idx": "INTEGER",
    "segment_signature": "VARCHAR",
    "created_at": "BIGINT",
}

SEG_MEMBERSHIP_EXPECTED = {
    "config_id": "INTEGER",
    "song_id": "VARCHAR",
    "seg_id": "INTEGER",
    "member_patch_idx": "INTEGER",
    "is_absorbed_outlier": "BOOLEAN",
    "membership_version": "INTEGER",
}


@pytest.fixture
def con():
    c = duckdb.connect(":memory:")
    ensure_schema(c)
    yield c
    c.close()


def _columns(con, table: str) -> dict:
    rows = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_name = ? AND table_schema = 'main' ORDER BY ordinal_position",
        [table],
    ).fetchall()
    return dict(rows)


def _constraint_types(con, table: str) -> list[str]:
    rows = con.execute("SELECT constraint_type FROM duckdb_constraints() WHERE table_name = ?", [table]).fetchall()
    return [r[0] for r in rows]


def _insert_config(
    con,
    *,
    config_id: int = 1,
    backbone: str = "effnet",
    bin_mode: str = "temporal_global",
    threshold_configured: float = 1.0,
    threshold_effective: float = 1.0,
    semantics: str = "direct_l2",
    calibration_record: str = "none",
    outlier_window: int = 3,
    strategy_version: int = 1,
    alias_of_config_id: int | None = None,
    canonical_config_hash: str = "hash-cfg-1",
    created_at: int = 0,
    run_id: str = "run-1",
) -> None:
    con.execute(
        f"INSERT INTO seg_config ({', '.join(seg_config_columns)}) VALUES "
        f"({', '.join('?' for _ in seg_config_columns)})",
        [
            config_id,
            backbone,
            bin_mode,
            threshold_configured,
            threshold_effective,
            semantics,
            calibration_record,
            outlier_window,
            strategy_version,
            alias_of_config_id,
            canonical_config_hash,
            created_at,
            run_id,
        ],
    )


def _insert_seg_meta(con, *, config_id: int = 1, song_id: str = "s1", seg_id: int = 0) -> None:
    con.execute(
        f"INSERT INTO seg_meta ({', '.join(seg_meta_columns)}) VALUES ({', '.join('?' for _ in seg_meta_columns)})",
        [
            config_id,
            song_id,
            seg_id,
            0,  # start_idx
            2,  # end_idx
            3,  # member_count
            0,  # absorbed_outlier_count
            3,  # weight
            1,  # medoid_source_patch_idx
            "sig",  # segment_signature
            0,  # created_at
        ],
    )


def _insert_membership(
    con, *, config_id: int = 1, song_id: str = "s1", seg_id: int = 0, member_patch_idx: int = 0
) -> None:
    con.execute(
        f"INSERT INTO seg_membership ({', '.join(seg_membership_columns)}) VALUES "
        f"({', '.join('?' for _ in seg_membership_columns)})",
        [config_id, song_id, seg_id, member_patch_idx, False, 1],
    )


def _insert_ready_stream(con, *, song_id: str, backbone: str, patch_count: int) -> None:
    """Insert a verified ``status='ready'`` stream_registry row (raw SQL, no file I/O)."""
    con.execute(
        "INSERT INTO stream_registry ("
        "song_id, backbone, artifact_ref, patch_count, dim, dtype, format_version, "
        "fingerprint_sha256, preprocess_fn, preprocess_version, backbone_model_hash, "
        "audio_params, embed_semantics_version, provenance_source, provenance_assumption, "
        "status, run_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            song_id,
            backbone,
            f"{song_id}.{backbone}.npy",
            patch_count,
            16,
            "float32",
            1,
            "a" * 64,
            "",
            "",
            "",
            "",
            1,
            "test",
            "synthetic",
            "ready",
            "run-stream",
            0,
            0,
        ],
    )


# ---------------------------------------------------------------------------
# Schema: columns, scalar-only, no PK/UNIQUE/index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        ("seg_config", SEG_CONFIG_EXPECTED),
        ("seg_meta", SEG_META_EXPECTED),
        ("seg_membership", SEG_MEMBERSHIP_EXPECTED),
    ],
)
def test_seg_table_columns_and_types(con, table, expected):
    assert _columns(con, table) == expected


@pytest.mark.parametrize("table", ["seg_config", "seg_meta", "seg_membership"])
def test_seg_table_has_no_pk_or_unique_constraint(con, table):
    types = _constraint_types(con, table)
    assert "PRIMARY KEY" not in types
    assert "UNIQUE" not in types
    # Only NOT NULL guards may exist (DuckDB ART/WAL policy — integrity is app-level).
    assert set(types) <= {"NOT NULL"}


@pytest.mark.parametrize("table", ["seg_config", "seg_meta", "seg_membership"])
def test_seg_table_has_no_vector_or_blob_column(con, table):
    blob_or_vector = {c for c, t in _columns(con, table).items() if "BLOB" in t or t in {"ARRAY", "FLOAT[]"}}
    assert blob_or_vector == set()


@pytest.mark.parametrize("table", ["seg_config", "seg_meta", "seg_membership"])
def test_seg_table_has_no_art_index(con, table):
    rows = con.execute("SELECT index_name, is_unique FROM duckdb_indexes() WHERE table_name = ?", [table]).fetchall()
    assert rows == []


def test_seg_config_nullable_optional_columns(con):
    """``alias_of_config_id`` (unaliased) and ``segment_signature`` are nullable by design."""
    # seg_config allows a NULL alias (no PK/UNIQUE); seg_meta allows a NULL signature.
    _insert_config(con, alias_of_config_id=None)
    assert con.execute("SELECT alias_of_config_id FROM seg_config").fetchone()[0] is None
    _insert_seg_meta(con, config_id=1)
    assert con.execute("SELECT segment_signature FROM seg_meta").fetchone()[0] == "sig"
    con.execute("DELETE FROM seg_meta")
    con.execute(
        "INSERT INTO seg_meta (config_id, song_id, seg_id, start_idx, end_idx, member_count, "
        "absorbed_outlier_count, weight, medoid_source_patch_idx, segment_signature, created_at) "
        "VALUES (1, 's1', 0, 0, 2, 3, 0, 3, 1, NULL, 0)"
    )
    assert con.execute("SELECT segment_signature FROM seg_meta").fetchone()[0] is None


# ---------------------------------------------------------------------------
# (a) config_id duplicate rejection
# ---------------------------------------------------------------------------


def test_duckdb_allows_duplicate_config_id_rows(con):
    """No DB constraint stops a second row with the same config_id — the app guard must."""
    _insert_config(con, config_id=7, canonical_config_hash="h1")
    _insert_config(con, config_id=7, canonical_config_hash="h2")
    rows = con.execute("SELECT count(*) FROM seg_config WHERE config_id = 7").fetchone()[0]
    assert rows == 2


def test_raise_if_config_id_duplicate_rejects_taken_id(con):
    _insert_config(con, config_id=3)
    with pytest.raises(SegDuplicateConfigIdError):
        raise_if_config_id_duplicate(con, 3)
    # A fresh id passes the guard.
    raise_if_config_id_duplicate(con, 4)


# ---------------------------------------------------------------------------
# (b) canonical config identity duplicate rejection
# ---------------------------------------------------------------------------


def test_raise_if_canonical_config_duplicate_rejects_equal_hash(con):
    _insert_config(con, config_id=1, canonical_config_hash="same")
    with pytest.raises(SegDuplicateConfigIdError):
        raise_if_canonical_config_duplicate(con, "same")


def test_raise_if_canonical_config_duplicate_accepts_distinct_hash(con):
    _insert_config(con, config_id=1, canonical_config_hash="one")
    raise_if_canonical_config_duplicate(con, "two")


def test_raise_if_canonical_config_duplicate_excludes_own_rebuild(con):
    """A full rebuild of the SAME config (delete-then-insert) must not trip its own hash."""
    _insert_config(con, config_id=1, canonical_config_hash="same")
    raise_if_canonical_config_duplicate(con, "same", exclude_config_id=1)
    with pytest.raises(SegDuplicateConfigIdError):
        raise_if_canonical_config_duplicate(con, "same", exclude_config_id=2)


# ---------------------------------------------------------------------------
# (c) segment-identity duplicate rejection
# ---------------------------------------------------------------------------


def test_raise_if_segment_duplicate_rejects_existing_identity(con):
    _insert_seg_meta(con, config_id=1, song_id="s1", seg_id=0)
    with pytest.raises(SegDuplicateSegmentError):
        raise_if_segment_duplicate(con, 1, "s1", 0)
    # Same seg_id under a different song is a distinct segment.
    raise_if_segment_duplicate(con, 1, "s2", 0)


# ---------------------------------------------------------------------------
# (d) membership-row duplicate rejection
# ---------------------------------------------------------------------------


def test_raise_if_membership_duplicate_rejects_existing_row(con):
    _insert_membership(con, config_id=1, song_id="s1", seg_id=0, member_patch_idx=4)
    with pytest.raises(SegDuplicateMembershipRowError):
        raise_if_membership_duplicate(con, 1, "s1", 0, 4)
    # The same patch index in a different segment is a distinct membership row.
    raise_if_membership_duplicate(con, 1, "s1", 1, 4)


# ---------------------------------------------------------------------------
# (e) member index validated against the verified ready source stream
# ---------------------------------------------------------------------------


def test_member_index_within_ready_stream_passes(con):
    _insert_config(con, config_id=1, backbone="effnet")
    _insert_ready_stream(con, song_id="s1", backbone="effnet", patch_count=8)
    raise_if_member_outside_verified_stream(con, 1, "s1", 0)
    raise_if_member_outside_verified_stream(con, 1, "s1", 7)


@pytest.mark.parametrize("bad_idx", [-1, 8, 100])
def test_member_index_out_of_range_raises(con, bad_idx):
    _insert_config(con, config_id=1, backbone="effnet")
    _insert_ready_stream(con, song_id="s1", backbone="effnet", patch_count=8)
    with pytest.raises(SegMemberIndexError):
        raise_if_member_outside_verified_stream(con, 1, "s1", bad_idx)


def test_member_index_validation_requires_existing_config(con):
    _insert_ready_stream(con, song_id="s1", backbone="effnet", patch_count=8)
    with pytest.raises(SegConfigNotFoundError):
        raise_if_member_outside_verified_stream(con, 99, "s1", 0)


def test_member_index_validation_requires_ready_stream(con):
    # A 'pending' (not 'ready') row is NOT a verifiable frozen source stream.
    _insert_config(con, config_id=1, backbone="effnet")
    _insert_ready_stream(con, song_id="s1", backbone="effnet", patch_count=8)
    con.execute("UPDATE stream_registry SET status = 'pending' WHERE song_id = 's1'")
    with pytest.raises(SegStreamNotReadyError):
        raise_if_member_outside_verified_stream(con, 1, "s1", 0)


def test_member_index_validation_uses_config_backbone(con):
    """The ready stream must match the CONFIG's backbone, not a different backbone."""
    _insert_config(con, config_id=1, backbone="effnet")
    _insert_ready_stream(con, song_id="s1", backbone="musicnn", patch_count=8)
    with pytest.raises(SegStreamNotReadyError):
        raise_if_member_outside_verified_stream(con, 1, "s1", 0)


# ---------------------------------------------------------------------------
# (f) orphaned metadata rejection
# ---------------------------------------------------------------------------


def test_raise_if_orphan_seg_meta_rejects_missing_config(con):
    with pytest.raises(SegOrphanError):
        raise_if_orphan_seg_meta(con, 99, "s1", 0)


def test_raise_if_orphan_seg_meta_passes_with_config(con):
    _insert_config(con, config_id=1)
    raise_if_orphan_seg_meta(con, 1, "s1", 0)


def test_raise_if_orphan_membership_rejects_missing_seg_meta(con):
    _insert_config(con, config_id=1)
    with pytest.raises(SegOrphanError):
        raise_if_orphan_membership(con, 1, "s1", 0)


def test_raise_if_orphan_membership_passes_with_seg_meta(con):
    _insert_config(con, config_id=1)
    _insert_seg_meta(con, config_id=1, song_id="s1", seg_id=0)
    raise_if_orphan_membership(con, 1, "s1", 0)


# ---------------------------------------------------------------------------
# Exception hierarchy consistency
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [
        SegDuplicateConfigIdError,
        SegDuplicateMembershipRowError,
        SegDuplicateSegmentError,
        SegMemberIndexError,
        SegOrphanError,
        SegConfigNotFoundError,
        SegStreamNotReadyError,
    ],
)
def test_catalog_exceptions_share_segmentation_base(exc):
    assert issubclass(exc, SegmentationError)
    assert issubclass(exc, RuntimeError)
