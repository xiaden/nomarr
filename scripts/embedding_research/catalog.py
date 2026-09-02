"""One-pass multi-threshold segmentation catalog build + bounded lookups (Plan C, Phase 3).

This is the *catalog orchestrator*: it fans the pure, deterministic segmentation
(``helpers/segmentation.py``) out into the ``seg_config`` / ``seg_meta`` /
``seg_membership`` rows that Phase 1's schema/integrity layer (``db/segmentation.py``)
and Phase 2's exact-membership/observed-medoid map define.

The DD R8 one-pass contract, implemented here:

* Each eligible ``(song, backbone)`` frozen stream is loaded **once** per build pass
  (via ``StreamStore.lookup`` + ``StreamStore.batch_gather``) and that single loaded,
  row-L2-normalised matrix is shared by **every** explicit-or-generated threshold
  configuration whose ``bin_mode``/``backbone`` selects it — so per-song work is
  ``O(P_s * D + T * P_s)`` with one stream read, never one read per threshold.
* Membership rows are written per ``(config_id, song_id, seg_id, member_patch_idx)``
  from the authoritative segments, plus ``medoid_source_patch_idx`` (observed index,
  never a vector), and the Phase-2 ``segment_signature``.
* No calibration / optimizer / audio discovery / ONNX / CUDA is invoked anywhere on
  this code path (the build is pure DuckDB + numpy over ready frozen streams).

Rebuild / identity / transaction semantics (P3-S2):

* ``config_id`` is application-allocated (the Phase 1 guards own uniqueness).  A
  config that already exists under the same ``canonical_config_hash`` reuses its id;
  a genuinely new logical config allocates ``max(config_id) + 1``.  No second
  ``seg_config`` row is ever created for the same logical configuration.
* A config's prior ``seg_meta`` / ``seg_membership`` rows are replaced with a
  ``DELETE ... WHERE config_id = ?`` **only** for that config — never broader, never
  a table-wide truncate.  Reruns therefore never accumulate duplicate rows, a
  single-config rebuild touches exactly one ``config_id``, a full rebuild (pass all
  configs) clears+recreates every config in scope, and unrelated configs are preserved.
* Membership + meta for **one song** are written atomically in one transaction.
  A partial (song, config) failure records a per-song/per-config status on the report
  and processing continues; it never leaves a silent half-write.

Bounded lookups (P3-S3) are named contracts realized with equality-filtered per-song /
per-config queries over a one-time in-memory map of the build's config set — no new
DuckDB ``CREATE INDEX`` (ordinary 1.x indexes are ART structures and would reopen the
reviewed crash/churn surface).  Phase 4 consumes :class:`CatalogBuildReport` and the
record types defined here.

Timestamps are INTEGER milliseconds (project convention).
"""

from __future__ import annotations

import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from scripts.embedding_research.db import segmentation as _seg
from scripts.embedding_research.helpers.binning import DIST_FNS
from scripts.embedding_research.helpers.segmentation import (
    MembershipSegment,
    authoritative_segmentation,
    validate_full_partition,
)
from scripts.embedding_research.helpers.thresholds import (
    DEFAULT_OUTLIER_WINDOW,
    PTC_STRATEGY_VERSION,
    ThresholdResolution,
    canonical_calibration_record,
    canonical_config_hash,
    validate_semantics,
)
from scripts.embedding_research.streams.records import (
    STREAM_REGISTRY_COLUMNS,
    STREAM_TABLE,
    StreamNotFoundError,
    StreamNotReadyError,
    StreamRecord,
    now_ms,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ARITHMETIC_SIZING_NOTE",
    "CATALOG_MEMBERSHIP_VERSION",
    "CATALOG_PHASE",
    "CatalogBuildReport",
    "CatalogError",
    "CatalogValidationError",
    "CatalogVerificationError",
    "ConfigBuildOutcome",
    "SegConfigInput",
    "SegConfigRecord",
    "SegMembershipRecord",
    "SegMetaRecord",
    "build_segmentation_catalog",
    "configs_by_backbone",
    "membership_by_config_song_seg",
    "segments_by_config_song",
    "stream_by_song_backbone",
]

#: Provenance ``phase`` label this build writes (Plan C owns run_provenance usage on the
#: same tables Plan B created — it never recreates them).
CATALOG_PHASE = "catalog"
#: The membership-relation contract version persisted into ``seg_membership.membership_version``.
CATALOG_MEMBERSHIP_VERSION: int = 1

#: The planning-surface sizing note.  This is ARITHMETIC SIZING (~10,000 songs x ~100
#: patches x ~10 configs ≈ 10M catalog rows), explicitly NOT an empirical corpus claim.
ARITHMETIC_SIZING_NOTE = (
    "~10,000 songs x ~100 patches x ~10 configs ~ 10M catalog rows (ARITHMETIC SIZING, "
    "not an empirical claim); per-song work O(P_s*D + T*P_s) with one stream load per "
    "(song, backbone), thresholds sharing the pass."
)


