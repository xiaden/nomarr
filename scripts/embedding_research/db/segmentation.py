"""Segmentation-catalog schema vocabulary and application-integrity guards (Plan C Phase 1).

The three catalog tables (``seg_config`` / ``seg_meta`` / ``seg_membership``) are the
PRIMARY segmentation schema (DD R6).  They deliberately carry NO ``PRIMARY KEY`` /
``UNIQUE`` constraint (DuckDB ART/WAL policy in the DD), so application-level integrity
is the ONLY guarantee of uniqueness and referential soundness.  That guarantee lives here,
in application code — never in a database constraint.

What the app asserts (and re-checks after a build) before any commit:

* (a) ``config_id`` is unique across ``seg_config``;
* (b) the canonical config identity (``canonical_config_hash`` over the fixed input
  ordering from ``helpers.thresholds``) is unique among non-aliased configs — two rows with
  the same hash are the SAME logical configuration and must collapse to one ``config_id``;
* (c) a segment identity ``(config_id, song_id, seg_id)`` is unique in ``seg_meta``;
* (d) a membership row ``(config_id, song_id, seg_id, member_patch_idx)`` is unique;
* (e) every ``member_patch_idx`` lies in ``[0, patch_count)`` of the verified frozen source
  stream (the ``status='ready'`` ``stream_registry`` row for that song/backbone);
* (f) no orphaned metadata: a ``seg_meta`` row always has its ``seg_config`` and a
  ``seg_membership`` row always has its ``seg_meta``.

Each guard raises a typed :class:`SegmentationError` subtype so downstream build code
(Phase 3) can distinguish a duplicate-config rerun from a genuine out-of-range member
index without string matching.  Timestamps are INTEGER milliseconds.
"""

from __future__ import annotations

from scripts.embedding_research.streams.records import STREAM_TABLE

__all__ = [
    "SEG_CONFIG_TABLE",
    "SEG_MEMBERSHIP_TABLE",
    "SEG_META_TABLE",
    "SegConfigNotFoundError",
    "SegDuplicateConfigIdError",
    "SegDuplicateMembershipRowError",
    "SegDuplicateSegmentError",
    "SegMemberIndexError",
    "SegOrphanError",
    "SegStreamNotReadyError",
    "SegValidationError",
    "SegmentationError",
    "config_id_exists",
    "config_row",
    "raise_if_canonical_config_duplicate",
    "raise_if_config_id_duplicate",
    "raise_if_member_outside_verified_stream",
    "raise_if_membership_duplicate",
    "raise_if_orphan_membership",
    "raise_if_orphan_seg_meta",
    "raise_if_segment_duplicate",
    "seg_config_columns",
    "seg_config_logical_key_columns",
    "seg_membership_columns",
    "seg_meta_columns",
    "seg_meta_exists",
]

SEG_CONFIG_TABLE = "seg_config"
SEG_META_TABLE = "seg_meta"
SEG_MEMBERSHIP_TABLE = "seg_membership"

#: Exact ``seg_config`` column order (DDL / ledger SegConfigRecord field order).
seg_config_columns: tuple[str, ...] = (
    "config_id",
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "semantics",
    "calibration_record",
    "outlier_window",
    "strategy_version",
    "alias_of_config_id",
    "canonical_config_hash",
    "created_at",
    "run_id",
)

#: The non-hash logical key fields that (together with ``canonical_config_hash``) pin one
#: logical segmentation configuration.  A second row agreeing on all of these IS the same
#: configuration and must collapse to one ``config_id`` rather than multiply.
seg_config_logical_key_columns: tuple[str, ...] = (
    "backbone",
    "bin_mode",
    "threshold_configured",
    "threshold_effective",
    "semantics",
    "calibration_record",
    "outlier_window",
    "strategy_version",
)

#: Exact ``seg_meta`` column order (DDL / ledger SegMetaRecord field order).
seg_meta_columns: tuple[str, ...] = (
    "config_id",
    "song_id",
    "seg_id",
    "start_idx",
    "end_idx",
    "member_count",
    "absorbed_outlier_count",
    "weight",
    "medoid_source_patch_idx",
    "segment_signature",
    "created_at",
)

#: Exact ``seg_membership`` column order (DDL / ledger SegMembershipRecord field order).
seg_membership_columns: tuple[str, ...] = (
    "config_id",
    "song_id",
    "seg_id",
    "member_patch_idx",
    "is_absorbed_outlier",
    "membership_version",
)


class SegmentationError(RuntimeError):
    """Base for all segmentation-catalog application-integrity failures."""


class SegValidationError(SegmentationError):
    """A catalog write violates an application-level input or identity rule."""


class SegDuplicateConfigIdError(SegmentationError):
    """Two ``seg_config`` rows share a ``config_id`` (guarantee (a) violated)."""


class SegDuplicateSegmentError(SegmentationError):
    """Two ``seg_meta`` rows share ``(config_id, song_id, seg_id)`` (guarantee (c))."""


