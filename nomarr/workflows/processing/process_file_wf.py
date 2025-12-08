"""
High-level audio file processing workflow.

This is a PURE WORKFLOW module that orchestrates the complete audio tagging pipeline:
- Model discovery and backbone grouping
- Embedding computation per backbone
- Head prediction execution
- Score pooling and decision logic
- Mood tier aggregation (including regression-based tiers)
- Calibration loading and application
- Tag writing to audio files
- Optional library database updates

ARCHITECTURE:
- This workflow is domain logic that coordinates ML, tagging, and persistence layers.
- It does NOT import or use the DI container, services, or application object.
- Callers (typically services) must provide all dependencies:
  - File path
  - ProcessorConfig with all processing parameters
  - Optional Database instance for persistence updates

EXPECTED DEPENDENCIES:
- `config: ProcessorConfig` - Typed configuration with:
  - models_dir: str
  - min_duration_s, allow_short: float, bool
  - batch_size: int
  - overwrite_tags: bool
  - namespace: str
  - version_tag_key, tagger_version: str
  - calibrate_heads: bool

- `db: Database | None` - Optional database instance for library updates
  - If provided, must support: db.library_files.*, db.file_tags.*, db.conn
  - Used to update library_files and file_tags after successful tagging

USAGE:
    from nomarr.workflows.processing.process_file_wf import process_file_workflow
    from nomarr.helpers.dto.processing_dto import ProcessorConfig

    config = ProcessorConfig(
        models_dir="/app/models",
        namespace="nom",
        # ... other config values
    )

    result = process_file_workflow(
        path="/path/to/audio.mp3",
        config=config,
        db=database_instance  # optional
    )
"""

from __future__ import annotations

import gc
import logging
import time
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia
from nomarr.components.ml.ml_discovery_comp import HeadInfo, discover_heads
from nomarr.components.ml.ml_embed_comp import pool_scores
from nomarr.components.ml.ml_heads_comp import run_head_decision
from nomarr.components.ml.ml_inference_comp import compute_embeddings_for_backbone, make_head_only_predictor_batched
from nomarr.components.tagging.tagging_aggregation_comp import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    load_calibrations,
    normalize_tag_label,
)
from nomarr.components.tagging.tagging_writer_comp import TagWriter
from nomarr.helpers.dto.library_dto import UpdateLibraryFileFromTagsParams
from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams
from nomarr.helpers.dto.processing_dto import ProcessFileResult, ProcessorConfig

# Get Essentia version for tag versioning
ESSENTIA_VERSION = backend_essentia.get_version()

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


@dataclass
class ProcessHeadPredictionsResult:
    """Result from _process_head_predictions() private helper (workflow-internal)."""

    heads_succeeded: int
    head_results: dict[str, Any]
    regression_heads: list[tuple[Any, list[float]]]  # list[tuple[HeadInfo, list[float]]]
    all_head_outputs: list[Any]  # list[HeadOutput]


def _discover_and_group_heads(models_dir: str) -> tuple[list[HeadInfo], dict[str, list[HeadInfo]]]:
    """
    Discover head models and group them by backbone for embedding reuse.

    Args:
        models_dir: Directory containing model files

    Returns:
        Tuple of (all_heads, heads_by_backbone_dict)

    Raises:
        RuntimeError: If no heads found in models_dir
    """
    heads = discover_heads(models_dir)
    if not heads:
        raise RuntimeError(f"No head models found under {models_dir}")

    logging.info(f"[processor] Discovered {len(heads)} heads")

    # DEBUG: Log all heads by backbone and type
    from collections import Counter

    by_backbone = Counter(h.backbone for h in heads)
    by_type = Counter(h.head_type for h in heads)
    logging.info(f"[processor] Heads by backbone: {dict(by_backbone)}")
    logging.info(f"[processor] Heads by type: {dict(by_type)}")

    for h in heads:
        logging.debug(f"[processor]   - {h.name} ({h.backbone}/{h.head_type}, {len(h.sidecar.labels)} labels)")

    # Group heads by backbone for embedding reuse
    heads_by_backbone = defaultdict(list)
    for h in heads:
        heads_by_backbone[h.backbone].append(h)

    logging.info(
        f"[processor] Grouped {len(heads)} heads into {len(heads_by_backbone)} backbones: "
        f"{ {k: len(v) for k, v in heads_by_backbone.items()} }"
    )

    return heads, dict(heads_by_backbone)


