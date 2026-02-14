"""High-level audio file processing workflow.

This is a PURE WORKFLOW module that orchestrates the ML audio tagging pipeline:
- Model discovery and backbone grouping
- Embedding computation per backbone
- Head prediction execution
- Score pooling and decision logic
- Mood tier aggregation (including regression-based tiers)
- Calibration loading and application
- Database storage of predictions

NOTE: This workflow does NOT write tags to audio files. File tag writing
is decoupled and handled by write_file_tags_wf based on per-library settings.
This separation ensures ML inference is not affected by file I/O failures.

ARCHITECTURE:
- This workflow is domain logic that coordinates ML and persistence layers.
- It does NOT import or use the DI container, services, or application object.
- Callers (typically discovery workers) must provide all dependencies:
  - File path
  - ProcessorConfig with all processing parameters
  - Optional Database instance for persistence updates

EXPECTED DEPENDENCIES:
- `config: ProcessorConfig` - Typed configuration with:
  - models_dir: str
  - min_duration_s, allow_short: float, bool
  - batch_size: int
  - namespace: str
  - version_tag_key, tagger_version: str
  - calibrate_heads: bool

- `db: Database | None` - Optional database instance for library updates
  - If provided, must support: db.library_files.*, db.tags.*
  - Used to update library_files and tags after successful tagging

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
from collections import defaultdict
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.ml import ml_backend_essentia_comp as backend_essentia
from nomarr.components.ml.ml_audio_comp import AudioLoadCrashError, AudioLoadShutdownError
from nomarr.components.ml.ml_discovery_comp import HeadInfo, discover_heads
from nomarr.components.ml.ml_embed_comp import pool_scores
from nomarr.components.ml.ml_heads_comp import run_head_decision
from nomarr.components.ml.ml_inference_comp import compute_embeddings_for_backbone, make_head_only_predictor_batched
from nomarr.components.tagging.tagging_aggregation_comp import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    normalize_tag_label,
)
from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams
from nomarr.helpers.dto.processing_dto import ProcessFileResult, ProcessorConfig
from nomarr.helpers.dto.tags_dto import Tags
from nomarr.helpers.time_helper import internal_s

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database


def _get_essentia_version() -> str:
    """Get Essentia version lazily (only when needed)."""
    return backend_essentia.get_version()


@dataclass
class ProcessHeadPredictionsResult:
    """Result from _process_head_predictions() private helper (workflow-internal)."""

    heads_succeeded: int
    head_results: dict[str, Any]
    regression_heads: list[tuple[Any, list[float]]]
    all_head_outputs: list[Any]


def _discover_and_group_heads(models_dir: str) -> tuple[list[HeadInfo], dict[str, list[HeadInfo]]]:
    """Discover head models and group them by backbone for embedding reuse.

    Args:
        models_dir: Directory containing model files

    Returns:
        Tuple of (all_heads, heads_by_backbone_dict)

    Raises:
        RuntimeError: If no heads found in models_dir

    """
    heads = discover_heads(models_dir)
    if not heads:
        msg = f"No head models found under {models_dir}"
        raise RuntimeError(msg)
    logger.debug(f"[processor] Discovered {len(heads)} heads")
    from collections import Counter

    by_backbone = Counter(h.backbone for h in heads)
    by_type = Counter(h.head_type for h in heads)
    logger.debug(f"[processor] Heads by backbone: {dict(by_backbone)}")
    logger.debug(f"[processor] Heads by type: {dict(by_type)}")
    for head in heads:
        logger.debug(
            f"[processor]   - {head.name} ({head.backbone}/{head.head_type}, {len(head.sidecar.labels)} labels)",
        )
    heads_by_backbone = defaultdict(list)
    for head in heads:
        heads_by_backbone[head.backbone].append(head)
    backbone_counts = {k: len(v) for k, v in heads_by_backbone.items()}
    logger.debug(f"[processor] Grouped {len(heads)} heads into {len(heads_by_backbone)} backbones: {backbone_counts}")
    return (heads, dict(heads_by_backbone))


def _compute_embeddings_for_backbone(
    backbone: str, first_head: HeadInfo, path: str, config: ProcessorConfig, db: Database | None,
) -> tuple[np.ndarray, float, str]:
    """Compute embeddings for a single backbone.

    Args:
        backbone: Name of the backbone model
        first_head: First head in the backbone group (for params)
        path: Path to audio file
        config: Processor configuration
        db: Database instance (for LibraryPath validation)

    Returns:
        Tuple of (embeddings_2d, duration, chromaprint)

    Raises:
        RuntimeError: If audio is too short or embedding computation fails

    """
    target_sr = first_head.sidecar.sr
    seg_len, hop_len = first_head.sidecar.segment_hop
    emb_graph = first_head.embedding_graph
    logger.debug(f"[processor] Computing embeddings for {backbone}: sr={target_sr}")
    from nomarr.components.infrastructure.path_comp import build_library_path_from_input

    library_path = build_library_path_from_input(path, db) if db else None
    if not library_path or not library_path.is_valid():
        msg = f"Cannot compute embeddings for invalid path: {path}"
        raise ValueError(msg)
    t_emb = internal_s()
    params = ComputeEmbeddingsForBackboneParams(
        backbone=backbone,
        emb_graph=emb_graph,
        target_sr=target_sr,
        segment_s=seg_len,
        hop_s=hop_len,
        path=library_path,
        min_duration_s=config.min_duration_s,
        allow_short=config.allow_short,
    )
    embeddings_2d, duration, chromaprint = compute_embeddings_for_backbone(params=params)
    logger.debug(
        f"[processor] Embeddings for {backbone} computed in {internal_s().value - t_emb.value:.1f}s: shape={embeddings_2d.shape}",
    )
    return (embeddings_2d, duration, chromaprint)


def _process_head_predictions(
    backbone_heads: list[HeadInfo], embeddings_2d: np.ndarray, config: ProcessorConfig, tags_accum: dict[str, Any],
) -> ProcessHeadPredictionsResult:
    """Process all head predictions for a single backbone using cached embeddings.

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
    for head_info in backbone_heads:
        head_name = head_info.name
        try:
            t_head = internal_s()
            head_predict_fn = make_head_only_predictor_batched(head_info, embeddings_2d, batch_size=config.batch_size)
            segment_scores = head_predict_fn()
            pooled_vec = pool_scores(segment_scores, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")
        except Exception as e:
            logger.error(f"[processor] Processing error for {head_name}: {e}", exc_info=True)
            head_results[head_name] = {"status": "error", "error": str(e), "stage": "processing"}
            continue
        try:
            decision = run_head_decision(head_info.sidecar, pooled_vec, prefix="")

            def _build_key(label: str, head: HeadInfo = head_info) -> str:
                model_key, _ = head.build_versioned_tag_key(
                    normalize_tag_label(label),
                    framework_version=_get_essentia_version(),
                    calib_method="none",
                    calib_version=0,
                )
                return model_key

            head_outputs = decision.to_head_outputs(
                head_info=head_info, framework_version=_get_essentia_version(), key_builder=_build_key,
            )
            all_head_outputs.extend(head_outputs)
            head_tags = decision.as_tags(key_builder=_build_key)
            logger.debug(f"[processor] Head {head_name} ({head_info.head_type}) produced {len(head_tags)} tags")
            if head_tags:
                sample_keys = list(head_tags.keys())[:3]
                logger.debug(f"[processor]   Sample keys: {sample_keys}")
            logger.debug(
                f"[processor] Head {head_name} complete: {len(segment_scores)} patches → {len(head_tags)} tags in {internal_s().value - t_head.value:.1f}s",
            )
            if len(head_tags) == 0:
                logger.warning(f"[processor] Head {head_name} produced ZERO tags")
            tags_accum.update(head_tags)
            heads_succeeded += 1
            if head_info.is_regression_head:
                if segment_scores.ndim == 2:
                    raw_values = [float(x) for x in segment_scores[:, 0]]
                else:
                    raw_values = [float(x) for x in segment_scores]
                regression_heads.append((head_info, raw_values))
                logger.debug(
                    f"[processor] Captured {len(raw_values)} segment predictions for {head_name} (mean={np.mean(raw_values):.3f}, std={np.std(raw_values):.3f})",
                )
            head_results[head_name] = {
                "status": "success",
                "tags_written": len(head_tags),
                "decisions": len(decision.details),
            }
        except Exception as e:
            logger.error(f"[processor] Aggregation error for {head_name}: {e}", exc_info=True)
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
    db: Database | None,
) -> dict[str, Any]:
    """Collect and aggregate all mood outputs from classification and regression heads.

    Args:
        regression_heads: List of (HeadInfo, segment_values) tuples for regression heads
        all_head_outputs: List of HeadOutput objects from classification heads
        models_dir: Directory containing model files (for calibrations)
        config: Processor configuration
        db: Optional Database instance for loading calibrations

    Returns:
        Dict of mood-* tags

    """
    regression_outputs = add_regression_mood_tiers(regression_heads, framework_version=_get_essentia_version())
    all_head_outputs.extend(regression_outputs)
    logger.debug(f"[processor] Total HeadOutput objects: {len(all_head_outputs)}")
    calibrations = {}
    if db is not None:
        from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_from_db_wf

        calibrations = load_calibrations_from_db_wf(db)
        if calibrations:
            logger.debug(f"[aggregation] Loaded {len(calibrations)} calibrations from database")
        else:
            logger.debug("[aggregation] No calibrations in database (initial state), using raw scores")
    return aggregate_mood_tiers(all_head_outputs, calibrations=calibrations)


