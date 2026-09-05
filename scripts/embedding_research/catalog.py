"""Compact durable segmentation-catalog producer (Plan C, P1-S5).

This module is the *compact catalog orchestrator*: it fans the pure, deterministic
segmentation (``helpers/segmentation.py`` §C) out into the DURABLE FILESYSTEM compact
snapshot rows (``seg_config`` / ``catalog_song`` / ``seg_meta`` / ``catalog_metadata``
inside a clean ``catalog.duckdb``) whose column/DDL home is ``catalog_storage.py``.

The corrective compact model (DD "Compact snapshot schema" + parts CONTRACTS § C):
there is NO per-patch ``seg_membership`` table and NO copied threshold-specific vector.
For each ``(song, backbone)`` frozen stream the build performs exactly ONE stream load
(shared across every requested threshold config of that backbone) and exactly one
mask load per song, then stores only structural ``seg_meta`` rows plus sparse canonical
absorbed exceptions.  Exact searchable membership ``M_g`` is reconstructed on read via
``helpers/segmentation.reconstruct_searchable_indices`` (``[start, end) - absorbed -
mask-silent``) — never read from an inclusive range.  Observed source-index medoids
(``select_observed_medoid_source_index``) and normalized searchable weights
(``searchable_count_g / total_searchable_song``) are persisted on ``seg_meta``.

``build_segmentation_catalog`` writes into ``output_root/catalogs/.staging-<run_id>/
catalog.duckdb`` (``catalog_storage.publish_catalog_snapshot`` durably publishes that staging
snapshot under ``catalogs/<catalog-id>/`` + ``catalogs/current.json``);
``output_root=None`` builds into an in-memory DuckDB.  Snapshots are per-run (each build
opens a fresh catalog file), so *rerun idempotence* means "the same canonical config and
song inputs produce an equivalent deterministic snapshot" — not cross-DB ``config_id``
persistence.  A config appearing under two identical canonical identities collapses to
one row; ``config_id`` values are assigned deterministically from the sorted canonical
hashes (1..n).

No calibration / optimizer / audio discovery / ONNX / CUDA is invoked anywhere on this
path (the build is pure DuckDB + numpy over ready frozen streams).  Post-build
``verify=True`` re-checks compact application integrity with no such prerequisite.

Timestamps are INTEGER milliseconds (project convention).

P1-S12 retired the pre-compact per-patch surfaces: ``SegConfigRecord`` / ``SegMetaRecord`` /
``SegMembershipRecord``, the research-DB read helpers (``configs_by_backbone`` /
``segments_by_config_song`` / ``membership_by_config_song_seg`` /
``stream_by_song_backbone``), the research ``seg_*`` DDL, and db/segmentation.py's
membership guards.  No retained production reader referenced them after the compact rewire
(they were never used by the compact producer).
"""

from __future__ import annotations

import hashlib
import math
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from scripts.embedding_research.catalog_storage import (
    CATALOG_SONG_COLS,
    CATALOG_SONG_TABLE,
    SEG_CONFIG_COLS,
    SEG_CONFIG_TABLE,
    SEG_META_COLS,
    SEG_META_TABLE,
    canonical_absorbed_indices,
    canonical_row_text,
    ensure_catalog_metadata_singleton,
    ensure_schema,
    now_ms,
    raise_if_duplicate_canonical_config,
    raise_if_duplicate_catalog_song,
    raise_if_duplicate_config,
)
from scripts.embedding_research.helpers import segmentation as _segmentation_module
from scripts.embedding_research.helpers.binning import DIST_FNS
from scripts.embedding_research.helpers.segmentation import (
    reconstruct_searchable_indices,
    run_spherical_segmentation,
    select_observed_medoid_source_index,
)
from scripts.embedding_research.helpers.thresholds import (
    DEFAULT_OUTLIER_WINDOW,
    DIRECT_L2,
    PTC_STRATEGY_VERSION,
    canonical_config_hash,
    config_encoder_version,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


__all__ = [
    "ARITHMETIC_SIZING_NOTE",
    "CATALOG_PHASE",
    "CatalogBuildReport",
    "CatalogError",
    "CatalogSongRecord",
    "CatalogValidationError",
    "CatalogVerificationError",
    "CompactConfigRecord",
    "CompactSegRecord",
    "ConfigBuildOutcome",
    "SegConfigInput",
    "build_segmentation_catalog",
    "compact_catalog_song",
    "compact_catalog_songs_by_config",
    "compact_config_by_id",
    "compact_segments_by_config_song",
]

#: Legacy provenance ``phase`` label for this build.  The producer does NOT write a
#: snapshot ``run_provenance`` row: durable catalog build provenance is recorded on the
#: ``catalog_metadata`` singleton (:func:`_write_catalog_metadata`) and, after publication,
#: in ``catalog.manifest.json``.  The snapshot ``run_provenance`` table is reserved and left
#: empty by the producer; the constant is retained for the historical ``catalog_report``
#: ``_latest_catalog_run`` semantics.
CATALOG_PHASE = "catalog"

#: The planning-surface sizing note.  ARITHMETIC SIZING (~10,000 songs x ~100 patches x
#: ~10 configs ≈ 10M compact ``seg_meta`` rows), explicitly NOT an empirical claim.
ARITHMETIC_SIZING_NOTE = (
    "~10,000 songs x ~100 patches x ~10 configs ~ 10M compact seg_meta rows "
    "(ARITHMETIC SIZING, not an empirical claim); per-song work O(P_s*D + T*P_s) with one "
    "stream load per (song, backbone) and one mask load per song, thresholds sharing the pass."
)

#: Compact ``catalog_song.status`` values.  A song with zero searchable patches across all
#: its structural segments is metadata-only (persisted, but never a search candidate).
CATALOG_SONG_STATUS_OK = "searchable"
CATALOG_SONG_STATUS_METADATA_ONLY = "metadata_only"

#: Snapshot ``catalog_metadata`` version semantics written by this build.  ``catalog_id``
#: is derived at publication time by ``catalog_storage.publish_catalog_snapshot`` (from the
#: canonical manifest, excluding its own id); the producer only records the run as the
#: ``catalog_id`` cell of the durable singleton, which is a stable placeholder until publish.
_FORMAT_VERSION = 1
_SCHEMA_VERSION = 1
_MANIFEST_VERSION = 1
_SERIALIZATION_VERSION = 1
_SEGMENTATION_SEMANTICS_VERSION = 1
_MASK_SEMANTICS_VERSION = "uint8-searchable-ones"
_SCORING_SEMANTICS_VERSION = 1


class CatalogError(RuntimeError):
    """Base for catalog build/lookup failures."""


class CatalogValidationError(CatalogError):
    """The build inputs (configs / songs / run) are invalid for a catalog pass."""


class CatalogVerificationError(CatalogError):
    """A ``verify=True`` post-build check found catalog rows inconsistent with intent."""


# --------------------------------------------------------------------------- #
# Build-input descriptor                                                       #
# --------------------------------------------------------------------------- #
# SegConfigInput is the build-input descriptor the compact producer accepts (alongside
# plain mapping descriptors via :func:`build_segmentation_catalog`).  P1-S12 removed the
# legacy ``alias_of_config_id`` and ``calibration_record`` fields (the compact model is
# canonical-only with no durable alias or calibration surface).


@dataclass(frozen=True)
class SegConfigInput:
    """A logical threshold configuration to be built (an explicit or generated member).

    The compact producer accepts these and plain mapping descriptors via
    :func:`build_segmentation_catalog`; its ``semantics``/``bin_mode`` validation is
    unchanged.  ``threshold_effective`` is the value actually applied during segmentation.
    """

    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    semantics: str = "direct_l2"
    outlier_window: int = DEFAULT_OUTLIER_WINDOW
    strategy_version: int = PTC_STRATEGY_VERSION

    def __post_init__(self) -> None:
        if self.semantics != DIRECT_L2:
            raise CatalogValidationError(f"only {DIRECT_L2!r} threshold semantics exists; got {self.semantics!r}")
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
        resolution: Any,
        outlier_window: int = DEFAULT_OUTLIER_WINDOW,
        strategy_version: int = PTC_STRATEGY_VERSION,
    ) -> SegConfigInput:
        """Build a config from a resolved threshold (configured/effective both recorded)."""
        return cls(
            backbone=backbone,
            bin_mode=bin_mode,
            threshold_configured=resolution.configured,
            threshold_effective=resolution.effective,
            semantics=DIRECT_L2,
            outlier_window=outlier_window,
            strategy_version=strategy_version,
        )

    def canonical_hash(self) -> str:
        """The deterministic sha256 canonical identity over the seg_config key ordering."""
        return canonical_config_hash(
            backbone=self.backbone,
            bin_mode=self.bin_mode,
            threshold=self.threshold_effective,
            outlier_window=self.outlier_window,
            strategy_version=self.strategy_version,
            encoder_version=config_encoder_version(),
        )