class CatalogError(RuntimeError):
    """Base for catalog build/lookup failures."""


class CatalogValidationError(CatalogError):
    """The build inputs (configs / songs / run) are invalid for a catalog pass."""


class CatalogVerificationError(CatalogError):
    """A ``verify=True`` post-build check found catalog rows inconsistent with intent."""


# --------------------------------------------------------------------------- #
# Catalog value objects / records                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class SegConfigInput:
    """A logical threshold configuration to be built (an explicit or generated member).

    This is the *build input* descriptor — it carries no ``config_id`` (the application
    allocates that, reusing an existing id when the same ``canonical_config_hash`` is
    already present).  Fields mirror the ``seg_config`` logical key (the canonical
    identity inputs from ``helpers.thresholds``).  ``threshold_effective`` is the value
    actually applied during segmentation (== ``threshold_configured`` for ``direct_l2``).
    """

    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    semantics: str = "direct_l2"
    calibration_record: Mapping[str, object] | None = None
    outlier_window: int = DEFAULT_OUTLIER_WINDOW
    strategy_version: int = PTC_STRATEGY_VERSION
    alias_of_config_id: int | None = None

    def __post_init__(self) -> None:
        validate_semantics(self.semantics)
        if self.bin_mode not in DIST_FNS:
            raise CatalogValidationError(f"unknown bin_mode {self.bin_mode!r}; supported: {sorted(DIST_FNS)}")
        if not isinstance(self.backbone, str) or not self.backbone.strip():
            raise CatalogValidationError("backbone must be non-empty text")
        for name in ("threshold_configured", "threshold_effective"):
            value = float(getattr(self, name))
            if not math.isfinite(value):
                raise CatalogValidationError(f"{name} must be finite; got {value!r}")
        if int(self.outlier_window) < 1:
            raise CatalogValidationError("outlier_window must be >= 1")

    @classmethod
    def from_resolution(
        cls,
        *,
        backbone: str,
        bin_mode: str,
        resolution: ThresholdResolution,
        outlier_window: int = DEFAULT_OUTLIER_WINDOW,
        strategy_version: int = PTC_STRATEGY_VERSION,
    ) -> SegConfigInput:
        """Build a config from a resolved threshold (configured/effective both recorded)."""
        return cls(
            backbone=backbone,
            bin_mode=bin_mode,
            threshold_configured=resolution.configured,
            threshold_effective=resolution.effective,
            semantics=resolution.semantics,
            calibration_record=dict(resolution.calibration_record)
            if resolution.calibration_record is not None
            else None,
            outlier_window=outlier_window,
            strategy_version=strategy_version,
        )

    def canonical_hash(self) -> str:
        """The deterministic sha256 canonical identity over the seg_config key ordering."""
        return canonical_config_hash(
            backbone=self.backbone,
            bin_mode=self.bin_mode,
            threshold_configured=self.threshold_configured,
            threshold_effective=self.threshold_effective,
            semantics=self.semantics,
            calibration_record=self.calibration_record,
            outlier_window=self.outlier_window,
            strategy_version=self.strategy_version,
            alias_of_config_id=self.alias_of_config_id,
        )