class SegDuplicateMembershipRowError(SegmentationError):
    """Two ``seg_membership`` rows share ``(config_id, song_id, seg_id, member_patch_idx)`` (guarantee (d))."""


class SegMemberIndexError(SegmentationError):
    """A ``member_patch_idx`` is outside the verified frozen source stream (guarantee (e))."""


class SegOrphanError(SegmentationError):
    """A ``seg_meta`` / ``seg_membership`` row references a config or segment that does not exist (guarantee (f))."""


class SegConfigNotFoundError(SegmentationError):
    """No ``seg_config`` row exists for a requested ``config_id``."""


class SegStreamNotReadyError(SegmentationError):
    """No verified ``ready`` source stream exists for the song/backbone a catalog write needs."""


# --------------------------------------------------------------------------- #
# Canonical-identity duplicate rejection                                       #
# --------------------------------------------------------------------------- #
# Two independent duplicate notions, both checked in application code:
#   (a) the same integer ``config_id`` appearing twice, and
#   (b) two configs that are the SAME logical configuration (equal canonical hash over the
#       fixed input ordering) but carrying DIFFERENT integer ids — the DD collapses these
#       to one canonical meaning instead of letting distinct rows multiply.
# Canonical-hash duplicate rejection accepts an ``exclude_config_id`` so a full rebuild of
# the SAME config (delete-then-insert, Phase 3) does not trip over its own pending row.


def config_id_exists(con, config_id: int) -> bool:
    """True when a ``seg_config`` row already carries ``config_id``."""
    row = con.execute(f"SELECT 1 FROM {SEG_CONFIG_TABLE} WHERE config_id = ? LIMIT 1", [config_id]).fetchone()
    return row is not None


def raise_if_config_id_duplicate(con, config_id: int) -> None:
    """Reject (a): raise :class:`SegDuplicateConfigIdError` when ``config_id`` is taken."""
    if config_id_exists(con, config_id):
        raise SegDuplicateConfigIdError(
            f"seg_config already has a row with config_id={config_id!r}; "
            "a config_id must be application-unique (no DB PK/UNIQUE per DuckDB ART/WAL policy)"
        )


def canonical_hash_exists(con, canonical_config_hash: str, *, exclude_config_id: int | None = None) -> bool:
    """True when a non-excluded ``seg_config`` row has ``canonical_config_hash``."""
    if exclude_config_id is None:
        row = con.execute(
            f"SELECT 1 FROM {SEG_CONFIG_TABLE} WHERE canonical_config_hash = ? LIMIT 1",
            [canonical_config_hash],
        ).fetchone()
    else:
        row = con.execute(
            f"SELECT 1 FROM {SEG_CONFIG_TABLE} WHERE canonical_config_hash = ? AND config_id != ? LIMIT 1",
            [canonical_config_hash, exclude_config_id],
        ).fetchone()
    return row is not None


def raise_if_canonical_config_duplicate(
    con, canonical_config_hash: str, *, exclude_config_id: int | None = None
) -> None:
    """Reject (b): a distinct config carrying the same canonical identity already exists.

    Two configs with the same ``canonical_config_hash`` (over ``backbone, bin_mode,
    thresholds, semantics, calibration_record, outlier_window, strategy_version,
    alias_of_config_id``) are the SAME logical configuration and must collapse to one
    ``config_id`` — never be inserted as a second row.  ``exclude_config_id`` permits a
    full rebuild of one and the same config.
    """
    if canonical_hash_exists(con, canonical_config_hash, exclude_config_id=exclude_config_id):
        raise SegDuplicateConfigIdError(
            f"seg_config already holds a DIFFERENT config_id with canonical hash "
            f"{canonical_config_hash!r}; equal canonical identity must collapse to one "
            "config_id, not multiply (no DB PK/UNIQUE per DuckDB ART/WAL policy)"
        )


# --------------------------------------------------------------------------- #
# Segment / membership duplicate rejection                                     #
# --------------------------------------------------------------------------- #


def seg_meta_exists(con, config_id: int, song_id: str, seg_id: int) -> bool:
    """True when a ``seg_meta`` row exists for ``(config_id, song_id, seg_id)``."""
    row = con.execute(
        f"SELECT 1 FROM {SEG_META_TABLE} WHERE config_id = ? AND song_id = ? AND seg_id = ? LIMIT 1",
        [config_id, song_id, seg_id],
    ).fetchone()
    return row is not None


def raise_if_segment_duplicate(con, config_id: int, song_id: str, seg_id: int) -> None:
    """Reject (c): a segment identity already exists in ``seg_meta``."""
    if seg_meta_exists(con, config_id, song_id, seg_id):
        raise SegDuplicateSegmentError(
            f"seg_meta already has a row for (config_id={config_id}, song_id={song_id!r}, "
            f"seg_id={seg_id}); a segment identity must be application-unique within a "
            "config/song (no DB PK/UNIQUE per DuckDB ART/WAL policy)"
        )