# --------------------------------------------------------------------------- #
# Compact value objects / records                                             #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class _CompactConfig:
    """A resolved, deduplicated compact segmentation config for one build pass.

    Compact configs accept ``bin_mode`` values beyond the legacy ``DIST_FNS`` set (e.g.
    ``"direct"``): the compact model does NOT validate ``bin_mode`` against ``DIST_FNS``.
    ``canonical_config_hash`` is the deterministic identity over the seg_config key
    ordering (backbone / bin_mode / threshold_effective / outlier_window /
    strategy_version / whole-module encoder_version) — independent of the human-readable
    ``threshold_semantics`` text.
    """

    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    threshold_semantics: str
    outlier_window: int
    strategy_version: int
    canonical_config_hash: str


@dataclass(frozen=True)
class CatalogSongRecord:
    """One compact ``catalog_song`` row (per (config, song) durable leaf)."""

    config_id: int
    song_id: str
    stream_digest: str
    mask_digest: str
    patch_count: int
    total_searchable_count: int
    exact_leaf: str
    search_leaf: str
    encoder_version: str
    params_id: str
    status: str

    @classmethod
    def from_row(cls, row: Sequence[object]) -> CatalogSongRecord:
        values = dict(zip(CATALOG_SONG_COLS, row, strict=True))
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class ConfigBuildOutcome:
    """Per-config result of one compact catalog build pass.

    ``songs_eligible`` is how many requested songs had a READY stream for this config's
    backbone (and were therefore built-or-attempted); ``excluded_songs`` is the number of
    requested songs for this backbone silently excluded for lacking a ready stream
    (never a failure).  ``songs_eligible + excluded_songs`` equals
    ``CatalogBuildReport.songs_requested``.  ``total_segments`` counts persisted compact
    ``seg_meta`` rows; ``total_catalog_songs`` counts persisted ``catalog_song`` rows.
    """

    config_id: int
    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    threshold_semantics: str
    canonical_config_hash: str
    songs_eligible: int
    excluded_songs: int
    songs_completed: int
    failed_songs: tuple[str, ...]
    total_segments: int
    total_catalog_songs: int
    status: str  # "complete" | "partial" | "empty"


@dataclass(frozen=True)
class CatalogBuildReport:
    """Result of :func:`build_segmentation_catalog`.

    Carries per-config outcomes, the one-load-per-song evidence proving the one-pass
    contract (``load_evidence`` is a sequence of 2-element ``((song, backbone), count)``
    pairs so ``dict(report.load_evidence)`` yields ``{(song, backbone): count}``), the
    deterministic snapshot exact/search hashes, and post-build verification errors.
    Timestamps are integer milliseconds.
    """

    run_id: str
    status: str  # "complete" | "partial"
    configs: tuple[ConfigBuildOutcome, ...]
    songs_requested: int
    songs_built: int  # distinct (song, backbone) streams actually loaded+processed
    stream_loads: int  # distinct (song, backbone) stream loads performed
    load_evidence: tuple[tuple[tuple[str, str], int], ...]
    total_segments: int
    total_catalog_songs: int
    exact_hash: str
    search_hash: str
    alias_collapse_note: str
    verification_errors: tuple[str, ...] = ()
    started_at: int = 0
    finished_at: int = 0

    @property
    def verify_ok(self) -> bool:
        """No catalog-row verification errors recorded (always True when ``verify=False``)."""
        return not self.verification_errors


# --------------------------------------------------------------------------- #
# Compact build helpers                                                       #
# --------------------------------------------------------------------------- #


