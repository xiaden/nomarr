"""Calibrated tags database updater workflow.

This workflow applies calibration to existing library files without re-running ML inference.
It reconstructs HeadOutput objects from stored numeric tags and calibration metadata,
then re-runs aggregation to update mood-* tags IN THE DATABASE ONLY.

File writes are handled separately by the write_file_tags_wf / reconcile pipeline,
which reads the updated DB mood tags and writes them to audio files on disk.

ARCHITECTURE:
- This is a PURE WORKFLOW that orchestrates: DB reads, calibration application, DB writes
- It does NOT write to audio files on disk
- It does NOT import services, interfaces, or the application object
- Callers must provide all dependencies: db, models_dir, namespace, calibrate_heads flag

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance with library and conn accessors
- `models_dir: str` - Path to models directory (for head metadata)
- `params: WriteCalibratedTagsParams` - Parameters containing:
  - `file_path: str` - Path to audio file
  - `models_dir: str` - Path to models directory
  - `namespace: str` - Tag namespace (e.g., "nom")
  - `version_tag_key: str` - Key for version tag in Navidrome
  - `calibrate_heads: bool` - Whether to use versioned calibration files (dev mode)

USAGE:
    from nomarr.workflows.calibration.write_calibrated_tags_wf import write_calibrated_tags_wf
    from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams

    params = WriteCalibratedTagsParams(
        file_path="/path/to/audio.mp3",
        models_dir="/app/models",
        namespace="nom",
        version_tag_key="nom_version",
        calibrate_heads=False
    )
    write_calibrated_tags_wf(db=database_instance, params=params)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_sync_comp import get_library_file
from nomarr.components.ml.calibration.ml_calibration_state_comp import (
    get_calibration_version,
    update_file_calibration_hash,
)
from nomarr.components.ml.inference.ml_segment_stats_store_comp import get_segment_stats_for_file
from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads
from nomarr.components.processing.file_write_comp import get_nomarr_tags, save_mood_tags
from nomarr.components.tagging.tagging_aggregation_comp import aggregate_mood_tiers
from nomarr.components.tagging.tagging_reconstruction_comp import (
    reconstruct_head_outputs_from_stats,
)
from nomarr.helpers.dto.tags_dto import Tags
from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf

if TYPE_CHECKING:
    from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
    from nomarr.helpers.dto.ml_dto import HeadOutput
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


@dataclass
class LoadLibraryStateResult:
    """Result from _load_library_state() private helper (workflow-internal)."""

    file_id: int
    all_tags: dict[str, Any]


@dataclass
class BatchContext:
    """Pre-computed invariants for batch calibration apply.

    When processing many files, these values are computed once and reused,
    avoiding redundant DB queries and filesystem scans per file.

    Attributes:
        heads: Discovered HeadInfo objects from discover_heads()
        calibrations: Calibration data from load_calibrations_from_db_wf()
        calibration_version: Global calibration version string
        prefetched_file_docs: Optional pre-fetched file records keyed by path.
            When populated, _load_library_state uses it instead of DB queries.
        prefetched_tags: Optional pre-fetched nomarr tags keyed by file_id.
            When populated, avoids per-file tag DB queries.
        prefetched_stats: Optional pre-fetched segment stats keyed by file_id.
            When populated, avoids per-file stats DB queries.
        pending_mood_tags: Accumulated (file_id, mood_tags) for deferred batch write.
        pending_calibration_hashes: Accumulated file_ids for deferred batch calibration mark.

    """

    heads: list[Any]
    calibrations: dict[str, Any]
    calibration_version: str | None
    prefetched_file_docs: dict[str, dict[str, Any]] | None = None
    prefetched_tags: dict[str, Tags] | None = None
    prefetched_stats: dict[str, list[dict[str, Any]]] | None = None
    pending_mood_tags: list[tuple[str, Tags]] = field(default_factory=list)
    pending_calibration_hashes: list[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


def _load_library_state(
    db: Database,
    file_path: str,
    batch_ctx: BatchContext | None = None,
) -> LoadLibraryStateResult:
    """Load file metadata and tags from library database.

    When ``batch_ctx`` is supplied and its prefetched caches are populated,
    all DB round-trips are bypassed.

    Args:
        db: Database instance
        file_path: Path to audio file
        batch_ctx: Optional batch context with pre-fetched data.

    Returns:
        LoadLibraryStateResult with file_id and all_tags

    Raises:
        FileNotFoundError: If file not found in library database

    """
    # Use prefetched file doc when available
    if batch_ctx is not None and batch_ctx.prefetched_file_docs is not None:
        library_file = batch_ctx.prefetched_file_docs.get(file_path)
    else:
        library_file = get_library_file(db, file_path)

    if not library_file:
        msg = f"File not in library: {file_path}"
        raise FileNotFoundError(msg)

    file_id = library_file["_id"]

    # Use prefetched tags when available
    if batch_ctx is not None and batch_ctx.prefetched_tags is not None:
        tags = batch_ctx.prefetched_tags.get(str(file_id), Tags(items=()))
    else:
        tags = get_nomarr_tags(db, file_id)

    all_tags = {}
    for tag in tags:
        name = tag.key
        key = name.removeprefix("nom:")
        all_tags[key] = tag.value[0] if len(tag.value) == 1 else tag.value
    if not all_tags:
        logger.warning("[calibrated_tags] No tags found for %s", file_path)
    return LoadLibraryStateResult(file_id=file_id, all_tags=all_tags)


def _filter_numeric_tags(all_tags: dict[str, Any], version_tag_key: str) -> dict[str, float | int]:
    """Filter to numeric tags only, excluding mood-* and version tags.

    Args:
        all_tags: All tags for the file
        version_tag_key: Un-namespaced key for the tagger version tag (e.g., "nom_version")

    Returns:
        Dictionary of numeric tags only

    """

    def _is_version_key(key: str) -> bool:
        if not isinstance(key, str):
            return False
        if key == version_tag_key:
            return True
        return ":" in key and key.split(":", 1)[1] == version_tag_key

    numeric_tags = {
        k: v
        for k, v in all_tags.items()
        if isinstance(v, int | float)
        and not k.endswith(":mood-strict")
        and not k.endswith(":mood-regular")
        and not k.endswith(":mood-loose")
        and not _is_version_key(k)
    }
    if not numeric_tags:
        logger.warning("[calibrated_tags] No numeric tags found")
    logger.debug("[calibrated_tags] Found %d numeric tags", len(numeric_tags))
    return numeric_tags


def _load_calibrations_from_db(db: Database) -> dict[str, Any]:
    """Load calibrations from calibration_state database table.

    Args:
        db: Database instance

    Returns:
        Dictionary of calibration data (label -> {p5, p95})
        Empty dict if no calibrations exist (initial state)

    """
    calibrations = load_calibrations_from_db_wf(db)
    if not calibrations:
        logger.debug("[calibrated_tags] No calibrations in database (initial state)")
    else:
        logger.debug("[calibrated_tags] Loaded %d calibrations from database", len(calibrations))
    return calibrations


def _compute_mood_tags(head_outputs: list[HeadOutput]) -> Tags:
    """Aggregate HeadOutput objects into mood-* tags.

    Args:
        head_outputs: List of HeadOutput objects

    Returns:
        Tags DTO with mood tags

    """
    mood_tags_dict = aggregate_mood_tiers(head_outputs)
    if not mood_tags_dict:
        logger.debug("[calibrated_tags] No mood tags generated")
        return Tags(items=())
    logger.debug("[calibrated_tags] Generated %d mood tags", len(mood_tags_dict))
    return Tags.from_dict(mood_tags_dict)


def write_calibrated_tags_wf(
    db: Database,
    params: WriteCalibratedTagsParams,
    *,
    batch_ctx: BatchContext | None = None,
) -> None:
    """Update mood-* tags in the database by re-applying calibration.

    DB-only operation — does NOT write to audio files on disk.
    File writes are handled by the reconcile / write_file_tags_wf pipeline
    which reads the updated DB mood tags and writes them to disk.

    This workflow:
    1. Loads numeric tags from DB (model_key -> value)
    2. Loads calibration metadata from calibration_state
    3. Discovers HeadInfo from models directory
    4. Reconstructs HeadOutput objects from tags + calibration
    5. Re-runs aggregation to compute mood-* tags
    6. Updates mood-* tags in DB
    7. Records calibration_hash on the file record

    This is much faster than retagging because it skips ML inference entirely,
    reusing the numeric scores already stored in the database.

    Args:
        db: Database instance (must provide library, tags accessors)
        params: WriteCalibratedTagsParams containing:
            - file_path: Absolute path to audio file
            - models_dir: Path to models directory
            - namespace: Tag namespace (e.g., "nom")
            - version_tag_key: Un-namespaced key for version tag
            - calibrate_heads: Whether to use versioned calibration files
        batch_ctx: Pre-computed batch context (batch optimization).
            When provided, reuses cached heads and calibrations
            instead of re-computing them for every file.  DB writes
            are deferred to the batch flush.

    Returns:
        None (updates DB in-place)

    Raises:
        FileNotFoundError: If file not found in library database
        ValueError: If no heads discovered or no tags found

    """
    file_path = params.file_path
    models_dir = params.models_dir
    version_tag_key = params.version_tag_key
    logger.debug("[calibrated_tags] Processing %s", file_path)
    library_state = _load_library_state(db, file_path, batch_ctx=batch_ctx)
    file_id = library_state.file_id
    all_tags = library_state.all_tags
    if not all_tags:
        return
    numeric_tags = _filter_numeric_tags(all_tags, version_tag_key)
    if not numeric_tags:
        return

    # Use cached values from batch context when available
    heads: list[Any] | None = batch_ctx.heads if batch_ctx is not None else None
    calibrations = batch_ctx.calibrations if batch_ctx is not None else _load_calibrations_from_db(db)

    # Load segment_scores_stats — use prefetched bulk data if available
    if batch_ctx is not None and batch_ctx.prefetched_stats is not None:
        stats_list = batch_ctx.prefetched_stats.get(str(file_id), [])
    else:
        stats_list = get_segment_stats_for_file(db, str(file_id))
    segment_stats_by_head: dict[str, list[dict[str, Any]]] = {}
    for doc in stats_list:
        head_name = doc.get("head_name")
        label_stats = doc.get("label_stats", [])
        if head_name and label_stats:
            segment_stats_by_head[head_name] = label_stats

    if not segment_stats_by_head:
        logger.warning(
            f"[calibrated_tags] No segment_scores_stats found for {file_path}, skipping (file needs reprocessing)"
        )
        return

    # Use discovered heads or discover them
    heads_list: list[Any]
    if heads is None:
        heads_list = discover_heads(models_dir, db)
        if not heads_list:
            msg = f"No heads discovered in {models_dir}"
            raise ValueError(msg)
    else:
        heads_list = heads

    # Reconstruct HeadOutput objects using segment stats (matches ML tier logic).
    # Pass calibrations so they are applied BEFORE tier assignment.
    head_outputs = reconstruct_head_outputs_from_stats(
        numeric_tags=numeric_tags,
        segment_stats_by_head=segment_stats_by_head,
        head_infos=heads_list,
        calibrations=calibrations,
    )
    if not head_outputs:
        return
    mood_tags = _compute_mood_tags(head_outputs)
    # mood_tags may be empty when all labels conflict or scores are below threshold.
    # Empty is a valid calibration result — we still write it (to clear stale tiers)
    # and update calibration_hash so the file is not re-queued on every apply run.
    if not mood_tags:
        logger.debug("[calibrated_tags] No mood tags produced for %s — writing empty tiers and marking hash", file_path)

    # Write to DB — batch mode defers, single-file mode writes immediately
    if batch_ctx is not None:
        with batch_ctx._lock:
            batch_ctx.pending_mood_tags.append((str(file_id), mood_tags))
            global_version = batch_ctx.calibration_version
            if global_version:
                batch_ctx.pending_calibration_hashes.append(str(file_id))
    else:
        save_mood_tags(db, str(file_id), mood_tags)
        global_version = get_calibration_version(db)
        if global_version:
            update_file_calibration_hash(db, str(file_id))
            logger.debug("[calibrated_tags] Updated calibration_hash for %s", file_path)
        logger.debug("[calibrated_tags] Updated mood tags in DB for %s", file_path)