def _sync_to_database(
    db: Database | None,
    path: str,
    db_tags: dict[str, Any],
    namespace: str,
    tagger_version: str,
    chromaprint: str | None = None,
    file_id: str | None = None,
) -> None:
    """Sync ML predictions to database only (NO file writes).

    File tag writing is handled separately by write_file_tags_wf based on
    library settings. This decouples ML inference from file I/O failures.

    Args:
        db: Optional Database instance
        path: Path to audio file
        db_tags: ML prediction tags to write to database
        namespace: Tag namespace
        tagger_version: Tagger version string
        chromaprint: Audio fingerprint hash for move detection
        file_id: Document _id from library_files (avoids path-based re-lookup)

    """
    if db is None:
        return
    try:
        from nomarr.components.infrastructure.path_comp import build_library_path_from_input
        from nomarr.components.library.metadata_extraction_comp import extract_metadata
        from nomarr.workflows.library.sync_file_to_library_wf import sync_file_to_library

        library_path = build_library_path_from_input(path, db)
        metadata = extract_metadata(library_path, namespace=namespace)
        if chromaprint:
            metadata["chromaprint"] = chromaprint

        # Merge ML prediction tags into nom_tags so sync_file_to_library writes them to DB
        nom_tags = metadata.get("nom_tags", {})
        nom_tags.update(db_tags)
        metadata["nom_tags"] = nom_tags

        sync_file_to_library(
            db=db,
            file_path=path,
            metadata=metadata,
            namespace=namespace,
            tagged_version=tagger_version,
            library_id=None,
            file_id=file_id,
        )
        logger.debug(f"[processor] Updated library database for {path} with {len(db_tags)} tags")
    except Exception as e:
        logger.exception(f"[processor] Failed to update library database for {path}: {e}")