def _l2_normalize_rows(patches: np.ndarray) -> np.ndarray:
    """Row L2-normalise a ``[P_s, D]`` float32 matrix to unit rows (finite-nonzero).

    Zero rows are preserved as-is (never medoid candidates downstream).  Returns a
    float32 copy.  Shared by the segmentation and medoid helpers, which both expect unit
    finite-nonzero rows.
    """
    arr = np.asarray(patches, dtype=np.float32)
    if arr.ndim != 2:
        raise CatalogValidationError(f"stream must be 2-D [P_s, D]; got shape {arr.shape}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (arr / norms).astype(np.float32, copy=False)


def _digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _coerce_compact_config(raw: Any) -> _CompactConfig:
    """Resolve one config descriptor (Mapping or attribute object) into a ``_CompactConfig``.

    Accepts both the legacy :class:`SegConfigInput` (attribute access) and plain mapping
    descriptors carrying ``backbone`` / ``bin_mode`` / ``threshold_configured`` /
    ``threshold_effective`` (optionally ``outlier_window`` / ``strategy_version`` /
    ``semantics``).  Does NOT validate ``bin_mode`` against ``DIST_FNS`` — the compact
    model permits ``"direct"`` and other non-DIST_FNS bin modes.
    """
    if isinstance(raw, Mapping):
        fields: dict[str, Any] = dict(raw)
        get = lambda key, default: fields.get(key, default)  # noqa: E731
    else:
        get = lambda key, default: getattr(raw, key, default)  # noqa: E731

    backbone = str(get("backbone", "") or "")
    bin_mode = str(get("bin_mode", "") or "")
    try:
        threshold_configured = float(get("threshold_configured", float("nan")))
        threshold_effective = float(get("threshold_effective", float("nan")))
    except (TypeError, ValueError) as exc:
        raise CatalogValidationError(f"thresholds must be numeric; got {exc!r}") from exc
    outlier_window = int(get("outlier_window", DEFAULT_OUTLIER_WINDOW))
    strategy_version = int(get("strategy_version", PTC_STRATEGY_VERSION))
    threshold_semantics = str(get("semantics", "direct_l2") or "direct_l2")

    if not backbone:
        raise CatalogValidationError("backbone must be non-empty text")
    if not bin_mode:
        raise CatalogValidationError("bin_mode must be non-empty text")
    for name, value in (("threshold_configured", threshold_configured), ("threshold_effective", threshold_effective)):
        if not math.isfinite(value):
            raise CatalogValidationError(f"{name} must be finite; got {value!r}")
    if outlier_window < 1:
        raise CatalogValidationError("outlier_window must be >= 1")

    canonical = canonical_config_hash(
        backbone=backbone,
        bin_mode=bin_mode,
        threshold=threshold_effective,
        outlier_window=outlier_window,
        strategy_version=strategy_version,
        encoder_version=config_encoder_version(),
    )
    return _CompactConfig(
        backbone=backbone,
        bin_mode=bin_mode,
        threshold_configured=threshold_configured,
        threshold_effective=threshold_effective,
        threshold_semantics=threshold_semantics,
        outlier_window=outlier_window,
        strategy_version=strategy_version,
        canonical_config_hash=canonical,
    )


def _dedup_and_validate_configs(configs: Sequence[Any]) -> list[_CompactConfig]:
    """Validate every config and collapse logical duplicates (same canonical hash).

    Order is preserved on first appearance; identity is canonical-hash dedup within the
    snapshot (equal canonical configs collapse to one).
    """
    unique: OrderedDict[str, _CompactConfig] = OrderedDict()
    for raw in configs:
        cfg = _coerce_compact_config(raw)
        unique.setdefault(cfg.canonical_config_hash, cfg)
    if not unique:
        raise CatalogValidationError("build_segmentation_catalog requires at least one config")
    return list(unique.values())


def _segmentation_encoder_version() -> str:
    """Whole-module encoder version of ``helpers/segmentation.py`` (lazy, cached).

    The compact snapshot records this deterministic whole-module encoder version on every
    ``catalog_song`` row (DD "encoder_version"); the exact-vs-search cross-layer hash
    wiring into D-owned readers is P1-S6/S7.
    """
    path = Path(getattr(_segmentation_module, "__file__", ""))
    return _digest_bytes(path.read_bytes())


def _structural_identity(seg: Any) -> str:
    """Deterministic per-segment structural identity (a stable snapshot preimage)."""
    pre = canonical_row_text(
        {
            "seg_id": int(seg.seg_id),
            "start_idx": int(seg.start_idx),
            "end_idx": int(seg.end_idx),
            "absorbed_indices": canonical_absorbed_indices(seg.absorbed_indices),
        },
        columns=("seg_id", "start_idx", "end_idx", "absorbed_indices"),
    )
    return _digest_bytes(("seg\n" + pre).encode("utf-8"))


def _load_song_mask(mask_store: Any, song_id: str) -> np.ndarray | None:
    """Load the whole-song uint8 mask for *song_id* once (``None`` => no silence).

    The mask store is a NEW duck-typed loader ``.load(song_id) -> uint8[P]`` (no
    ``MaskStore`` class exists).  A ``None`` / failed mask means "no silent patches", so
    the whole structural range is searchable (fails open on absent mask data).
    """
    if mask_store is None:
        return None
    try:
        result = mask_store.load(song_id)
    except Exception:
        return None
    if result is None:
        return None
    arr = np.asarray(result)
    if arr.size == 0:
        return None
    return arr


def _song_leaves(con, config_id: int, song_id: str, *, patch_count: int, total_searchable: int) -> tuple[str, str]:
    """Deterministic exact/search leaf hashes for one persisted ``catalog_song``.

    Reads the just-written compact ``seg_meta`` rows for ``(config_id, song_id)`` (in
    ``seg_id`` order) and hashes two DISTINCT canonical projections: ``exact`` covers the
    structural/membership-reconstruction content; ``search`` covers the searchable
    medoid/weight content.  The preimages are prefixed and bound to ``patch_count`` and
    ``total_searchable_count`` so the two leaves differ even for an empty segment set and
    match whatever the snapshot persisted.  Returns ``(exact_leaf, search_leaf)``.
    """
    rows = con.execute(
        f"SELECT {', '.join(SEG_META_COLS)} FROM {SEG_META_TABLE} WHERE config_id = ? AND song_id = ? ORDER BY seg_id",
        [int(config_id), song_id],
    ).fetchall()
    row_maps = [dict(zip(SEG_META_COLS, r, strict=True)) for r in rows]
    head = f"pc={int(patch_count)};total={int(total_searchable)}\n"
    exact_pre = (
        "exact\n"
        + head
        + "\n".join(
            canonical_row_text(
                m,
                columns=("seg_id", "start_idx", "end_idx", "absorbed_indices", "absorbed_count", "searchable_count"),
            )
            for m in row_maps
        )
    )
    search_pre = (
        "search\n"
        + head
        + "\n".join(
            canonical_row_text(
                m,
                columns=("seg_id", "searchable_count", "search_medoid_source_patch_idx", "searchable_weight"),
            )
            for m in row_maps
        )
    )
    return _digest_bytes(exact_pre.encode("utf-8")), _digest_bytes(search_pre.encode("utf-8"))


def _write_config_rows(con, cfg: _CompactConfig, config_id: int, *, run_id: str) -> None:
    """Insert one compact ``seg_config`` row (application duplicate hooks enforced)."""
    raise_if_duplicate_config(con, config_id)
    raise_if_duplicate_canonical_config(con, cfg.canonical_config_hash, exclude_config_id=config_id)
    values = {
        "config_id": int(config_id),
        "backbone": cfg.backbone,
        "bin_mode": cfg.bin_mode,
        "threshold_configured": float(cfg.threshold_configured),
        "threshold_effective": float(cfg.threshold_effective),
        "threshold_semantics": cfg.threshold_semantics,
        "outlier_window": int(cfg.outlier_window),
        "strategy_version": int(cfg.strategy_version),
        "canonical_config_hash": cfg.canonical_config_hash,
        "run_id": run_id,
    }
    cols = ", ".join(SEG_CONFIG_COLS)
    ph = ", ".join("?" for _ in SEG_CONFIG_COLS)
    con.execute(
        f"INSERT INTO {SEG_CONFIG_TABLE} ({cols}) VALUES ({ph})",
        [values[c] for c in SEG_CONFIG_COLS],
    )


def _persist_seg_rows(
    con,
    *,
    config_id: int,
    song_id: str,
    run_id: str,
    unit_matrix: np.ndarray,
    total_searchable: int,
    computed: Sequence[tuple[Any, int, tuple[int, ...]]],
) -> int:
    """Persist one song's compact ``seg_meta`` structural rows.

    ``computed`` is ``(seg, searchable_count, searchable_indices)`` per structural segment.
    For each row ``searchable_weight = searchable_count / total_searchable`` (0 when the
    segment has no searchable mass) and ``search_medoid_source_patch_idx`` is the observed
    source index selected over the segment's reconstructed searchable set (``None`` when
    empty / no finite-nonzero candidate).  Returns the number of persisted rows.
    """
    encoded: list[list[object]] = []
    for seg, count, searchable_indices in computed:
        absorbed = tuple(int(i) for i in seg.absorbed_indices)
        weight = float(count) / float(total_searchable) if total_searchable > 0 else 0.0
        medoid: int | None = None
        if count > 0:
            medoid, _centrality = select_observed_medoid_source_index(unit_matrix, searchable_indices)
        encoded.append(
            [
                int(config_id),
                song_id,
                int(seg.seg_id),
                int(seg.start_idx),
                int(seg.end_idx),
                canonical_absorbed_indices(absorbed),
                len(absorbed),
                int(count),
                medoid,
                float(weight),
                _structural_identity(seg),
                run_id,
            ]
        )
    if encoded:
        cols = ", ".join(SEG_META_COLS)
        ph = ", ".join("?" for _ in SEG_META_COLS)
        con.executemany(
            f"INSERT INTO {SEG_META_TABLE} ({cols}) VALUES ({ph})",
            encoded,
        )
    return len(encoded)


def _write_catalog_song_row(
    con,
    *,
    config_id: int,
    song_id: str,
    stream_digest: str,
    mask_digest: str,
    patch_count: int,
    total_searchable: int,
    exact_leaf: str,
    search_leaf: str,
    encoder_version: str,
    params_id: str,
    status: str,
) -> None:
    raise_if_duplicate_catalog_song(con, config_id, song_id)
    values = {
        "config_id": int(config_id),
        "song_id": song_id,
        "stream_digest": stream_digest,
        "mask_digest": mask_digest,
        "patch_count": int(patch_count),
        "total_searchable_count": int(total_searchable),
        "exact_leaf": exact_leaf,
        "search_leaf": search_leaf,
        "encoder_version": encoder_version,
        "params_id": params_id,
        "status": status,
    }
    cols = ", ".join(CATALOG_SONG_COLS)
    ph = ", ".join("?" for _ in CATALOG_SONG_COLS)
    con.execute(
        f"INSERT INTO {CATALOG_SONG_TABLE} ({cols}) VALUES ({ph})",
        [values[c] for c in CATALOG_SONG_COLS],
    )


def _write_catalog_metadata(con, *, run_id: str, created_at_ms: int) -> None:
    """Write the ``catalog_metadata`` singleton for a built snapshot.

    Records the build run and software versions durably on the singleton (this is the
    producer's build-provenance home; the snapshot ``run_provenance`` table is not written
    here).  The ``catalog_id`` is stored as a stable *placeholder* equal to ``run_id``; the
    final manifest-derived ``catalog_id`` is computed and republished later by
    ``catalog_storage.publish_catalog_snapshot``.
    """
    ensure_catalog_metadata_singleton(con)
    import duckdb as _ddb

    from scripts.embedding_research.catalog_storage import (
        CATALOG_METADATA_COLS,
        CATALOG_METADATA_TABLE,
    )

    values = {
        "catalog_id": run_id,  # placeholder; publish_catalog_snapshot derives the final id
        "format_version": _FORMAT_VERSION,
        "schema_version": _SCHEMA_VERSION,
        "manifest_version": _MANIFEST_VERSION,
        "serialization_version": _SERIALIZATION_VERSION,
        "segmentation_semantics_version": _SEGMENTATION_SEMANTICS_VERSION,
        "mask_semantics_version": _MASK_SEMANTICS_VERSION,
        "scoring_semantics_version": _SCORING_SEMANTICS_VERSION,
        "build_duckdb_version": str(_ddb.__version__),
        "build_python_version": _python_version(),
        "build_numpy_version": str(np.__version__),
        "resolved_input_digests": None,
        "run_id": run_id,
        "created_at_ms": int(created_at_ms),
    }
    cols = ", ".join(CATALOG_METADATA_COLS)
    ph = ", ".join("?" for _ in CATALOG_METADATA_COLS)
    con.execute(
        f"INSERT INTO {CATALOG_METADATA_TABLE} ({cols}) VALUES ({ph})",
        [values[c] for c in CATALOG_METADATA_COLS],
    )


def _python_version() -> str:
    import platform

    return platform.python_version()


def _build_and_persist_song(
    con,
    *,
    config_id: int,
    cfg: _CompactConfig,
    song_id: str,
    unit_matrix: np.ndarray,
    mask: np.ndarray | None,
    patch_count: int,
    run_id: str,
    encoder_version: str,
    stream_digest: str,
    mask_digest: str,
) -> tuple[int, int]:
    """Segment one song under one config and persist ``seg_meta`` + ``catalog_song``.

    Returns ``(num_segments, total_searchable)``.  A song whose structural segments all
    yield zero searchable mass is metadata-only: it gets a ``catalog_song`` row (status
    ``metadata_only``, zero totals) and NO ``seg_meta`` rows.  Raises on any compute /
    persistence failure (the caller captures it as a per-(config, song) partial failure).
    """
    segments = run_spherical_segmentation(
        unit_matrix, float(cfg.threshold_effective), outlier_window=cfg.outlier_window
    )
    computed: list[tuple[Any, int, tuple[int, ...]]] = []
    total = 0
    for seg in segments:
        searchable = reconstruct_searchable_indices(seg, mask, patch_count)
        searchable = np.asarray(searchable, dtype=int)
        count = int(searchable.size)
        total += count
        computed.append((seg, count, tuple(int(i) for i in searchable)))
    if total == 0:
        exact_leaf, search_leaf = _song_leaves(con, config_id, song_id, patch_count=patch_count, total_searchable=0)
        _write_catalog_song_row(
            con,
            config_id=config_id,
            song_id=song_id,
            stream_digest=stream_digest,
            mask_digest=mask_digest,
            patch_count=patch_count,
            total_searchable=0,
            exact_leaf=exact_leaf,
            search_leaf=search_leaf,
            encoder_version=encoder_version,
            params_id=_params_id(unit_matrix),
            status=CATALOG_SONG_STATUS_METADATA_ONLY,
        )
        return 0, 0

    # Persist the structural seg rows (medoid + normalized weight computed here), then
    # derive the catalog_song leaf hashes from the persisted rows.
    seg_count = _persist_seg_rows(
        con,
        config_id=config_id,
        song_id=song_id,
        run_id=run_id,
        unit_matrix=unit_matrix,
        total_searchable=total,
        computed=computed,
    )
    exact_leaf, search_leaf = _song_leaves(con, config_id, song_id, patch_count=patch_count, total_searchable=total)
    _write_catalog_song_row(
        con,
        config_id=config_id,
        song_id=song_id,
        stream_digest=stream_digest,
        mask_digest=mask_digest,
        patch_count=patch_count,
        total_searchable=total,
        exact_leaf=exact_leaf,
        search_leaf=search_leaf,
        encoder_version=encoder_version,
        params_id=_params_id(unit_matrix),
        status=CATALOG_SONG_STATUS_OK,
    )
    return seg_count, total


def _params_id(unit_matrix: np.ndarray) -> str:
    """Deterministic params identity for a stream (its embedding dimension)."""
    return f"dim={int(unit_matrix.shape[1])}"


# --------------------------------------------------------------------------- #
# The compact one-pass catalog build                                          #
# --------------------------------------------------------------------------- #


def build_segmentation_catalog(
    stream_store,
    mask_store,
    configs: Sequence[Any],
    song_ids: Sequence[str],
    *,
    output_root,
    run_id: str,
    verify: bool = False,
) -> CatalogBuildReport:
    """Build a compact segmentation catalog snapshot in one pass per (song, backbone).

    Each verified ``(song, backbone)`` stream is loaded EXACTLY ONCE and shared by every
    requested threshold config of that backbone (one mask load per song).  The snapshot
    is written to ``output_root/catalogs/.staging-<run_id>/catalog.duckdb`` (a fresh file
    per run) or, when ``output_root`` is ``None``, to an in-memory DuckDB.  The compact
    snapshot stores structural ``seg_config``/``catalog_song``/``seg_meta`` rows plus
    sparse absorbed exceptions — never a per-patch membership table.  ``config_id`` is
    assigned deterministically (sorted canonical hashes, 1..n) and logical duplicates
    collapse.

    ``mask_store`` is the new duck-typed whole-song mask loader (``.load(song_id) ->
    uint8[P]``); a ``None``/failed mask means no silent patches.  ``stream_store`` is any
    current-stream loader with ``.load(song_id, backbone) -> float32[P,D] | None`` (the
    real seam is ``make_current_stream_resolver``).

    A requested song with no ready stream for a config's backbone is silently excluded
    (counted on the outcome, never a failure); genuine per-(config, song) failures are
    captured as ``failed_songs`` and drive ``partial``/``empty`` statuses.  When
    ``verify=True`` a post-build compact-integrity re-check runs; any drift raises
    :class:`CatalogVerificationError` (a returned report always carries empty
    ``verification_errors``).
    """
    started = now_ms()
    cfg_list = _dedup_and_validate_configs(list(configs))
    song_ids_tuple = tuple(str(s) for s in song_ids)
    if not song_ids_tuple:
        raise CatalogValidationError("build_segmentation_catalog requires at least one song_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise CatalogValidationError("run_id must be non-empty text")

    if output_root is None:
        import duckdb as _duckdb

        con = _duckdb.connect(":memory:")
        ensure_schema(con)
        try:
            return _run_build(
                con,
                stream_store=stream_store,
                mask_store=mask_store,
                cfg_list=cfg_list,
                song_ids=song_ids_tuple,
                run_id=run_id,
                verify=verify,
                started=started,
            )
        finally:
            con.close()
    staging = Path(output_root) / "catalogs" / f".staging-{run_id}" / "catalog.duckdb"
    from scripts.embedding_research.catalog_storage import connect as _catalog_connect

    # Hold the connection context-manager open for the whole build (a temporary
    # context manager would be garbage-collected at the yield and close the con early).
    with _catalog_connect(staging) as con:
        return _run_build(
            con,
            stream_store=stream_store,
            mask_store=mask_store,
            cfg_list=cfg_list,
            song_ids=song_ids_tuple,
            run_id=run_id,
            verify=verify,
            started=started,
        )


def _run_build(
    con,
    *,
    stream_store,
    mask_store,
    cfg_list: Sequence[_CompactConfig],
    song_ids: Sequence[str],
    run_id: str,
    verify: bool,
    started: int,
) -> CatalogBuildReport:
    """Execute the build against an open compact-snapshot connection *con*."""
    # Deterministic config_id assignment from the sorted canonical hashes (1..n).
    ordered = sorted(cfg_list, key=lambda c: c.canonical_config_hash)
    hash_to_id: dict[str, int] = {c.canonical_config_hash: i + 1 for i, c in enumerate(ordered)}
    config_id_for: dict[str, int] = {c.canonical_config_hash: hash_to_id[c.canonical_config_hash] for c in cfg_list}

    # Group unique configs by backbone (deterministic backbone order).
    by_backbone: OrderedDict[str, list[_CompactConfig]] = OrderedDict()
    for cfg in cfg_list:
        by_backbone.setdefault(cfg.backbone, []).append(cfg)

    # Insert every seg_config row up front (identity is independent of stream readiness).
    for cfg in cfg_list:
        _write_config_rows(con, cfg, config_id_for[cfg.canonical_config_hash], run_id=run_id)

    encoder_version = _segmentation_encoder_version()

    # Per-config mutable build state keyed by canonical hash.
    per_cfg: dict[str, dict[str, Any]] = {}
    for cfg in cfg_list:
        per_cfg[cfg.canonical_config_hash] = {
            "cfg": cfg,
            "config_id": int(config_id_for[cfg.canonical_config_hash]),
            "eligible": 0,
            "excluded_songs": 0,
            "songs_completed": 0,
            "failed": [],
            "segments": 0,
            "catalog_songs": 0,
        }

    mask_cache: dict[str, np.ndarray | None] = {}
    load_evidence: dict[tuple[str, str], int] = {}
    stream_loads = 0
    songs_built = 0
    total_segments = 0
    total_catalog_songs = 0

    for backbone in sorted(by_backbone):
        backbone_cfgs = by_backbone[backbone]
        ready_count = 0
        for song in song_ids:
            try:
                matrix = stream_store.load(song, backbone)
            except Exception:
                matrix = None
            if matrix is None:
                continue  # no ready stream for this (song, backbone): silently excluded
            ready_count += 1
            stream_loads += 1
            songs_built += 1
            load_evidence[(song, backbone)] = load_evidence.get((song, backbone), 0) + 1

            unit = _l2_normalize_rows(matrix)
            patch_count = int(unit.shape[0])
            if song not in mask_cache:
                mask_cache[song] = _load_song_mask(mask_store, song)
            mask = mask_cache[song]
            stream_digest = _digest_bytes(np.ascontiguousarray(matrix, dtype=np.float32).tobytes())
            mask_digest = (
                _digest_bytes(np.ascontiguousarray(mask, dtype=np.uint8).tobytes()) if mask is not None else "no-mask"
            )

            for cfg in backbone_cfgs:
                state = per_cfg[cfg.canonical_config_hash]
                try:
                    seg_count, _song_total = _build_and_persist_song(
                        con,
                        config_id=state["config_id"],
                        cfg=cfg,
                        song_id=song,
                        unit_matrix=unit,
                        mask=mask,
                        patch_count=patch_count,
                        run_id=run_id,
                        encoder_version=encoder_version,
                        stream_digest=stream_digest,
                        mask_digest=mask_digest,
                    )
                    state["songs_completed"] += 1
                    state["segments"] += seg_count
                    state["catalog_songs"] += 1
                    total_segments += seg_count
                    total_catalog_songs += 1
                except Exception as exc:  # per-(config, song) partial failure
                    state["failed"].append(f"{song}:{type(exc).__name__}")

        for cfg in backbone_cfgs:
            state = per_cfg[cfg.canonical_config_hash]
            # This backbone's requested-song readiness is shared by every config of it.
            state["eligible"] = max(state["eligible"], ready_count)
            state["excluded_songs"] = max(state["excluded_songs"], len(song_ids) - ready_count)

    # Assemble per-config outcomes ordered by config_id.
    outcomes: list[ConfigBuildOutcome] = []
    for cfg in cfg_list:
        state = per_cfg[cfg.canonical_config_hash]
        failed = tuple(sorted(set(state["failed"])))
        if failed:
            status = "partial"
        elif state["songs_completed"] == 0:
            status = "empty"
        else:
            status = "complete"
        outcomes.append(
            ConfigBuildOutcome(
                config_id=int(state["config_id"]),
                backbone=cfg.backbone,
                bin_mode=cfg.bin_mode,
                threshold_configured=float(cfg.threshold_configured),
                threshold_effective=float(cfg.threshold_effective),
                threshold_semantics=cfg.threshold_semantics,
                canonical_config_hash=cfg.canonical_config_hash,
                songs_eligible=int(state["eligible"]),
                excluded_songs=int(state["excluded_songs"]),
                songs_completed=int(state["songs_completed"]),
                failed_songs=failed,
                total_segments=int(state["segments"]),
                total_catalog_songs=int(state["catalog_songs"]),
                status=status,
            )
        )
    outcomes.sort(key=lambda o: o.config_id)
    report_status = "complete" if all(o.status == "complete" for o in outcomes) else "partial"

    _write_catalog_metadata(con, run_id=run_id, created_at_ms=now_ms())

    verification_errors: tuple[str, ...] = ()
    if verify:
        verification_errors = _post_build_verify(con, outcomes=outcomes, run_id=run_id)
        if verification_errors:
            raise CatalogVerificationError(
                "post-build catalog verification found drift: " + "; ".join(verification_errors)
            )

    exact_hash, search_hash = _snapshot_hashes(con)
    finished = now_ms()

    return CatalogBuildReport(
        run_id=run_id,
        status=report_status,
        configs=tuple(outcomes),
        songs_requested=len(song_ids),
        songs_built=songs_built,
        stream_loads=stream_loads,
        load_evidence=tuple(((song, backbone), count) for (song, backbone), count in load_evidence.items()),
        total_segments=total_segments,
        total_catalog_songs=total_catalog_songs,
        exact_hash=exact_hash,
        search_hash=search_hash,
        alias_collapse_note=(
            "no durable alias_of_config_id or copied vectors; alias/collapse evidence is "
            "computed transiently from the snapshot exact/search hashes"
        ),
        verification_errors=verification_errors,
        started_at=started,
        finished_at=finished,
    )


def _snapshot_hashes(con) -> tuple[str, str]:
    """Deterministic report-level exact/search hashes over the persisted song leaves.

    Both are independent of physical row order (leaf sets are sorted before hashing) and
    are distinct because the underlying exact/search leaves are distinct preimages.
    """
    rows = con.execute(
        f"SELECT exact_leaf, search_leaf FROM {CATALOG_SONG_TABLE} ORDER BY exact_leaf, search_leaf"
    ).fetchall()
    exact = "\n".join(sorted(r[0] for r in rows))
    search = "\n".join(sorted(r[1] for r in rows))
    return _digest_bytes(("exact-snapshot\n" + exact).encode("utf-8")), _digest_bytes(
        ("search-snapshot\n" + search).encode("utf-8")
    )


def _post_build_verify(con, *, outcomes: Sequence[ConfigBuildOutcome], run_id: str) -> tuple[str, ...]:
    """Post-build compact application-integrity re-check (``verify=True``).

    Verifies: every built config has exactly one ``seg_config`` row; no
    ``seg_membership`` table exists anywhere; ``catalog_metadata`` is a valid singleton;
    every ``seg_meta`` row has a backing ``catalog_song`` row (no orphans); and each
    ``catalog_song.total_searchable_count`` equals the reconstructed sum of its
    ``seg_meta.searchable_count`` rows.  Returns a tuple of human-readable errors (empty
    == clean).  Never creates indexes / vectors / optimizer state.
    """
    errors: list[str] = []
    try:
        present = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    except Exception as exc:  # pragma: no cover - defensive
        present = set()
        errors.append(f"could not enumerate snapshot tables: {exc!r}")
    if "seg_membership" in present:
        errors.append("compact snapshot must not contain a per-patch seg_membership table")

    ensure_catalog_metadata_singleton(con)

    seen: set[int] = set()
    for outcome in outcomes:
        cid = int(outcome.config_id)
        if cid in seen:
            errors.append(f"config_id {cid} appears more than once across built configs")
        seen.add(cid)
        count = int(
            con.execute(
                f"SELECT count(*) FROM {SEG_CONFIG_TABLE} WHERE config_id = ? AND run_id = ?",
                [cid, run_id],
            ).fetchone()[0]
        )
        if count != 1:
            errors.append(f"seg_config missing (or not run-owned) for built config_id {cid}")

    # Orphaned seg_meta: a seg_meta row whose (config, song) has no catalog_song leaf.
    orphaned = con.execute(
        f"SELECT DISTINCT song_id FROM {SEG_META_TABLE} sm "
        f"WHERE NOT EXISTS (SELECT 1 FROM {CATALOG_SONG_TABLE} cs "
        "  WHERE cs.config_id = sm.config_id AND cs.song_id = sm.song_id)"
    ).fetchall()
    for (song_id,) in orphaned:
        errors.append(f"seg_meta row for song {song_id!r} has no backing catalog_song leaf; orphaned")

    # Total-searchable drift: catalog_song.total_searchable_count must equal the sum of its
    # seg_meta.searchable_count rows (and zero-searchable metadata-only songs have no seg rows).
    drift = con.execute(
        f"SELECT cs.song_id, cs.total_searchable_count, COALESCE(grp.n, 0) "
        f"FROM {CATALOG_SONG_TABLE} cs "
        f"LEFT JOIN (SELECT config_id, song_id, sum(searchable_count) AS n FROM {SEG_META_TABLE} "
        "           GROUP BY config_id, song_id) grp "
        "  ON grp.config_id = cs.config_id AND grp.song_id = cs.song_id "
        "WHERE COALESCE(grp.n, 0) <> cs.total_searchable_count",
        [],
    ).fetchall()
    for song_id, stored, derived in drift:
        errors.append(f"catalog_song total_searchable_count {stored} != reconstructed {derived} for song {song_id!r}")
    return tuple(errors)


# --------------------------------------------------------------------------- #
# Compact snapshot read helpers                                                #
# --------------------------------------------------------------------------- #
# These read the COMPACT durable FILESYSTEM snapshot tables (``seg_config`` /
# ``catalog_song`` / ``seg_meta``) via the ``catalog_storage`` column tuples.  Per the
# corrective pass (P1-S12 retired the legacy research ``seg_*`` tables, their dead readers,
# and the ``SegConfigRecord``/``SegMetaRecord``/``SegMembershipRecord`` objects), these
# ``compact_*`` helpers are the ONLY catalog readers: exact searchable membership is
# reconstructed on read (structural ranges + sparse absorbed indices + mask), never read as
# per-patch rows.  They accept any connection whose schema is this module's five compact
# tables — typically ``CatalogHandle.con`` (returned by
# ``catalog_storage.open_current_catalog`` / ``open_snapshot_file``) — or any duckdb con
# with the 5-table compact schema.  A compact ``seg_config`` row is canonical-only (no
# ``alias_of_config_id``; there is no durable alias graph).  These helpers are NOT used by
# the compact producer (``catalog.py`` writes rows directly through the schema) and back the
# D-owned analysis/report readers.

# NAMING DECISION (recorded for the ``compact_*`` reader/record surface): the compact
# config and segment row objects are named ``CompactConfigRecord`` / ``CompactSegRecord``
# (implemented below) to read distinctly from the pre-compact ``SegConfigRecord`` /
# ``SegMetaRecord`` that P1-S12 removed along with the research ``seg_*`` tables.  The
# compact ``catalog_song`` leaf reuses the existing compact :class:`CatalogSongRecord`.  Read
# helpers are prefixed ``compact_``:
# ``compact_configs_by_backbone`` / ``compact_config_by_id`` /
# ``compact_segments_by_config_song`` / ``compact_catalog_songs_by_config`` /
# ``compact_catalog_song``.  All take a compact ``con`` (pass ``handle.con``) and return
# read-only records.  ``absorbed_indices`` is parsed from the canonical ``[1,4,7]`` text
# into an ascending int tuple so downstream reconstruction
# (``helpers.segmentation.reconstruct_searchable_indices``) can consume it directly.


@dataclass(frozen=True)
class CompactConfigRecord:
    """One compact ``seg_config`` row (canonical-only: no ``alias_of_config_id``).

    Fields exactly follow ``catalog_storage.SEG_CONFIG_COLS``.  Configured and effective
    thresholds are always numerically equal under the direct contract; both are carried
    for parity with the durable row.  ``canonical_config_hash`` is the deterministic
    identity over the seg_config key ordering.
    """

    config_id: int
    backbone: str
    bin_mode: str
    threshold_configured: float
    threshold_effective: float
    threshold_semantics: str
    outlier_window: int
    strategy_version: int
    canonical_config_hash: str
    run_id: str

    @classmethod
    def from_row(cls, row: Sequence[object]) -> CompactConfigRecord:
        values = dict(zip(SEG_CONFIG_COLS, row, strict=True))
        return cls(**values)  # type: ignore[arg-type]


@dataclass(frozen=True)
class CompactSegRecord:
    """One compact ``seg_meta`` row (structural + searchable-membership metadata).

    Fields follow ``catalog_storage.SEG_META_COLS``; ``absorbed_indices`` is parsed from
    the canonical sparse text into an ascending int tuple (empty tuple when none).  The
    structural ``start_idx``/``end_idx`` are EXCLUSIVE report ranges only — exact
    searchable membership is reconstructed via ``helpers.segmentation.
    reconstruct_searchable_indices`` against the song mask, never read from the range.
    ``search_medoid_source_patch_idx`` is nullable (``None`` when the segment has no
    searchable / no finite-nonzero candidate).
    """

    config_id: int
    song_id: str
    seg_id: int
    start_idx: int
    end_idx: int
    absorbed_indices: tuple[int, ...]
    absorbed_count: int
    searchable_count: int
    search_medoid_source_patch_idx: int | None
    searchable_weight: float
    structural_identity: str
    provenance: str | None

    @classmethod
    def from_row(cls, row: Sequence[object]) -> CompactSegRecord:
        values = dict(zip(SEG_META_COLS, row, strict=True))
        values["absorbed_indices"] = _parse_canonical_absorbed_indices(str(values["absorbed_indices"]))
        values["search_medoid_source_patch_idx"] = (
            int(values["search_medoid_source_patch_idx"])
            if values["search_medoid_source_patch_idx"] is not None
            else None
        )
        return cls(**values)  # type: ignore[arg-type]


def _parse_canonical_absorbed_indices(text: str) -> tuple[int, ...]:
    """Parse the canonical ``[1,4,7]`` sparse text into an ascending int tuple."""
    body = text.strip()
    if body in ("", "[]"):
        return ()
    if not (body.startswith("[") and body.endswith("]")):
        raise ValueError(f"absorbed_indices is not canonical sparse text: {text!r}")
    inner = body[1:-1]
    if not inner.strip():
        return ()
    return tuple(int(part) for part in inner.split(",") if part.strip() != "")


def compact_configs_by_backbone(con, backbone: str) -> tuple[CompactConfigRecord, ...]:
    """Every compact ``seg_config`` row for *backbone* (ordered by ``config_id``).

    Canonical-only semantics: a compact config never carries ``alias_of_config_id``; two
    rows with equal ``canonical_config_hash`` would violate the collapse invariant and
    should never coexist in a verified snapshot.
    """
    rows = con.execute(
        f"SELECT {', '.join(SEG_CONFIG_COLS)} FROM {SEG_CONFIG_TABLE} WHERE backbone = ? ORDER BY config_id",
        [backbone],
    ).fetchall()
    return tuple(CompactConfigRecord.from_row(row) for row in rows)


def compact_config_by_id(con, config_id: int) -> CompactConfigRecord | None:
    """The compact ``seg_config`` row with *config_id*, or ``None`` when absent."""
    row = con.execute(
        f"SELECT {', '.join(SEG_CONFIG_COLS)} FROM {SEG_CONFIG_TABLE} WHERE config_id = ? ORDER BY config_id LIMIT 1",
        [int(config_id)],
    ).fetchone()
    return CompactConfigRecord.from_row(row) if row is not None else None


def compact_segments_by_config_song(con, config_id: int, song_id: str) -> tuple[CompactSegRecord, ...]:
    """Every compact ``seg_meta`` row for ``(config_id, song_id)`` ordered by ``seg_id``."""
    rows = con.execute(
        f"SELECT {', '.join(SEG_META_COLS)} FROM {SEG_META_TABLE} WHERE config_id = ? AND song_id = ? ORDER BY seg_id",
        [int(config_id), song_id],
    ).fetchall()
    return tuple(CompactSegRecord.from_row(row) for row in rows)


def compact_catalog_songs_by_config(con, config_id: int) -> tuple[CatalogSongRecord, ...]:
    """Every compact ``catalog_song`` row for *config_id* (ordered by ``song_id``)."""
    rows = con.execute(
        f"SELECT {', '.join(CATALOG_SONG_COLS)} FROM {CATALOG_SONG_TABLE} WHERE config_id = ? ORDER BY song_id",
        [int(config_id)],
    ).fetchall()
    return tuple(CatalogSongRecord.from_row(row) for row in rows)


def compact_catalog_song(con, config_id: int, song_id: str) -> CatalogSongRecord | None:
    """The compact ``catalog_song`` leaf for ``(config_id, song_id)``, or ``None`` when absent."""
    row = con.execute(
        f"SELECT {', '.join(CATALOG_SONG_COLS)} FROM {CATALOG_SONG_TABLE} "
        "WHERE config_id = ? AND song_id = ? ORDER BY song_id LIMIT 1",
        [int(config_id), song_id],
    ).fetchone()
    return CatalogSongRecord.from_row(row) if row is not None else None