def _compute_embeddings_for_backbone(
    backbone: str,
    first_head: HeadInfo,
    path: str,
    config: ProcessorConfig,
) -> tuple[np.ndarray, float]:
    """
    Compute embeddings for a single backbone.

    Args:
        backbone: Name of the backbone model
        first_head: First head in the backbone group (for params)
        path: Path to audio file
        config: Processor configuration

    Returns:
        Tuple of (embeddings_2d, duration)

    Raises:
        RuntimeError: If audio is too short or embedding computation fails
    """
    target_sr = first_head.sidecar.sr
    seg_len, hop_len = first_head.sidecar.segment_hop
    emb_graph = first_head.embedding_graph

    logging.info(f"[processor] Computing embeddings for {backbone}: sr={target_sr}")

    t_emb = time.time()
    params = ComputeEmbeddingsForBackboneParams(
        backbone=backbone,
        emb_graph=emb_graph,
        target_sr=target_sr,
        segment_s=seg_len,
        hop_s=hop_len,
        path=path,
        min_duration_s=config.min_duration_s,
        allow_short=config.allow_short,
    )
    embeddings_2d, duration = compute_embeddings_for_backbone(params=params)

    logging.info(
        f"[processor] Embeddings for {backbone} computed in {time.time() - t_emb:.1f}s: shape={embeddings_2d.shape}"
    )

    return embeddings_2d, duration