@dataclass(frozen=True)
class SegConfigRecord:
    """One ``seg_config`` row (config id + canonical identity + provenance)."""

    config_id: int
    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    semantics: str
    calibration_record: str
    outlier_window: int
    strategy_version: int
    alias_of_config_id: int | None
    canonical_config_hash: str
    created_at: int
    run_id: str

    @classmethod
    def from_row(cls, row: Sequence[object]) -> SegConfigRecord:
        # values is dict[str, object] keyed by seg_config_columns: The DuckDB row returns each
        # per-column value typed as object, so a **-expansion into cls's typed fields exposes an
        # arg-type mismatch statically.  The per-column runtime types match the record fields by
        # construction (seg_config_columns is emitted in the same fixed order as the dataclass
        # fields), so the narrowing is intentional and the ignore is scoped to arg-type only.
        values = dict(zip(_seg.seg_config_columns, row, strict=True))
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SegMetaRecord:
    """One ``seg_meta`` row (structural ranges + exact counts + observed medoid)."""

    config_id: int
    song_id: str
    seg_id: int
    start_idx: int
    end_idx: int
    member_count: int
    absorbed_outlier_count: int
    weight: int
    medoid_source_patch_idx: int
    segment_signature: str
    created_at: int

    @classmethod
    def from_row(cls, row: Sequence[object]) -> SegMetaRecord:
        # values is dict[str, object] keyed by seg_meta_columns: The DuckDB row returns each
        # per-column value typed as object, so a **-expansion into cls's typed fields exposes an
        # arg-type mismatch statically.  The per-column runtime types match the record fields by
        # construction (seg_meta_columns is emitted in the same fixed order as the dataclass
        # fields), so the narrowing is intentional and the ignore is scoped to arg-type only.
        values = dict(zip(_seg.seg_meta_columns, row, strict=True))
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class SegMembershipRecord:
    """One ``seg_membership`` row (the authoritative per-member relation)."""

    config_id: int
    song_id: str
    seg_id: int
    member_patch_idx: int
    is_absorbed_outlier: bool
    membership_version: int

    @classmethod
    def from_row(cls, row: Sequence[object]) -> SegMembershipRecord:
        # values is dict[str, object] keyed by seg_membership_columns: The DuckDB row returns
        # each per-column value typed as object, so a **-expansion into cls's typed fields
        # exposes an arg-type mismatch statically.  The per-column runtime types match the
        # record fields by construction (seg_membership_columns is emitted in the same fixed
        # order as the dataclass fields), so the narrowing is intentional and the ignore is
        # scoped to arg-type only.
        values = dict(zip(_seg.seg_membership_columns, row, strict=True))
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ConfigBuildOutcome:
    """Per-config result of one catalog build pass (consumed by Phase 4 reports).

    ``songs_eligible`` is how many requested songs had a READY stream for this config's
    backbone (and were therefore actually built-or-attempted); ``excluded_songs`` is the
    number of requested songs for this backbone that were silently excluded for lacking
    a ready stream (never a failure).  ``songs_eligible + excluded_songs`` equals the
    report-level caller-requested count (``CatalogBuildReport.songs_requested``).
    """

    config_id: int
    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    semantics: str
    canonical_config_hash: str
    songs_eligible: int
    excluded_songs: int
    songs_completed: int
    failed_songs: tuple[str, ...]
    total_segments: int
    total_membership_rows: int
    status: str  # "complete" | "partial" | "empty"


@dataclass(frozen=True)
class CatalogBuildReport:
    """Result of :func:`build_segmentation_catalog`.

    Carries per-config outcomes (ids / canonical hashes / per-song completion counts /
    failed songs) for Phase 4 ``catalog-report`` structural-change and medoid-change
    summaries, the arithmetic sizing note, and the one-load-per-song evidence proving
    the R8 one-pass contract.  Timestamps are integer milliseconds.
    """

    run_id: str
    status: str  # "complete" | "partial"
    configs: tuple[ConfigBuildOutcome, ...]
    songs_requested: int
    songs_built: int  # distinct (song, backbone) streams actually loaded+processed
    stream_loads: int  # distinct (song, backbone) stream loads performed
    load_evidence: tuple[tuple[str, str, int], ...]  # (song, backbone, load_count == 1)
    total_segments: int
    total_membership_rows: int
    arithmetic_sizing_note: str
    verification_errors: tuple[str, ...] = ()
    started_at: int = 0
    finished_at: int = 0

    @property
    def verify_ok(self) -> bool:
        """No catalog-row verification errors recorded (always True when ``verify=False``)."""
        return not self.verification_errors


# --------------------------------------------------------------------------- #
# Build helpers                                                               #
# --------------------------------------------------------------------------- #