def membership_row_exists(con, config_id: int, song_id: str, seg_id: int, member_patch_idx: int) -> bool:
    """True when a ``seg_membership`` row exists for the full row identity."""
    row = con.execute(
        f"SELECT 1 FROM {SEG_MEMBERSHIP_TABLE} "
        "WHERE config_id = ? AND song_id = ? AND seg_id = ? AND member_patch_idx = ? LIMIT 1",
        [config_id, song_id, seg_id, member_patch_idx],
    ).fetchone()
    return row is not None


def raise_if_membership_duplicate(con, config_id: int, song_id: str, seg_id: int, member_patch_idx: int) -> None:
    """Reject (d): a membership row already exists for the full row identity."""
    if membership_row_exists(con, config_id, song_id, seg_id, member_patch_idx):
        raise SegDuplicateMembershipRowError(
            f"seg_membership already has a row for (config_id={config_id}, song_id={song_id!r}, "
            f"seg_id={seg_id}, member_patch_idx={member_patch_idx}); membership rows must be "
            "application-unique (no DB PK/UNIQUE per DuckDB ART/WAL policy)"
        )


# --------------------------------------------------------------------------- #
# Verified-source-stream member-range validation                               #
# --------------------------------------------------------------------------- #


def config_row(con, config_id: int) -> tuple | None:
    """Return the ``seg_config`` row in ``seg_config_columns`` order, else None."""
    return con.execute(
        f"SELECT {', '.join(seg_config_columns)} FROM {SEG_CONFIG_TABLE} WHERE config_id = ? LIMIT 1",
        [config_id],
    ).fetchone()


def _verified_stream_patch_count(con, song_id: str, backbone: str) -> int:
    """Read ``patch_count`` from the ``status='ready'`` stream_registry row."""
    row = con.execute(
        f"SELECT patch_count FROM {STREAM_TABLE} WHERE song_id = ? AND backbone = ? AND status = 'ready' LIMIT 1",
        [song_id, backbone],
    ).fetchone()
    if row is None:
        raise SegStreamNotReadyError(
            f"no verified 'ready' frozen source stream for (song_id={song_id!r}, "
            f"backbone={backbone!r}); a catalog write may only reference an immutable "
            "ready stream (guarantee (e))"
        )
    return int(row[0])


def raise_if_member_outside_verified_stream(con, config_id: int, song_id: str, member_patch_idx: int) -> None:
    """Reject (e): ``member_patch_idx`` must lie in ``[0, patch_count)`` of the ready stream.

    The config's ``backbone`` (seg tables store no backbone) selects the source stream:
    the ``status='ready'`` ``stream_registry`` row for ``(song_id, backbone)``.  Raises
    :class:`SegMemberIndexError` for an out-of-range index, :class:`SegConfigNotFoundError`
    when the config is absent, and :class:`SegStreamNotReadyError` when no ready stream
    exists to validate against.
    """
    cfg = config_row(con, config_id)
    if cfg is None:
        raise SegConfigNotFoundError(
            f"seg_config has no row for config_id={config_id!r}; cannot resolve the "
            "backbone needed to validate a member index"
        )
    cfg_dict = dict(zip(seg_config_columns, cfg, strict=True))
    backbone = cfg_dict["backbone"]
    patch_count = _verified_stream_patch_count(con, song_id, backbone)
    if member_patch_idx < 0 or member_patch_idx >= patch_count:
        raise SegMemberIndexError(
            f"member_patch_idx={member_patch_idx} is outside the verified frozen source "
            f"stream for (song_id={song_id!r}, backbone={backbone!r}, patch_count="
            f"{patch_count}); membership must reference only observed source patches"
        )


# --------------------------------------------------------------------------- #
# Orphan rejection                                                             #
# --------------------------------------------------------------------------- #
# No DB foreign key exists (DuckDB ART/WAL policy), so the app rejects orphaned
# metadata before commit: every seg_meta needs its seg_config; every seg_membership row
# needs its seg_meta (and, transitively, its config).


def raise_if_orphan_seg_meta(con, config_id: int, song_id: str, seg_id: int) -> None:
    """Reject (f)-meta: the ``seg_meta`` row's ``config_id`` must reference an existing config."""
    cfg = config_row(con, config_id)
    if cfg is None:
        raise SegOrphanError(
            f"seg_meta row (config_id={config_id}, song_id={song_id!r}, seg_id={seg_id}) "
            "references a seg_config that does not exist; orphaned segment metadata is rejected"
        )


def raise_if_orphan_membership(con, config_id: int, song_id: str, seg_id: int) -> None:
    """Reject (f)-membership: the membership row's ``(config_id, song_id, seg_id)`` must exist in seg_meta."""
    if not seg_meta_exists(con, config_id, song_id, seg_id):
        raise SegOrphanError(
            f"seg_membership row (config_id={config_id}, song_id={song_id!r}, "
            f"seg_id={seg_id}) references a seg_meta row that does not exist; orphaned "
            "membership rows are rejected"
        )