def select_tags_for_file(all_tags: dict[str, Any], file_write_mode: str) -> dict[str, Any]:
    """Filter tags for file writing based on file_write_mode.

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
        filtered = {}
        for key, tag_value in all_tags.items():
            if not isinstance(key, str):
                continue
            if key.startswith("mood-") or key.endswith("_version") or "version" in key:
                filtered[key] = tag_value
        return filtered
    filtered = {}
    for key, tag_value in all_tags.items():
        if not isinstance(key, str):
            continue
        if key.endswith("_tier"):
            continue
        if "calibration" in key.lower():
            continue
        filtered[key] = tag_value
    return filtered


def process_file_workflow(path: str, config: ProcessorConfig, db: Database | None = None, file_id: str | None = None) -> ProcessFileResult:
    """Process an audio file through the complete tagging pipeline.

    This is the main workflow entrypoint for audio file processing. It is a pure
    function that orchestrates the entire tagging pipeline without any hidden
    dependencies or side effects beyond file I/O and optional database updates.

    WORKFLOW STEPS:
    0. Validate path against library configuration (if db provided)
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
    - Validate path against library config (when db provided)
    - Discover and group models by backbone
    - Compute embeddings for each backbone
    - Run head predictions on embeddings
    - Pool segment predictions to file-level scores
    - Aggregate mood tiers with calibrations
    - Write tags to audio file via TagWriter
    - Optionally update library database via db parameter

    RESPONSIBILITIES (what this function DOES NOT do):
    - Skip/force logic (caller decides whether to call this)
    - Cache management internals (handled by cache module)
    - Config loading or DI (caller injects typed config)
    - Error recovery strategies (caller handles retries)

    Args:
        path: Path to audio file (string from queue, will be validated if db provided)
        config: Typed configuration for processing pipeline (ProcessorConfig)
                Must include: models_dir, namespace, batch_size, tagger_version,
                min_duration_s, allow_short, overwrite_tags, version_tag_key,
                calibrate_heads
        db: Optional Database instance for updating library_files and tags
            after successful processing. If None, library updates are skipped.
        file_id: Document _id from library_files. When provided, avoids
            path-based upsert/lookup during DB sync (prevents duplicates).

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
    from nomarr.components.infrastructure.path_comp import build_library_path_from_db
    from nomarr.components.ml.ml_cache_comp import check_and_evict_idle_cache, touch_cache

    library_path: LibraryPath | None = None
    if db is not None:
        library_path = build_library_path_from_db(stored_path=path, db=db, library_id=None, check_disk=True)
        if not library_path.is_valid():
            error_msg = f"Path validation failed ({library_path.status}): {library_path.reason}"
            logger.error(f"[process_file_workflow] {error_msg} - {path}")
            raise ValueError(error_msg)
        path = str(library_path.absolute)
        logger.debug(f"[process_file_workflow] Path validated for library_id={library_path.library_id}: {path}")
    check_and_evict_idle_cache()
    touch_cache()
    start_all = internal_s()
    _, heads_by_backbone = _discover_and_group_heads(config.models_dir)

    class TagAccumulator(dict):
        pass

    tags_accum = TagAccumulator()
    all_head_results: dict[str, Any] = {}
    chromaprint_from_ml: str | None = None
    duration_final: float | None = None
    all_head_outputs: list[Any] = []
    heads_succeeded = 0
    regression_heads: list[tuple[HeadInfo, list[float]]] = []
    total_heads_succeeded = 0
    for backbone, backbone_heads in heads_by_backbone.items():
        first_head = backbone_heads[0]
        try:
            embeddings_2d, duration, chromaprint_hash = _compute_embeddings_for_backbone(
                backbone, first_head, path, config, db,
            )
            if duration_final is None:
                duration_final = float(duration)
            if chromaprint_from_ml is None:
                chromaprint_from_ml = chromaprint_hash
        except AudioLoadShutdownError:
            # Worker shutting down - let it propagate, don't mark file invalid
            raise
        except RuntimeError as e:
            logger.warning(f"[processor] Skipping backbone {backbone}: {e}")
            for head in backbone_heads:
                all_head_results[head.name] = {"status": "skipped", "reason": str(e)}
            continue
        except AudioLoadCrashError as e:
            # File is corrupt (crashed twice during audio loading) - mark invalid and abort
            logger.error(f"[processor] Audio load crashed twice for {path}: {e}")
            if db:
                db.library_files.mark_file_invalid(path)
                logger.info(f"[processor] Marked file as invalid: {path}")
            elapsed = round(internal_s().value - start_all.value, 2)
            return ProcessFileResult(
                file_path=path,
                elapsed=elapsed,
                duration=None,
                heads_processed=0,
                tags_written=0,
                head_results={"_crash": {"status": "crash", "reason": str(e)}},
                mood_aggregations=None,
                tags=Tags.from_dict({}),
            )
        result = _process_head_predictions(backbone_heads, embeddings_2d, config, tags_accum)
        heads_succeeded = result.heads_succeeded
        head_results = result.head_results
        regression_outputs = result.regression_heads
        head_outputs = result.all_head_outputs
        total_heads_succeeded += heads_succeeded
        all_head_results.update(head_results)
        regression_heads.extend(regression_outputs)
        all_head_outputs.extend(head_outputs)
        del embeddings_2d
        gc.collect()
        logger.debug(f"[processor] Released {backbone} embeddings and predictors from memory")
    if total_heads_succeeded == 0:
        # Check if all heads were skipped (vs failed)
        all_skipped = all(
            result.get("status") == "skipped"
            for result in all_head_results.values()
        )
        if all_skipped:
            # All heads skipped due to short audio or other valid reasons
            # Return early with skipped result instead of raising error
            elapsed = round(internal_s().value - start_all.value, 2)
            logger.info(
                f"[processor] All heads skipped for {path} (e.g., audio too short) - returning empty result"
            )
            return ProcessFileResult(
                file_path=path,
                elapsed=elapsed,
                duration=duration_final,
                heads_processed=0,
                tags_written=0,
                head_results=all_head_results,
                mood_aggregations=None,
                tags=Tags.from_dict({}),
            )
        # Some heads failed (not skipped) - this is an error
        msg = "No heads produced decisions; refusing to write tags"
        raise RuntimeError(msg)
    mood_tags = _collect_mood_outputs(regression_heads, all_head_outputs, config.models_dir, config, db)
    tags_accum.update(mood_tags)
    mood_keys = [k for k in tags_accum if isinstance(k, str) and k.startswith("mood-")]
    logger.debug(f"[processor] Mood aggregation produced {len(mood_keys)} mood- tags: {mood_keys}")
    for mood_key in mood_keys:
        mood_value = tags_accum[mood_key]
        if isinstance(mood_value, list):
            logger.debug(f"[processor]   {mood_key}: {len(mood_value)} terms")
    tags_accum[config.version_tag_key] = config.tagger_version
    db_tags = dict(tags_accum)
    _sync_to_database(db, path, db_tags, config.namespace, config.tagger_version, chromaprint_from_ml, file_id=file_id)
    elapsed = round(internal_s().value - start_all.value, 2)
    mood_info = {}
    for key in ["mood-strict", "mood-regular", "mood-loose"]:
        if key in tags_accum:
            mood_value = tags_accum[key]
            if isinstance(mood_value, dict | list):
                mood_info[key] = len(mood_value)
    return ProcessFileResult(
        file_path=path,
        elapsed=elapsed,
        duration=duration_final,
        heads_processed=total_heads_succeeded,
        tags_written=len(tags_accum),
        head_results=all_head_results,
        mood_aggregations=mood_info if mood_info else None,
        tags=Tags.from_dict(dict(tags_accum)),
    )