def _l2_normalize_rows(patches: np.ndarray) -> np.ndarray:
    """Row L2-normalise a ``[P_s, D]`` float32 matrix (unit-normalised, vector-free).

    Zero rows are preserved as-is (a real frozen stream never contains one; the guard
    only prevents a NaN from a divide-by-zero).  Returns a float32 copy.
    """
    arr = np.asarray(patches, dtype=np.float32)
    if arr.ndim != 2:
        raise CatalogValidationError(f"stream must be 2-D [P_s, D]; got shape {arr.shape}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (arr / norms).astype(np.float32, copy=False)


def _insert_config_row(
    con,
    cfg: SegConfigInput,
    config_id: int,
    *,
    run_id: str,
    created_at: int,
) -> None:
    """Insert one ``seg_config`` row with named columns (app id already allocated)."""
    values = {
        "config_id": int(config_id),
        "backbone": cfg.backbone,
        "bin_mode": cfg.bin_mode,
        "threshold_configured": float(cfg.threshold_configured),
        "threshold_effective": float(cfg.threshold_effective),
        "semantics": cfg.semantics,
        "calibration_record": canonical_calibration_record(cfg.calibration_record),
        "outlier_window": int(cfg.outlier_window),
        "strategy_version": int(cfg.strategy_version),
        "alias_of_config_id": cfg.alias_of_config_id,
        "canonical_config_hash": cfg.canonical_hash(),
        "created_at": int(created_at),
        "run_id": run_id,
    }
    cols = ", ".join(_seg.seg_config_columns)
    ph = ", ".join(f"${c}" for c in _seg.seg_config_columns)
    con.execute(f"INSERT INTO {_seg.SEG_CONFIG_TABLE} ({cols}) VALUES ({ph})", values)


def _existing_config_id(con, canonical_hash: str) -> int | None:
    """Return the ``config_id`` of an existing row with *canonical_hash*, else None."""
    row = con.execute(
        f"SELECT config_id FROM {_seg.SEG_CONFIG_TABLE} WHERE canonical_config_hash = ? LIMIT 1",
        [canonical_hash],
    ).fetchone()
    return int(row[0]) if row is not None else None


def _next_config_id(con) -> int:
    """Application-allocate the next ``config_id``: max existing id + 1 (or 1 when empty)."""
    row = con.execute(f"SELECT max(config_id) FROM {_seg.SEG_CONFIG_TABLE}").fetchone()
    return 1 if row[0] is None else int(row[0]) + 1


def _prepare_config(con, cfg: SegConfigInput, *, run_id: str) -> int:
    """Reuse-or-insert the ``seg_config`` row and clear the config's prior catalog rows.

    Transactional.  Reuses an existing ``config_id`` when the same canonical config is
    already present (rerun / single-config rebuild), else allocates a fresh id.  The
    config's prior ``seg_meta`` + ``seg_membership`` rows are deleted with a
    ``WHERE config_id = ?`` ONLY (never broader, never table-wide) so reruns replace the
    same logical configuration without duplicates and unrelated configs are preserved.
    Returns the (reused or allocated) ``config_id``.
    """
    canonical = cfg.canonical_hash()
    existing = _existing_config_id(con, canonical)
    now = now_ms()
    con.execute("BEGIN TRANSACTION")
    try:
        if existing is not None:
            config_id = existing
            # A rebuild/rerun reuses the same logical config id (no duplicate row) but the
            # row's provenance now reflects THIS run, which is responsible for the current
            # catalog content.
            con.execute(
                f"UPDATE {_seg.SEG_CONFIG_TABLE} SET run_id = ?, created_at = ? WHERE config_id = ?",
                [run_id, now, config_id],
            )
        else:
            # No row carries this canonical identity (or this id), so allocating a fresh
            # id cannot collide.  The Phase 1 duplicate guards are asserted defensively.
            config_id = _next_config_id(con)
            _seg.raise_if_config_id_duplicate(con, config_id)
            _seg.raise_if_canonical_config_duplicate(con, canonical)
            _insert_config_row(con, cfg, config_id, run_id=run_id, created_at=now)
        # Replace this config's membership/meta exactly once — never broader.
        con.execute(f"DELETE FROM {_seg.SEG_META_TABLE} WHERE config_id = ?", [config_id])
        con.execute(f"DELETE FROM {_seg.SEG_MEMBERSHIP_TABLE} WHERE config_id = ?", [config_id])
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return int(config_id)


def _write_song_membership(
    con,
    *,
    config_id: int,
    song_id: str,
    segments: Sequence[MembershipSegment],
) -> tuple[int, int]:
    """Write one song's ``seg_meta`` + ``seg_membership`` rows atomically.

    One transaction per (config, song): membership + meta for a single song are written
    together so a partial failure leaves per-song status on the report, never a silent
    half-write.  Returns ``(num_segments, num_membership_rows)``.
    """
    now = now_ms()
    meta_rows: list[list[object]] = []
    member_rows: list[list[object]] = []
    for seg in segments:
        meta_rows.append(
            [
                int(config_id),
                song_id,
                int(seg.seg_id),
                int(seg.start_idx),
                int(seg.end_idx),
                int(seg.member_count),
                int(seg.absorbed_outlier_count),
                int(seg.weight),
                int(seg.medoid_source_patch_idx),
                seg.segment_signature,
                now,
            ]
        )
        for member_idx, is_outlier in zip(seg.member_indices, seg.is_absorbed_outlier, strict=True):
            member_rows.append(
                [
                    int(config_id),
                    song_id,
                    int(seg.seg_id),
                    int(member_idx),
                    bool(is_outlier),
                    int(CATALOG_MEMBERSHIP_VERSION),
                ]
            )
    con.execute("BEGIN TRANSACTION")
    try:
        if meta_rows:
            cols = ", ".join(_seg.seg_meta_columns)
            ph = ", ".join("?" for _ in _seg.seg_meta_columns)
            con.executemany(f"INSERT INTO {_seg.SEG_META_TABLE} ({cols}) VALUES ({ph})", meta_rows)
        if member_rows:
            cols = ", ".join(_seg.seg_membership_columns)
            ph = ", ".join("?" for _ in _seg.seg_membership_columns)
            con.executemany(f"INSERT INTO {_seg.SEG_MEMBERSHIP_TABLE} ({cols}) VALUES ({ph})", member_rows)
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    return len(segments), len(member_rows)


def _validate_and_dedup_configs(configs: Sequence[SegConfigInput]) -> list[SegConfigInput]:
    """Validate every config and collapse logical duplicates (same canonical hash)."""
    unique: OrderedDict[str, SegConfigInput] = OrderedDict()
    for cfg in configs:
        if not isinstance(cfg, SegConfigInput):
            cfg = SegConfigInput(**cfg) if isinstance(cfg, Mapping) else _coerce_cfg(cfg)
        cfg.canonical_hash()  # validates
        unique.setdefault(cfg.canonical_hash(), cfg)
    if not unique:
        raise CatalogValidationError("build_segmentation_catalog requires at least one config")
    return list(unique.values())


def _coerce_cfg(raw: Any) -> SegConfigInput:
    """Allow a config as a mapping of SegConfigInput fields (caller convenience)."""
    if isinstance(raw, Mapping):
        return SegConfigInput(**dict(raw))
    raise CatalogValidationError(f"unsupported config descriptor {type(raw).__name__}")


def _post_build_verify(
    con,
    *,
    outcomes: Sequence[ConfigBuildOutcome],
    run_id: str,
) -> tuple[str, ...]:
    """Re-check application integrity after the build (DD app-checks-again guarantee).

    Verifies: every built config has exactly one ``seg_config`` row (id unique); every
    ``seg_meta`` row has its config (no orphaned metadata) and every ``seg_membership``
    row has its ``seg_meta`` (no orphaned membership); the persisted membership row count
    per ``(config, song, seg)`` equals ``seg_meta.member_count``; and every member index
    lies inside its verified frozen source stream.  Returns a tuple of human-readable
    errors (empty == clean).  Never creates indexes / vectors.

    The orphan/count/range checks are SET-BASED per config (single NOT EXISTS anti-joins,
    one grouped-count comparison, one member-range anti-join), so the verification cost is
    a handful of engine-side passes over the config's rows rather than one round trip per
    membership row — keeping the ``verify=True`` path practical at the ~10M-row catalog
    scale while preserving the per-row detection semantics.
    """
    errors: list[str] = []
    seen_ids: set[int] = set()
    for outcome in outcomes:
        cid = outcome.config_id
        if cid in seen_ids:
            errors.append(f"config_id {cid} appears more than once across built configs")
        seen_ids.add(cid)
        cfg_row = _seg.config_row(con, cid)
        if cfg_row is None:
            errors.append(f"seg_config missing for built config_id {cid}")
            continue
        cfg = SegConfigRecord.from_row(cfg_row)
        if cfg.run_id != run_id:
            errors.append(f"config_id {cid} run_id {cfg.run_id!r} != build run_id {run_id!r}")
        backbone = cfg.backbone
        # Orphaned membership: seg_membership rows whose (config, song, seg) has no seg_meta.
        orphans = con.execute(
            f"SELECT DISTINCT song_id, seg_id FROM {_seg.SEG_MEMBERSHIP_TABLE} "
            "WHERE config_id = ? "
            "AND NOT EXISTS ("
            f"  SELECT 1 FROM {_seg.SEG_META_TABLE} m "
            "  WHERE m.config_id = seg_membership.config_id AND m.song_id = seg_membership.song_id "
            "  AND m.seg_id = seg_membership.seg_id)",
            [cid],
        ).fetchall()
        for song_id, seg_id in orphans:
            errors.append(
                f"seg_membership row (config_id={cid}, song_id={song_id!r}, "
                f"seg_id={seg_id}) references a seg_meta row that does not exist; orphaned "
                "membership rows are rejected"
            )
        # Membership row count must equal each seg_meta.member_count (grouped set comparison;
        # a left join with COALESCE surfaces under- and over-counts, incl. a seg_meta row with no
        # membership rows at all).
        count_drift = con.execute(
            f"SELECT meta.song_id, meta.seg_id, meta.member_count, COALESCE(grp.n, 0) "
            f"FROM {_seg.SEG_META_TABLE} meta "
            f"LEFT JOIN (SELECT song_id, seg_id, count(*) AS n FROM {_seg.SEG_MEMBERSHIP_TABLE} "
            "           WHERE config_id = ? GROUP BY song_id, seg_id) grp "
            "  ON grp.song_id = meta.song_id AND grp.seg_id = meta.seg_id "
            "WHERE meta.config_id = ? AND COALESCE(grp.n, 0) <> meta.member_count",
            [cid, cid],
        ).fetchall()
        for song_id, seg_id, member_count, persisted in count_drift:
            errors.append(
                f"config {cid} song {song_id!r} seg {seg_id} member_count {member_count} != {persisted} persisted rows"
            )
        # Member index in the verified frozen source stream: membership may only reference patch
        # indices inside [0, stream.patch_count) of the config backbone's status='ready' stream
        # for that song.  A single anti-join surfaces both an out-of-range index and a membership
        # whose song has no matching ready stream for the config's backbone.
        range_drift = con.execute(
            f"SELECT m.song_id, m.member_patch_idx FROM {_seg.SEG_MEMBERSHIP_TABLE} m "
            f"LEFT JOIN {STREAM_TABLE} s "
            "  ON s.song_id = m.song_id AND s.backbone = ? AND s.status = 'ready' "
            "WHERE m.config_id = ? "
            "AND (s.patch_count IS NULL OR m.member_patch_idx < 0 OR m.member_patch_idx >= s.patch_count)",
            [backbone, cid],
        ).fetchall()
        for song_id, member_patch_idx in range_drift:
            errors.append(
                f"member_patch_idx={member_patch_idx} is outside the verified frozen source "
                f"stream for (song_id={song_id!r}, backbone={backbone!r}); membership must "
                "reference only observed source patches (or no verified 'ready' stream exists)"
            )
    return tuple(errors)


# --------------------------------------------------------------------------- #
# The one-pass catalog build                                                   #
# --------------------------------------------------------------------------- #


def build_segmentation_catalog(
    con,
    stream_store,
    configs: Sequence[SegConfigInput | Mapping[str, object]],
    song_ids: Sequence[str],
    run_id: str,
    *,
    verify: bool = False,
) -> CatalogBuildReport:
    """Build the segmentation catalog for *configs* x *song_ids* in one pass per stream.

    Each verified ``(song, backbone)`` stream is loaded exactly once and every explicit
    or generated threshold configuration that selects that backbone is evaluated in the
    shared pass (R8).  ``config_id`` is application-allocated (reusing an existing id
    when the same canonical config is already present), a config's prior rows are
    replaced with a ``DELETE WHERE config_id = ?`` only, and each song's membership +
    meta are written in one transaction.

    Full-rebuild warning: because each in-scope config's prior ``seg_meta`` +
    ``seg_membership`` rows are deleted and replaced with the CURRENT build's rows, a
    rerun with a narrower ``song_ids`` scope (or a backbone whose eligible ready-stream
    count drops) rebuilds that config to contain ONLY the currently in-scope songs -- any
    previously-cataloged rows for songs no longer in scope are deleted.  Pass the
    complete intended song scope for a full rebuild, not a slice.

    When ``verify=True`` a post-build application-integrity re-check runs after commit; any
    drift raises :class:`CatalogVerificationError` before the run is recorded and no report is
    returned for a failed verification (a returned report always carries empty
    ``verification_errors``, matching ``verify_ok``).
    """
    started = now_ms()
    cfg_list = _validate_and_dedup_configs(list(configs))
    song_ids_tuple = tuple(str(s) for s in song_ids)
    if not song_ids_tuple:
        raise CatalogValidationError("build_segmentation_catalog requires at least one song_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise CatalogValidationError("run_id must be non-empty text")

    # Group the (deduplicated) configs by backbone in a stable one-time in-memory map —
    # this is the "one-time in-memory map" half of the bounded-lookup realization.  Every
    # config of a backbone then shares the single loaded stream per (song, backbone).
    by_backbone: OrderedDict[str, list[SegConfigInput]] = OrderedDict()
    for cfg in cfg_list:
        by_backbone.setdefault(cfg.backbone, []).append(cfg)

    config_ids: dict[str, int] = {}  # canonical hash -> allocated/reused config_id
    per_config: dict[str, dict[str, Any]] = {}
    load_evidence: list[tuple[str, str, int]] = []
    stream_loads = 0
    songs_built = 0
    total_segments = 0
    total_membership = 0

    for backbone, backbone_cfgs in by_backbone.items():
        # One-time in-memory map of which requested songs have a READY stream for this
        # backbone.  Requested songs lacking a stream for the backbone are inapplicable to
        # these configs and are silently excluded (not failures); genuine per-song
        # processing failures below drive partial/empty statuses.
        ready_songs: dict[str, StreamRecord] = {}
        for song in song_ids_tuple:
            try:
                record = stream_store.lookup(song, backbone)
            except (StreamNotFoundError, StreamNotReadyError):
                continue
            ready_songs[song] = record

        # Prepare every config of this backbone up front: reuse-or-allocate its config_id,
        # update its provenance, and clear its prior catalog rows with a
        # ``DELETE ... WHERE config_id = ?`` (never broader) so a rebuild replaces the
        # config without touching unrelated configs.  Each config appears in exactly one
        # backbone group, so this runs once per logical config per build call.
        for cfg in backbone_cfgs:
            hash_key = cfg.canonical_hash()
            cid = _prepare_config(con, cfg, run_id=run_id)
            config_ids[hash_key] = cid
            per_config[hash_key] = {
                "config_id": cid,
                "cfg": cfg,
                "eligible": len(ready_songs),
                # Requested songs lacking a READY stream for this backbone are silently
                # excluded from this config (not failures); surface the count on the outcome.
                "excluded_songs": len(song_ids_tuple) - len(ready_songs),
                "songs_completed": 0,
                "failed": [],
                "segments": 0,
                "membership": 0,
            }

        if not ready_songs:
            # No song stream for this backbone: every config keeps an empty outcome.
            continue

        for song, record in ready_songs.items():
            # ── ONE stream load per (song, backbone), shared by every config in the pass ──
            patches = stream_store.batch_gather(song, backbone, list(range(int(record.patch_count))))
            stream_loads += 1
            load_evidence.append((song, backbone, 1))
            norm = _l2_normalize_rows(patches)
            patch_count = int(norm.shape[0])

            for cfg in backbone_cfgs:
                state = per_config[cfg.canonical_hash()]
                try:
                    segments = authoritative_segmentation(
                        norm,
                        float(cfg.threshold_effective),
                        DIST_FNS[cfg.bin_mode],
                        outlier_window=int(cfg.outlier_window),
                    )
                    validate_full_partition(segments, patch_count)
                    seg_count, mem_count = _write_song_membership(
                        con,
                        config_id=int(state["config_id"]),
                        song_id=song,
                        segments=segments,
                    )
                    state["songs_completed"] += 1
                    state["segments"] += seg_count
                    state["membership"] += mem_count
                    total_segments += seg_count
                    total_membership += mem_count
                except Exception as exc:  # per-(config, song) partial failure
                    state["failed"].append(f"{song}:{type(exc).__name__}")
            songs_built += 1

    # Assemble per-config outcomes ordered by allocated config_id.
    outcomes: list[ConfigBuildOutcome] = []
    for state in per_config.values():
        cfg: SegConfigInput = state["cfg"]
        cid = int(state["config_id"])
        eligible = int(state["eligible"])
        songs_completed = int(state["songs_completed"])
        failed = tuple(sorted(set(state["failed"])))
        if failed:
            status = "partial"
        elif songs_completed == 0:
            status = "empty"
        else:
            status = "complete"
        outcomes.append(
            ConfigBuildOutcome(
                config_id=cid,
                backbone=cfg.backbone,
                bin_mode=cfg.bin_mode,
                threshold_configured=float(cfg.threshold_configured),
                threshold_effective=float(cfg.threshold_effective),
                semantics=cfg.semantics,
                canonical_config_hash=cfg.canonical_hash(),
                songs_eligible=eligible,
                excluded_songs=int(state["excluded_songs"]),
                songs_completed=songs_completed,
                failed_songs=failed,
                total_segments=int(state["segments"]),
                total_membership_rows=int(state["membership"]),
                status=status,
            )
        )
    outcomes.sort(key=lambda o: o.config_id)

    report_status = "complete" if all(o.status == "complete" for o in outcomes) else "partial"

    # Post-build verification (verify=True) then provenance + corpus-state bookkeeping.
    verification_errors: tuple[str, ...] = ()
    if verify:
        verification_errors = _post_build_verify(
            con,
            outcomes=outcomes,
            run_id=run_id,
        )
        if verification_errors:
            raise CatalogVerificationError(
                "post-build catalog verification found drift: " + "; ".join(verification_errors)
            )
    _record_catalog_run(con, run_id=run_id, outcomes=outcomes, status=report_status, started=started)
    finished = now_ms()

    return CatalogBuildReport(
        run_id=run_id,
        status=report_status,
        configs=tuple(outcomes),
        songs_requested=len(song_ids_tuple),
        songs_built=songs_built,
        stream_loads=stream_loads,
        load_evidence=tuple(load_evidence),
        total_segments=total_segments,
        total_membership_rows=total_membership,
        arithmetic_sizing_note=ARITHMETIC_SIZING_NOTE,
        verification_errors=verification_errors,
        started_at=started,
        finished_at=finished,
    )


def _record_catalog_run(
    con,
    *,
    run_id: str,
    outcomes: Sequence[ConfigBuildOutcome],
    status: str,
    started: int,
) -> None:
    """Record the catalog phase run and bump the corpus-state catalog fields (idempotent).

    Writes one ``run_provenance`` row (``phase='catalog'``) on the SAME tables Plan B
    created, skipping a duplicate when this ``run_id`` is already recorded (rerun
    idempotence).  Updates the singleton ``corpus_state.latest_catalog_run_id`` and its
    ``reconciliation_status``.  Rows never reference vectors; timestamps are ms.
    """
    from scripts.embedding_research.db import provenance as _prov

    finished = now_ms()
    summary = ";".join(f"{o.config_id}:{o.status}:songs={o.songs_completed}/{o.songs_eligible}" for o in outcomes)
    existing = con.execute(
        f"SELECT count(*) FROM {_prov.RUN_PROVENANCE_TABLE} WHERE run_id = ?",
        [run_id],
    ).fetchone()[0]
    if int(existing) == 0:
        _prov.write_run_provenance(
            con,
            run_id=run_id,
            phase=CATALOG_PHASE,
            status=status,
            started_at=started,
            finished_at=finished,
            config_hash=",".join(str(o.canonical_config_hash) for o in outcomes),
            song_count=int(sum(o.songs_completed for o in outcomes)),
            structural_change_summary=summary,
        )
    state = _prov.read_corpus_state(con)
    _prov.update_corpus_state(
        con,
        state_version=int(state["state_version"]) if state else 1,
        registered_song_count=int(state["registered_song_count"]) if state else 0,
        eligible_song_count=int(state["eligible_song_count"]) if state else 0,
        complete_flag=bool(state["complete_flag"]) if state else False,
        latest_catalog_run_id=run_id,
        latest_search_view_hash=str(state["latest_search_view_hash"]) if state else "",
        reconciled_at=finished,
        reconciliation_status=f"catalog:{status}:configs={len(outcomes)}",
    )


# --------------------------------------------------------------------------- #
# Bounded lookups (P3-S3)                                                     #
# --------------------------------------------------------------------------- #
# Realized with equality-filtered per-song / per-config queries.  No new DuckDB
# ``CREATE INDEX`` is introduced anywhere on this path (ordinary 1.x indexes are ART
# structures; the DD deliberately avoids them under the selected line).


def configs_by_backbone(con, backbone: str) -> tuple[SegConfigRecord, ...]:
    """Every ``seg_config`` row for *backbone* (equality-filtered, in column order)."""
    rows = con.execute(
        f"SELECT {', '.join(_seg.seg_config_columns)} FROM {_seg.SEG_CONFIG_TABLE} "
        "WHERE backbone = ? ORDER BY config_id",
        [backbone],
    ).fetchall()
    return tuple(SegConfigRecord.from_row(row) for row in rows)


def segments_by_config_song(con, config_id: int, song_id: str) -> tuple[SegMetaRecord, ...]:
    """Every ``seg_meta`` row for ``(config_id, song_id)`` ordered by ``seg_id``."""
    rows = con.execute(
        f"SELECT {', '.join(_seg.seg_meta_columns)} FROM {_seg.SEG_META_TABLE} "
        "WHERE config_id = ? AND song_id = ? ORDER BY seg_id",
        [config_id, song_id],
    ).fetchall()
    return tuple(SegMetaRecord.from_row(row) for row in rows)


def membership_by_config_song_seg(con, config_id: int, song_id: str, seg_id: int) -> tuple[SegMembershipRecord, ...]:
    """Every ``seg_membership`` row for ``(config_id, song_id, seg_id)`` ordered by member idx."""
    rows = con.execute(
        f"SELECT {', '.join(_seg.seg_membership_columns)} FROM {_seg.SEG_MEMBERSHIP_TABLE} "
        "WHERE config_id = ? AND song_id = ? AND seg_id = ? ORDER BY member_patch_idx",
        [config_id, song_id, seg_id],
    ).fetchall()
    return tuple(SegMembershipRecord.from_row(row) for row in rows)


def stream_by_song_backbone(con, song_id: str, backbone: str) -> StreamRecord:
    """The ready ``stream_registry`` record for ``(song_id, backbone)``.

    Mirrors ``StreamStore.lookup`` gating (only a ``ready`` row satisfies reads): raises
    :class:`StreamNotFoundError` when no row exists and :class:`StreamNotReadyError`
    when the row is not yet ready.  Equality-filtered, no index.
    """
    row = con.execute(
        f"SELECT {', '.join(STREAM_REGISTRY_COLUMNS)} FROM {STREAM_TABLE} WHERE song_id = ? AND backbone = ? LIMIT 1",
        [song_id, backbone],
    ).fetchone()
    if row is None:
        raise StreamNotFoundError(f"No {STREAM_TABLE} row for ({song_id!r}, {backbone!r})")
    record = StreamRecord.from_row(row)
    if record.status != "ready":
        raise StreamNotReadyError(
            f"{STREAM_TABLE} row for ({song_id!r}, {backbone!r}) has status "
            f"{record.status!r}; only 'ready' rows satisfy reads"
        )
    return record