def _process_head_predictions(
    backbone_heads: list[HeadInfo],
    embeddings_2d: np.ndarray,
    config: ProcessorConfig,
    tags_accum: dict[str, Any],
) -> ProcessHeadPredictionsResult:
    """
    Process all head predictions for a single backbone using cached embeddings.

    Args:
        backbone_heads: List of heads for this backbone
        embeddings_2d: Pre-computed embeddings
        config: Processor configuration
        tags_accum: Accumulator dict for tags (modified in place)

    Returns:
        Tuple of (heads_succeeded, head_results, regression_heads, all_head_outputs)
    """
    heads_succeeded = 0
    head_results: dict[str, Any] = {}
    regression_heads: list[tuple[HeadInfo, list[float]]] = []
    all_head_outputs: list[Any] = []

    # Initialize calibration map on tags_accum if not present
    if not hasattr(tags_accum, "_calibration_map"):
        tags_accum._calibration_map = {}  # type: ignore

    for head_info in backbone_heads:
        head_name = head_info.name

        try:
            t_head = time.time()

            # Build head-only predictor (batched with explicit batch size for VRAM control)
            head_predict_fn = make_head_only_predictor_batched(head_info, embeddings_2d, batch_size=config.batch_size)

            # Run predictions for ALL segments (potentially in multiple batches)
            segment_scores = head_predict_fn()  # Returns [num_segments, num_classes]

            # Pool segment predictions
            pooled_vec = pool_scores(segment_scores, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")

        except Exception as e:
            logging.error(f"[processor] Processing error for {head_name}: {e}", exc_info=True)
            head_results[head_name] = {"status": "error", "error": str(e), "stage": "processing"}
            continue

        try:
            decision = run_head_decision(head_info.sidecar, pooled_vec, prefix="")

            # Build versioned tag keys using runtime framework version and model metadata
            # Normalize labels (non_happy -> not_happy) before building keys
            # Capture head_info in closure to avoid late binding issue
            # Track calibration IDs for storage in database
            calib_map = tags_accum._calibration_map  # type: ignore

            def _build_key(label: str, head: HeadInfo = head_info, calib_map: dict = calib_map) -> str:
                model_key, calibration_id = head.build_versioned_tag_key(
                    normalize_tag_label(label),
                    framework_version=ESSENTIA_VERSION,
                    calib_method="none",
                    calib_version=0,
                )
                calib_map[model_key] = calibration_id
                return model_key

            # Convert HeadDecision to HeadOutput objects for aggregation
            head_outputs = decision.to_head_outputs(
                head_info=head_info,
                framework_version=ESSENTIA_VERSION,
                key_builder=_build_key,
            )
            all_head_outputs.extend(head_outputs)

            # Get numeric tags (no *_tier tags emitted)
            head_tags = decision.as_tags(key_builder=_build_key)

            # DEBUG: Log tag generation details
            logging.debug(f"[processor] Head {head_name} ({head_info.head_type}) produced {len(head_tags)} tags")
            if head_tags:
                sample_keys = list(head_tags.keys())[:3]
                logging.debug(f"[processor]   Sample keys: {sample_keys}")

            # Combined log: processing complete + tags produced
            logging.info(
                f"[processor] Head {head_name} complete: {len(segment_scores)} patches → {len(head_tags)} tags "
                f"in {time.time() - t_head:.1f}s"
            )

            if len(head_tags) == 0:
                logging.warning(f"[processor] Head {head_name} produced ZERO tags")

            tags_accum.update(head_tags)
            heads_succeeded += 1

            # Capture raw segment predictions for regression heads (approachability, engagement)
            # These will be used to generate mood tier tags with variance-based confidence
            if head_info.is_regression_mood_source:
                # segment_scores is [num_segments, 1] for regression heads, extract first column
                if segment_scores.ndim == 2:
                    raw_values = [float(x) for x in segment_scores[:, 0]]  # Extract first column as float list
                else:
                    raw_values = [float(x) for x in segment_scores]  # Already 1D
                regression_heads.append((head_info, raw_values))
                logging.debug(
                    f"[processor] Captured {len(raw_values)} segment predictions for {head_name} "
                    f"(mean={np.mean(raw_values):.3f}, std={np.std(raw_values):.3f})"
                )

            # Track success with tag count
            head_results[head_name] = {
                "status": "success",
                "tags_written": len(head_tags),
                "decisions": len(decision.details),
            }

        except Exception as e:
            logging.error(f"[processor] Aggregation error for {head_name}: {e}", exc_info=True)
            head_results[head_name] = {"status": "error", "error": str(e), "stage": "aggregation"}
            continue

    return ProcessHeadPredictionsResult(
        heads_succeeded=heads_succeeded,
        head_results=head_results,
        regression_heads=regression_heads,
        all_head_outputs=all_head_outputs,
    )


def _collect_mood_outputs(
    regression_heads: list[tuple[HeadInfo, list[float]]],
    all_head_outputs: list[Any],
    models_dir: str,
    config: ProcessorConfig,
) -> dict[str, Any]:
    """
    Collect and aggregate all mood outputs from classification and regression heads.

    Args:
        regression_heads: List of (HeadInfo, segment_values) tuples for regression heads
        all_head_outputs: List of HeadOutput objects from classification heads
        models_dir: Directory containing model files (for calibrations)
        config: Processor configuration

    Returns:
        Dict of mood-* tags
    """
    # Convert regression head predictions to HeadOutput objects with tier information
    regression_outputs = add_regression_mood_tiers(regression_heads, framework_version=ESSENTIA_VERSION)
    all_head_outputs.extend(regression_outputs)

    logging.debug(f"[processor] Total HeadOutput objects: {len(all_head_outputs)}")

    # Load calibrations if available (conditional - gracefully handles missing files)
    # Use calibrate_heads flag from config to determine which calibration files to load
    calibrations = load_calibrations(models_dir, calibrate_heads=config.calibrate_heads)
    if calibrations:
        logging.info(f"[aggregation] Loaded calibrations for {len(calibrations)} labels")
    else:
        logging.debug("[aggregation] No calibrations found, using raw scores")

    # Aggregate HeadOutput objects into mood-* tags
    mood_tags = aggregate_mood_tiers(all_head_outputs, calibrations=calibrations)

    return mood_tags


def _prepare_file_and_db_tags(
    tags_accum: dict[str, Any],
    config: ProcessorConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Prepare separate tag dicts for database and file writing.

    Args:
        tags_accum: Complete accumulated tags
        config: Processor configuration

    Returns:
        Tuple of (db_tags, file_tags)
    """
    # DB gets ALL tags (numeric scores + mood-*)
    db_tags = dict(tags_accum)  # Copy for DB

    # File writes are filtered based on file_write_mode config
    file_write_mode = config.file_write_mode
    file_tags = select_tags_for_file(db_tags, file_write_mode)

    logging.info(
        f"[processor] Tags prepared: {len(db_tags)} for DB, {len(file_tags)} for file (mode={file_write_mode})"
    )

    # DEBUG: Log calibration map
    if hasattr(tags_accum, "_calibration_map"):
        calib_map = tags_accum._calibration_map  # type: ignore
        logging.debug(f"[processor] Calibration map has {len(calib_map)} entries")

    return db_tags, file_tags


def _write_tags_to_file(
    writer: TagWriter,
    path: str,
    file_tags: dict[str, Any],
) -> None:
    """
    Write filtered tags to audio file.

    Args:
        writer: TagWriter instance
        path: Path to audio file
        file_tags: Tags to write to file
    """
    if file_tags:
        writer.write(path, file_tags)
        logging.info(f"[processor] Wrote {len(file_tags)} tags to file")
    else:
        logging.info("[processor] No tags written to file (file_write_mode=none or empty filter result)")


def _sync_database(
    db: Database | None,
    path: str,
    writer: TagWriter,
    db_tags: dict[str, Any],
    file_tags: dict[str, Any],
    namespace: str,
    tagger_version: str,
    file_write_mode: str,
    calibration_map: dict[str, str] | None = None,
) -> None:
    """
    Sync database with tags and handle file rewriting if needed.

    Args:
        db: Optional Database instance
        path: Path to audio file
        writer: TagWriter instance
        db_tags: Tags to write to database
        file_tags: Tags to write to file (filtered)
        namespace: Tag namespace
        tagger_version: Tagger version string
        file_write_mode: File write mode setting
        calibration_map: Optional mapping of model keys to calibration IDs
    """
    if db is None:
        return

    try:
        from nomarr.workflows.library.scan_library_wf import update_library_file_from_tags

        # Write FULL tags to file temporarily for DB sync
        writer.write(path, db_tags)

        # Pass tagger_version so library scanner marks file as tagged
        params_update = UpdateLibraryFileFromTagsParams(
            file_path=path,
            namespace=namespace,
            tagged_version=tagger_version,
            calibration=calibration_map,
            library_id=None,
        )
        update_library_file_from_tags(db, params_update)
        logging.info(f"[processor] Updated library database for {path} with {len(db_tags)} tags")

        # Now rewrite file with filtered tags if mode is not "full"
        if file_write_mode != "full":
            writer.write(path, file_tags)
            logging.info(f"[processor] Rewrote file with filtered tags (mode={file_write_mode})")
    except Exception as e:
        # Don't fail the entire processing if library update fails
        logging.warning(f"[processor] Failed to update library database: {e}")


def select_tags_for_file(all_tags: dict[str, Any], file_write_mode: str) -> dict[str, Any]:
    """
    Filter tags for file writing based on file_write_mode.

    Args:
        all_tags: Complete tag dict (includes numeric tags, mood-*, version, etc.)
        file_write_mode: "none" | "minimal" | "full"

    Returns:
        Filtered dict of tags to write to media file

    Rules:
        - "none": Empty dict (no file writes)
        - "minimal": Only mood-* tags and version tag
        - "full": All numeric tags + mood-* + version (but never *_tier or calibration)
        - Never write *_tier tags or calibration_id to files
    """
    if file_write_mode == "none":
        return {}

    if file_write_mode == "minimal":
        # Only high-level summary tags
        filtered = {}
        for key, val in all_tags.items():
            if not isinstance(key, str):
                continue
            # Include mood-* tags and version tag
            if key.startswith("mood-") or key.endswith("_version") or "version" in key:
                filtered[key] = val
        return filtered

    # "full" mode: Include numeric tags and mood-*, but exclude tiers and calibration
    filtered = {}
    for key, val in all_tags.items():
        if not isinstance(key, str):
            continue
        # Exclude *_tier tags (internal use only)
        if key.endswith("_tier"):
            continue
        # Exclude calibration-related keys
        if "calibration" in key.lower():
            continue
        filtered[key] = val
    return filtered


def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    db: Database | None = None,
) -> ProcessFileResult:
    """
    Process an audio file through the complete tagging pipeline.

    This is the main workflow entrypoint for audio file processing. It is a pure
    function that orchestrates the entire tagging pipeline without any hidden
    dependencies or side effects beyond file I/O and optional database updates.

    WORKFLOW STEPS:
    1. Discover head models and group by backbone
    2. For each backbone group:
       a. Compute embeddings (reused across heads)
       b. Run all heads for that backbone
       c. Release embeddings to minimize memory
    3. Aggregate mood tiers (including regression-based tiers)
    4. Load and apply calibrations if available
    5. Write tags to audio file
    6. Optionally update library database if db provided

    PURE WORKFLOW GUARANTEES:
    - No global state access (except ESSENTIA_VERSION constant)
    - No DI container or service imports
    - No config loading (caller provides ProcessorConfig)
    - All dependencies explicit in parameters
    - Callable from any context (services, tests, CLI)

    RESPONSIBILITIES (what this function DOES):
    - Discover and group models by backbone
    - Compute embeddings for each backbone
    - Run head predictions on embeddings
    - Pool segment predictions to file-level scores
    - Aggregate mood tiers with calibrations
    - Write tags to audio file via TagWriter
    - Optionally update library database via db parameter

    RESPONSIBILITIES (what this function DOES NOT do):
    - File validation (caller must ensure file exists/readable)
    - Skip/force logic (caller decides whether to call this)
    - Cache management internals (handled by cache module)
    - Config loading or DI (caller injects typed config)
    - Error recovery strategies (caller handles retries)

    Args:
        path: Absolute path to audio file (must exist and be readable)
        config: Typed configuration for processing pipeline (ProcessorConfig)
                Must include: models_dir, namespace, batch_size, tagger_version,
                min_duration_s, allow_short, overwrite_tags, version_tag_key,
                calibrate_heads
        db: Optional Database instance for updating library_files and library_tags
            after successful processing. If None, library updates are skipped.

    Returns:
        ProcessFileResult with:
        - file: path to processed file
        - elapsed: total processing time in seconds
        - duration: audio duration in seconds
        - heads_processed: number of heads that succeeded
        - tags_written: number of tags written to file
        - head_results: per-head processing outcomes
        - mood_aggregations: mood tier counts if written
        - tags: all tags that were written to file

    Raises:
        RuntimeError: If no heads found in models_dir, or all heads fail processing

    Example:
        >>> from nomarr.helpers.dto.processing_dto import ProcessorConfig
        >>> config = ProcessorConfig(models_dir="/app/models", namespace="nom", ...)
        >>> result = process_file_workflow("/music/song.mp3", config, db=my_database)
        >>> print(f"Processed {result.file} in {result.elapsed}s")
    """
    from nomarr.components.ml.ml_cache_comp import check_and_evict_idle_cache, touch_cache

    # Cache management (module handles eviction policy)
    check_and_evict_idle_cache()
    touch_cache()

    start_all = time.time()

    # === STEP 1: Discover and group heads by backbone ===
    _, heads_by_backbone = _discover_and_group_heads(config.models_dir)

    # Initialize state
    writer = TagWriter(overwrite=config.overwrite_tags, namespace=config.namespace)

    # Use a simple class to allow attribute storage (can't set attrs on built-in dict)
    class TagAccumulator(dict):
        pass

    tags_accum = TagAccumulator()
    tags_accum._calibration_map = {}  # type: ignore
    all_head_results: dict[str, Any] = {}
    regression_heads: list[tuple[HeadInfo, list[float]]] = []
    all_head_outputs: list[Any] = []
    total_heads_succeeded = 0
    duration_final = None

    # === STEP 2: Process each backbone group (compute embeddings → run heads → release) ===
    for backbone, backbone_heads in heads_by_backbone.items():
        first_head = backbone_heads[0]

        # Compute embeddings for this backbone
        try:
            embeddings_2d, duration = _compute_embeddings_for_backbone(backbone, first_head, path, config)
            if duration_final is None:
                duration_final = float(duration)
        except RuntimeError as e:
            logging.warning(f"[processor] Skipping backbone {backbone}: {e}")
            for head in backbone_heads:
                all_head_results[head.name] = {"status": "skipped", "reason": str(e)}
            continue

        # Process all heads for this backbone using cached embeddings
        result = _process_head_predictions(backbone_heads, embeddings_2d, config, tags_accum)
        heads_succeeded = result.heads_succeeded
        head_results = result.head_results
        regression_outputs = result.regression_heads
        head_outputs = result.all_head_outputs

        total_heads_succeeded += heads_succeeded
        all_head_results.update(head_results)
        regression_heads.extend(regression_outputs)
        all_head_outputs.extend(head_outputs)

        # Release embeddings to minimize memory usage
        del embeddings_2d
        gc.collect()
        logging.info(f"[processor] Released {backbone} embeddings and predictors from memory")

    if total_heads_succeeded == 0:
        raise RuntimeError("No heads produced decisions; refusing to write tags")

    # === STEP 3: Aggregate mood tiers from all head outputs ===
    mood_tags = _collect_mood_outputs(regression_heads, all_head_outputs, config.models_dir, config)
    tags_accum.update(mood_tags)

    # DEBUG: Log mood aggregation results
    mood_keys = [k for k in tags_accum if isinstance(k, str) and k.startswith("mood-")]
    logging.info(f"[processor] Mood aggregation produced {len(mood_keys)} mood- tags: {mood_keys}")
    for mood_key in mood_keys:
        val = tags_accum[mood_key]
        if isinstance(val, list):
            logging.debug(f"[processor]   {mood_key}: {len(val)} terms")

    # Add version tag
    tags_accum[config.version_tag_key] = config.tagger_version

    # === STEP 4: Prepare tags for database and file writing ===
    db_tags, file_tags = _prepare_file_and_db_tags(tags_accum, config)

    # === STEP 5: Write tags to file ===
    _write_tags_to_file(writer, path, file_tags)

    # === STEP 6: Sync database with full tags ===
    calibration_map = getattr(tags_accum, "_calibration_map", None)
    _sync_database(
        db,
        path,
        writer,
        db_tags,
        file_tags,
        config.namespace,
        config.tagger_version,
        config.file_write_mode,
        calibration_map,
    )

    elapsed = round(time.time() - start_all, 2)

    # Collect mood aggregation info if written
    mood_info = {}
    for key in ["mood-strict", "mood-regular", "mood-loose"]:
        if key in tags_accum:
            val = tags_accum[key]
            if isinstance(val, dict | list):
                mood_info[key] = len(val)

    return ProcessFileResult(
        file=path,
        elapsed=elapsed,
        duration=duration_final,
        heads_processed=total_heads_succeeded,
        tags_written=len(tags_accum),
        head_results=all_head_results,
        mood_aggregations=mood_info if mood_info else None,
        tags=dict(tags_accum),  # Include actual tags for CLI display
    )
