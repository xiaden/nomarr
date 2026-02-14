"""Calibrated tags writer workflow.

This workflow applies calibration to existing library files without re-running ML inference.
It reconstructs HeadOutput objects from stored numeric tags and calibration metadata,
then re-runs aggregation to update mood-* tags.

ARCHITECTURE:
- This is a PURE WORKFLOW that orchestrates: DB reads, calibration application, file writes
- It does NOT import services, interfaces, or the application object
- Callers must provide all dependencies: db, models_dir, namespace, calibrate_heads flag

EXPECTED DEPENDENCIES:
- `db: Database` - Database instance with library and conn accessors
- `models_dir: str` - Path to models directory (for loading calibration sidecars and head metadata)
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
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from nomarr.components.library.file_sync_comp import get_library_file
from nomarr.components.library.scan_lifecycle_comp import save_folder_record
from nomarr.components.ml.calibration_state_comp import (
    get_calibration_version,
    update_file_calibration_hash,
)
from nomarr.components.ml.ml_discovery_comp import discover_heads
from nomarr.components.processing.file_write_comp import get_nomarr_tags, save_mood_tags
from nomarr.components.tagging.tagging_aggregation_comp import aggregate_mood_tiers
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dto.ml_dto import HeadOutput
from nomarr.helpers.dto.tags_dto import Tags

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from pathlib import Path

    from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database

@dataclass
class LoadLibraryStateResult:
    """Result from _load_library_state() private helper (workflow-internal)."""

    file_id: int
    all_tags: dict[str, Any]
    chromaprint: str | None


@dataclass
class BatchContext:
    """Pre-computed invariants for batch calibration apply.

    When processing many files, these values are computed once and reused,
    avoiding redundant DB queries and filesystem scans per file.

    Attributes:
        heads: Discovered HeadInfo objects from discover_heads()
        calibrations: Calibration data from load_calibrations_from_db_wf()
        calibration_version: Global calibration version string
        library_roots: Mapping of library_id -> resolved root Path
        writer: Reusable TagWriter instance
        pending_folders: Folders needing mtime update after batch completes.
            Maps folder_abs_str -> (library_id, library_root).

    """

    heads: list[Any]
    calibrations: dict[str, Any]
    calibration_version: str | None
    library_roots: dict[str, Path]
    writer: TagWriter
    pending_folders: dict[str, tuple[str, Path]] = field(default_factory=dict)

def _load_library_state(db: Database, file_path: str, namespace: str) -> LoadLibraryStateResult:
    """Load file metadata and tags from library database.

    Args:
        db: Database instance
        file_path: Path to audio file
        namespace: Tag namespace

    Returns:
        LoadLibraryStateResult with file_id, all_tags, and chromaprint

    Raises:
        FileNotFoundError: If file not found in library database

    """
    library_file = get_library_file(db, file_path)
    if not library_file:
        msg = f"File not in library: {file_path}"
        raise FileNotFoundError(msg)
    file_id = library_file["_id"]
    chromaprint = library_file.get("chromaprint")
    tags = get_nomarr_tags(db, file_id)
    all_tags = {}
    for tag in tags:
        rel = tag.key
        key = rel.removeprefix("nom:")
        all_tags[key] = tag.value[0] if len(tag.value) == 1 else tag.value
    if not all_tags:
        logger.warning(f"[calibrated_tags] No tags found for {file_path}")
    return LoadLibraryStateResult(file_id=file_id, all_tags=all_tags, chromaprint=chromaprint)

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
    numeric_tags = {k: v for k, v in all_tags.items() if isinstance(v, int | float) and (not k.endswith(":mood-strict")) and (not k.endswith(":mood-regular")) and (not k.endswith(":mood-loose")) and (not _is_version_key(k))}
    if not numeric_tags:
        logger.warning("[calibrated_tags] No numeric tags found")
    logger.debug(f"[calibrated_tags] Found {len(numeric_tags)} numeric tags")
    return numeric_tags

def _discover_head_mappings(models_dir: str, namespace: str, numeric_tags: dict[str, float | int], heads: list[Any] | None = None) -> dict[str, tuple[Any, str]]:
    """Discover heads and build mapping from tag keys to HeadInfo.

    Args:
        models_dir: Path to models directory
        namespace: Tag namespace
        numeric_tags: Numeric tags to match against heads
        heads: Pre-discovered HeadInfo objects (batch optimization).
            When provided, skips the expensive discover_heads() filesystem scan.

    Returns:
        Dictionary mapping tag_key -> (HeadInfo, label)

    Raises:
        ValueError: If no heads discovered

    """
    if heads is None:
        heads = discover_heads(models_dir)
    if not heads:
        msg = f"No heads discovered in {models_dir}"
        raise ValueError(msg)
    head_by_model_key: dict[str, tuple[Any, str]] = {}
    for head in heads:
        for label in head.labels:
            normalized_label = label.lower().replace(" ", "_")
            for tag_key in numeric_tags:
                clean_key = tag_key[len(namespace) + 1:] if tag_key.startswith(f"{namespace}:") else tag_key
                if normalized_label in clean_key.lower():
                    head_by_model_key[tag_key] = (head, label)
    logger.debug(f"[calibrated_tags] Matched {len(head_by_model_key)} tags to heads")
    return head_by_model_key

def _load_calibrations_from_db(db: Database) -> dict[str, Any]:
    """Load calibrations from calibration_state database table.

    Args:
        db: Database instance

    Returns:
        Dictionary of calibration data (label -> {p5, p95})
        Empty dict if no calibrations exist (initial state)

    """
    from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf
    calibrations = load_calibrations_from_db_wf(db)
    if not calibrations:
        logger.debug("[calibrated_tags] No calibrations in database (initial state)")
    else:
        logger.debug(f"[calibrated_tags] Loaded {len(calibrations)} calibrations from database")
    return calibrations

def _reconstruct_head_outputs(numeric_tags: dict[str, float | int], head_by_model_key: dict[str, tuple[Any, str]], namespace: str, calibrations: dict[str, Any]) -> list[HeadOutput]:
    """Reconstruct HeadOutput objects from numeric tags and calibration data.

    Note: calibration_id set to None for all outputs (legacy field, not used).

    Args:
        numeric_tags: Numeric tags from database
        head_by_model_key: Mapping of tag_key -> (HeadInfo, label)
        namespace: Tag namespace
        calibrations: Calibration data (label -> {p5, p95})

    Returns:
        List of HeadOutput objects

    """
    head_outputs: list[HeadOutput] = []
    for tag_key, value in numeric_tags.items():
        if tag_key not in head_by_model_key:
            continue
        head_info, label = head_by_model_key[tag_key]
        clean_key = tag_key[len(namespace) + 1:] if tag_key.startswith(f"{namespace}:") else tag_key
        tier: str | None = None
        if head_info.is_mood_source or head_info.is_regression_mood_source:
            calibrated_value = value
            if calibrations and clean_key in calibrations:
                from nomarr.components.ml.ml_calibration_comp import apply_minmax_calibration
                calibrated_value = apply_minmax_calibration(value, calibrations[clean_key])
            if calibrated_value >= 0.7:
                tier = "high"
            elif calibrated_value >= 0.5:
                tier = "medium"
            elif calibrated_value >= 0.3:
                tier = "low"
        head_outputs.append(HeadOutput(head=head_info, model_key=clean_key, label=label, value=value, tier=tier, calibration_id=None))
    if not head_outputs:
        logger.warning("[calibrated_tags] No HeadOutput objects reconstructed")
    logger.info(f"[calibrated_tags] Reconstructed {len(head_outputs)} HeadOutput objects")
    return head_outputs

def _compute_mood_tags(head_outputs: list[HeadOutput], calibrations: dict[str, Any]) -> Tags:
    """Aggregate HeadOutput objects into mood-* tags.

    Args:
        head_outputs: List of HeadOutput objects
        calibrations: Calibration parameters

    Returns:
        Tags DTO with mood tags

    """
    mood_tags_dict = aggregate_mood_tiers(head_outputs, calibrations=calibrations)
    if not mood_tags_dict:
        logger.debug("[calibrated_tags] No mood tags generated")
        return Tags(items=())
    logger.info(f"[calibrated_tags] Generated {len(mood_tags_dict)} mood tags")
    return Tags.from_dict(mood_tags_dict)

def _update_db_and_file(db: Database, file_id: str, file_path: str, namespace: str, mood_tags: Tags, chromaprint: str | None=None, *, batch_ctx: BatchContext | None = None) -> None:
    """Update mood-* tags in database and file.

    Uses atomic safe writes to prevent file corruption.

    Args:
        db: Database instance
        file_id: File ID in library
        file_path: Path to audio file
        namespace: Tag namespace
        mood_tags: Tags DTO with mood tags to write
        chromaprint: Audio fingerprint for verification (from library_files)
        batch_ctx: Pre-computed batch context (batch optimization).
            When provided, skips redundant library root lookups and
            defers folder mtime updates.

    """
    count = save_mood_tags(db, file_id, mood_tags)
    logger.debug(f"[calibrated_tags] Updated {count} mood tags in DB")

    if batch_ctx is not None:
        # Batch mode: skip expensive per-file library lookups
        from pathlib import Path as PathLib
        file_abs = PathLib(file_path).resolve()

        # Find library root by in-memory prefix matching
        matched_library_id: str | None = None
        matched_root: PathLib | None = None
        matched_root_len = 0
        for lib_id, root in batch_ctx.library_roots.items():
            try:
                file_abs.relative_to(root)
                root_len = len(str(root))
                if root_len > matched_root_len:
                    matched_library_id = lib_id
                    matched_root = root
                    matched_root_len = root_len
            except ValueError:
                continue

        if matched_root and matched_library_id and chromaprint:
            from nomarr.helpers.dto.path_dto import LibraryPath
            relative_str = str(file_abs.relative_to(matched_root)).replace("\\", "/")
            library_path = LibraryPath(
                relative=relative_str,
                absolute=file_abs,
                library_id=matched_library_id,
                status="valid",
            )
            result = batch_ctx.writer.write_safe(library_path, mood_tags, matched_root, chromaprint)
            if not result.success:
                msg = f"Safe write failed: {result.error}"
                raise RuntimeError(msg)
            # Defer folder mtime update — collect for batch processing
            folder_key = str(file_abs.parent)
            if folder_key not in batch_ctx.pending_folders:
                batch_ctx.pending_folders[folder_key] = (matched_library_id, matched_root)
        elif not chromaprint:
            logger.warning("[calibrated_tags] No chromaprint - using unsafe direct write")
            writer = batch_ctx.writer
            from pathlib import Path as PathLib2

            from nomarr.helpers.dto.path_dto import LibraryPath
            library_path = LibraryPath(
                relative="",
                absolute=PathLib2(file_path),
                library_id=None,
                status="valid",
            )
            writer.write(library_path, mood_tags)
        return

    # Single-file mode: full validation path
    from nomarr.components.infrastructure.path_comp import build_library_path_from_input, get_library_root
    library_path = build_library_path_from_input(file_path, db)
    library_root = get_library_root(library_path, db)
    writer = TagWriter(overwrite=True, namespace=namespace)
    if chromaprint and library_root:
        result = writer.write_safe(library_path, mood_tags, library_root, chromaprint)
        if not result.success:
            msg = f"Safe write failed: {result.error}"
            raise RuntimeError(msg)
        if library_path.library_id:
            _update_folder_mtime_after_write(db, library_path, library_root)
    else:
        logger.warning("[calibrated_tags] No chromaprint - using unsafe direct write")
        writer.write(library_path, mood_tags)
    logger.info(f"[calibrated_tags] Wrote calibrated tags for {file_path}")

def _update_folder_mtime_after_write(db: Database, library_path: LibraryPath, library_root: Path) -> None:
    """Update folder mtime in DB after writing tags to a file."""
    import os
    if not library_path.library_id:
        return
    folder_abs = library_path.absolute.parent
    try:
        folder_mtime = int(os.stat(folder_abs).st_mtime * 1000)
        folder_rel = str(folder_abs.relative_to(library_root)).replace("\\", "/")
        if folder_abs == library_root:
            folder_rel = ""
        from nomarr.helpers.files_helper import is_audio_file
        file_count = sum(1 for f in os.listdir(folder_abs) if is_audio_file(f) and os.path.isfile(os.path.join(folder_abs, f)))
        save_folder_record(db, library_path.library_id, folder_rel, folder_mtime, file_count)
        logger.debug(f"[calibrated_tags] Updated folder mtime: {folder_rel}")
    except Exception as e:
        logger.warning(f"[calibrated_tags] Failed to update folder mtime: {e}")

def write_calibrated_tags_wf(db: Database, params: WriteCalibratedTagsParams, *, batch_ctx: BatchContext | None = None) -> None:
    """Write calibrated tags to a file by applying calibration to existing numeric tags.

    This workflow:
    1. Loads numeric tags from DB (model_key -> value)
    2. Loads calibration metadata from library_files.calibration
    3. Discovers HeadInfo from models directory
    4. Reconstructs HeadOutput objects from tags + calibration
    5. Re-runs aggregation to compute mood-* tags
    6. Updates mood-* tags in DB and file

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
            When provided, reuses cached heads, calibrations, and library roots
            instead of re-computing them for every file.

    Returns:
        None (updates file tags in-place)

    Raises:
        FileNotFoundError: If file not found in library database
        ValueError: If no heads discovered or no tags found

    """
    file_path = params.file_path
    models_dir = params.models_dir
    namespace = params.namespace
    version_tag_key = params.version_tag_key
    logger.debug(f"[calibrated_tags] Processing {file_path}")
    library_state = _load_library_state(db, file_path, namespace)
    file_id = library_state.file_id
    all_tags = library_state.all_tags
    chromaprint = library_state.chromaprint
    if not all_tags:
        return
    numeric_tags = _filter_numeric_tags(all_tags, version_tag_key)
    if not numeric_tags:
        return

    # Use cached values from batch context when available
    heads = batch_ctx.heads if batch_ctx is not None else None
    calibrations = batch_ctx.calibrations if batch_ctx is not None else _load_calibrations_from_db(db)

    head_by_model_key = _discover_head_mappings(models_dir, namespace, numeric_tags, heads=heads)
    head_outputs = _reconstruct_head_outputs(numeric_tags, head_by_model_key, namespace, calibrations)
    if not head_outputs:
        return
    mood_tags = _compute_mood_tags(head_outputs, calibrations)
    if not mood_tags:
        return
    _update_db_and_file(db, str(file_id), file_path, namespace, mood_tags, chromaprint, batch_ctx=batch_ctx)

    # Update calibration hash
    if batch_ctx is not None:
        global_version = batch_ctx.calibration_version
    else:
        global_version = get_calibration_version(db)
    if global_version:
        update_file_calibration_hash(db, str(file_id), global_version)
        logger.debug(f"[calibrated_tags] Updated calibration_hash for {file_path}")
