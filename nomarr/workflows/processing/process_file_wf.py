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

import logging
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from functools import partial
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
from nomarr.helpers.dto.ml_dto import ComputeEmbeddingsForBackboneParams, LoadAudioMonoResult
from nomarr.helpers.dto.processing_dto import DeferredFileWrites, ProcessFileResult, ProcessorConfig
from nomarr.helpers.dto.tags_dto import Tags
from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database


_ESSENTIA_VERSION: str | None = None


def _get_essentia_version() -> str:
    """Get Essentia version — computed once per process, cached thereafter."""
    global _ESSENTIA_VERSION
    if _ESSENTIA_VERSION is None:
        _ESSENTIA_VERSION = backend_essentia.get_version()
    return _ESSENTIA_VERSION


# Reusable thread pool for parallel head predictions.
# Capped at 12 workers (max heads per backbone group). Lives for the process
# lifetime — avoids repeated pool creation/teardown overhead per file.
_HEAD_POOL = ThreadPoolExecutor(max_workers=12, thread_name_prefix="head")


@dataclass
class ProcessHeadPredictionsResult:
    """Result from _process_head_predictions() private helper (workflow-internal)."""

    heads_succeeded: int
    head_results: dict[str, Any]
    regression_heads: list[tuple[Any, list[float]]]
    all_head_outputs: list[Any]
    raw_segments_per_head: dict[str, tuple[np.ndarray, list[str]]]  # head -> (scores, labels)
    per_head_timings: dict[str, float]  # head_name -> duration_ms  # head_name -> duration_ms


@dataclass
class _SingleHeadResult:
    """Result from processing a single head (thread-safe, no shared mutation)."""

    head_name: str
    status: str  # "success", "error_processing", "error_aggregation"
    error: str | None = None
    head_tags: dict[str, Any] | None = None
    head_outputs: list[Any] | None = None
    regression_data: tuple[Any, list[float]] | None = None
    raw_segment_scores: np.ndarray | None = None  # deferred to async write thread
    segment_labels: list[str] | None = None  # labels for segment stats computation
    elapsed_ms: float = 0.0
    decisions_count: int = 0


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
    backbone: str, first_head: HeadInfo, library_path: LibraryPath, config: ProcessorConfig,
    pre_loaded_audio: LoadAudioMonoResult | None = None,
    pre_computed_chromaprint: str | None = None,
) -> tuple[np.ndarray, float, str]:
    """Compute embeddings for a single backbone.

    Args:
        backbone: Name of the backbone model
        first_head: First head in the backbone group (for params)
        library_path: Validated LibraryPath object (from workflow start)
        config: Processor configuration
        pre_loaded_audio: Pre-loaded audio waveform (avoids redundant audio loading)
        pre_computed_chromaprint: Pre-computed chromaprint hash

    Returns:
        Tuple of (embeddings_2d, duration, chromaprint)

    Raises:
        RuntimeError: If audio is too short or embedding computation fails

    """
    target_sr = first_head.sidecar.sr
    seg_len, hop_len = first_head.sidecar.segment_hop
    emb_graph = first_head.embedding_graph
    logger.debug(f"[processor] Computing embeddings for {backbone}: sr={target_sr}")

    t_emb = internal_ms()
    params = ComputeEmbeddingsForBackboneParams(
        backbone=backbone,
        emb_graph=emb_graph,
        target_sr=target_sr,
        segment_s=seg_len,
        hop_s=hop_len,
        path=library_path,
        min_duration_s=config.min_duration_s,
        allow_short=config.allow_short,
        pre_loaded_audio=pre_loaded_audio,
        pre_computed_chromaprint=pre_computed_chromaprint,
    )
    embeddings_2d, duration, chromaprint = compute_embeddings_for_backbone(params=params)
    logger.debug(
        f"[processor] Embeddings for {backbone} computed in {(internal_ms().value - t_emb.value)/1000:.1f}s: shape={embeddings_2d.shape}",
    )
    return (embeddings_2d, duration, chromaprint)



def _build_tag_key(label: str, *, head_info: HeadInfo, essentia_version: str) -> str:
    """Build a versioned tag key for a label — module-level to avoid per-head closure creation."""
    model_key, _ = head_info.build_versioned_tag_key(
        normalize_tag_label(label),
        framework_version=essentia_version,
        calib_method="none",
        calib_version=0,
    )
    return model_key
def _run_single_head(
    head_info: HeadInfo,
    predict_fn: Callable[[], np.ndarray],
    essentia_version: str,
) -> _SingleHeadResult:
    """Process a single head prediction — fully independent, no shared state mutation.

    Thread-safe: all inputs are read-only, all outputs returned via _SingleHeadResult.
    TF inference releases the GIL so multiple heads get real parallelism.

    Args:
        head_info: Head metadata.
        predict_fn: Pre-resolved cached predictor closure (from make_head_only_predictor_batched).
            Hoisting resolution to the caller avoids per-thread cache lookup + lock contention.
        essentia_version: Pre-cached essentia version string (avoids per-label calls).

    """
    head_name = head_info.name
    t_head = internal_ms()
    # Phase 1: TF inference (GPU/CPU, releases GIL)
    try:
        segment_scores = predict_fn()
        pooled_vec = pool_scores(segment_scores, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")
        seg_std: np.ndarray | None = None
        if segment_scores.ndim == 2 and segment_scores.shape[0] > 1:
            seg_std = np.std(segment_scores, axis=0).astype(np.float32, copy=False)
    except Exception as e:
        logger.error(f"[processor] Processing error for {head_name}: {e}", exc_info=True)
        return _SingleHeadResult(
            head_name=head_name, status="error_processing",
            error=str(e), elapsed_ms=internal_ms().value - t_head.value,
        )
    # Phase 2: Decision + tag generation (pure Python/numpy)
    try:
        decision = run_head_decision(head_info.sidecar, pooled_vec, prefix="", segment_std=seg_std)

        key_builder = partial(_build_tag_key, head_info=head_info, essentia_version=essentia_version)

        head_outputs = decision.to_head_outputs(
            head_info=head_info, framework_version=essentia_version, key_builder=key_builder,
        )
        head_tags = decision.as_tags(key_builder=key_builder)
        logger.debug(f"[processor] Head {head_name} ({head_info.head_type}) produced {len(head_tags)} tags")
        if head_tags:
            sample_keys = list(head_tags.keys())[:3]
            logger.debug(f"[processor]   Sample keys: {sample_keys}")
        elapsed_ms = internal_ms().value - t_head.value
        logger.debug(
            f"[processor] Head {head_name} complete: {len(segment_scores)} patches → {len(head_tags)} tags in {elapsed_ms/1000:.1f}s",
        )
        if len(head_tags) == 0:
            logger.warning(f"[processor] Head {head_name} produced ZERO tags")
        # Regression data
        regression_data: tuple[Any, list[float]] | None = None
        if head_info.is_regression_head:
            if segment_scores.ndim == 2:
                raw_values = [float(x) for x in segment_scores[:, 0]]
            else:
                raw_values = [float(x) for x in segment_scores]
            regression_data = (head_info, raw_values)
            logger.debug(
                f"[processor] Captured {len(raw_values)} segment predictions for {head_name} (mean={np.mean(raw_values):.3f}, std={np.std(raw_values):.3f})",
            )
        # Defer segment stats computation to async DB write thread.
        # Keep raw scores alive (numpy ref, no copy needed — it's from vstack).
        raw_segment_scores: np.ndarray | None = None
        segment_labels: list[str] | None = None
        if segment_scores.ndim == 2 and len(head_info.labels) > 0:
            raw_segment_scores = segment_scores
            segment_labels = head_info.labels
        return _SingleHeadResult(
            head_name=head_name, status="success",
            head_tags=head_tags, head_outputs=head_outputs,
            regression_data=regression_data,
            raw_segment_scores=raw_segment_scores, segment_labels=segment_labels,
            elapsed_ms=elapsed_ms, decisions_count=len(decision.details),
        )
    except Exception as e:
        logger.error(f"[processor] Aggregation error for {head_name}: {e}", exc_info=True)
        return _SingleHeadResult(
            head_name=head_name, status="error_aggregation",
            error=str(e), elapsed_ms=internal_ms().value - t_head.value,
        )


def _process_head_predictions(
    backbone_heads: list[HeadInfo], embeddings_2d: np.ndarray, config: ProcessorConfig, tags_accum: dict[str, Any],
) -> ProcessHeadPredictionsResult:
    """Process all head predictions for a single backbone using cached embeddings.

    Runs heads in parallel via a reusable module-level ThreadPoolExecutor (_HEAD_POOL).
    Predictor resolution is hoisted to the main thread to avoid per-thread cache
    lookup + lock contention. The dispatched threads only call predict_fn() which
    releases the GIL for real CPU parallelism.

    Args:
        backbone_heads: List of heads for this backbone
        embeddings_2d: Pre-computed embeddings
        config: Processor configuration
        tags_accum: Accumulator dict for tags (modified in place)

    Returns:
        ProcessHeadPredictionsResult with per-head outcomes

    """
    # Pre-resolve cached predictors on the main thread (no lock contention).
    # Each predict_fn is a lightweight closure binding the cached TF model + embeddings.
    predict_fns: dict[str, Callable[[], np.ndarray]] = {}
    for hi in backbone_heads:
        predict_fns[hi.name] = make_head_only_predictor_batched(hi, embeddings_2d, batch_size=config.batch_size)

    essentia_version = _get_essentia_version()
    head_results_list: list[_SingleHeadResult] = []
    n_heads = len(backbone_heads)
    if n_heads > 1:
        futures = {
            _HEAD_POOL.submit(_run_single_head, hi, predict_fns[hi.name], essentia_version): hi.name
            for hi in backbone_heads
        }
        head_results_list.extend(fut.result() for fut in as_completed(futures))
        logger.debug("[processor] Parallel heads complete (%d heads)", n_heads)
    else:
        head_results_list.extend(
            _run_single_head(hi, predict_fns[hi.name], essentia_version) for hi in backbone_heads
        )

    # Merge results sequentially (safe dict mutations)
    heads_succeeded = 0
    head_results: dict[str, Any] = {}
    regression_heads: list[tuple[Any, list[float]]] = []
    all_head_outputs: list[Any] = []
    raw_segments_per_head: dict[str, tuple[np.ndarray, list[str]]] = {}
    per_head_timings: dict[str, float] = {}
    for r in head_results_list:
        per_head_timings[r.head_name] = r.elapsed_ms
        if r.status == "success":
            heads_succeeded += 1
            if r.head_tags:
                tags_accum.update(r.head_tags)
            if r.head_outputs:
                all_head_outputs.extend(r.head_outputs)
            if r.regression_data:
                regression_heads.append(r.regression_data)
            if r.raw_segment_scores is not None and r.segment_labels is not None:
                raw_segments_per_head[r.head_name] = (r.raw_segment_scores, r.segment_labels)
            head_results[r.head_name] = {
                "status": "success",
                "tags_written": len(r.head_tags or {}),
                "decisions": r.decisions_count,
            }
        elif r.status == "error_processing":
            head_results[r.head_name] = {"status": "error", "error": r.error, "stage": "processing"}
        else:
            head_results[r.head_name] = {"status": "error", "error": r.error, "stage": "aggregation"}
    return ProcessHeadPredictionsResult(
        heads_succeeded=heads_succeeded,
        head_results=head_results,
        regression_heads=regression_heads,
        all_head_outputs=all_head_outputs,
        raw_segments_per_head=raw_segments_per_head,
        per_head_timings=per_head_timings,
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
        from nomarr.workflows.calibration.calibration_loader_wf import load_calibrations_cached_wf

        calibrations = load_calibrations_cached_wf(db)
        if calibrations:
            logger.debug(f"[aggregation] Loaded {len(calibrations)} calibrations from database")
        else:
            logger.debug("[aggregation] No calibrations in database (initial state), using raw scores")
    return aggregate_mood_tiers(all_head_outputs, calibrations=calibrations)




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

    library_path: LibraryPath | None = None
    if db is not None:
        library_path = build_library_path_from_db(stored_path=path, db=db, library_id=None, check_disk=True)
        if not library_path.is_valid():
            error_msg = f"Path validation failed ({library_path.status}): {library_path.reason}"
            logger.error(f"[process_file_workflow] {error_msg} - {path}")
            raise ValueError(error_msg)
        path = str(library_path.absolute)
        logger.debug(f"[process_file_workflow] Path validated for library_id={library_path.library_id}: {path}")
    start_all = internal_ms()
    # Ultra-verbose timing tracker for bottleneck analysis
    timings: dict[str, float] = {}  # operation_name -> duration_ms
    t_discover = internal_ms()
    _, heads_by_backbone = _discover_and_group_heads(config.models_dir)
    timings["model_discovery"] = internal_ms().value - t_discover.value

    class TagAccumulator(dict):
        pass

    tags_accum = TagAccumulator()
    all_head_results: dict[str, Any] = {}
    all_head_outputs: list[Any] = []
    heads_succeeded = 0
    regression_heads: list[tuple[HeadInfo, list[float]]] = []
    total_heads_succeeded = 0
    all_raw_segments: dict[str, tuple[np.ndarray, list[str]]] = {}
    # Compute model suite hash once for vector persistence (not per backbone)
    from nomarr.components.ml.ml_discovery_comp import compute_model_suite_hash

    model_suite_hash = compute_model_suite_hash(config.models_dir)
    if library_path is None:
        raise ValueError("Cannot process file without database connection (library_path is None)")

    # Load audio ONCE before the backbone loop (both backbones use same sample rate)
    # This eliminates redundant fork-isolated loads + chromaprint computations
    from nomarr.components.ml.chromaprint_comp import compute_chromaprint
    from nomarr.components.ml.ml_audio_comp import load_audio_mono, should_skip_short

    t_audio_load = internal_ms()
    first_backbone_heads = next(iter(heads_by_backbone.values()))
    target_sr = first_backbone_heads[0].sidecar.sr
    try:
        shared_audio = load_audio_mono(library_path, target_sr=target_sr)
    except AudioLoadShutdownError:
        raise
    except AudioLoadCrashError as e:
        logger.error(f"[processor] Audio load crashed twice for {path}: {e}")
        if db:
            db.library_files.mark_file_invalid(path)
            logger.info(f"[processor] Marked file as invalid: {path}")
        elapsed = round((internal_ms().value - start_all.value) / 1000, 2)
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
    if should_skip_short(shared_audio.duration, config.min_duration_s, config.allow_short):
        elapsed = round((internal_ms().value - start_all.value) / 1000, 2)
        logger.info(
            f"[processor] Audio too short ({shared_audio.duration:.1f}s < {config.min_duration_s}s) - skipping {path}"
        )
        return ProcessFileResult(
            file_path=path,
            elapsed=elapsed,
            duration=shared_audio.duration,
            heads_processed=0,
            tags_written=0,
            head_results={"_short": {"status": "skipped", "reason": f"audio too short ({shared_audio.duration:.1f}s)"}},
            mood_aggregations=None,
            tags=Tags.from_dict({}),
        )
    shared_chromaprint = compute_chromaprint(shared_audio.waveform, shared_audio.sample_rate)
    timings["audio_load"] = internal_ms().value - t_audio_load.value
    duration_final = float(shared_audio.duration)
    chromaprint_from_ml = shared_chromaprint
    # -- Backbone embedding computation: parallel when 2+ backbones --
    # Both models are already resident in VRAM (cached predictors).
    # TF C++ kernels release the GIL, so ThreadPoolExecutor gets real parallelism.
    # Audio array is read-only numpy — safe to share across threads with no copy.
    backbone_items = list(heads_by_backbone.items())
    use_parallel = len(backbone_items) >= 2

    def _embed_one(backbone: str, backbone_heads: list[HeadInfo]) -> tuple[str, list[HeadInfo], np.ndarray, float, str, float]:
        """Compute embeddings for one backbone, returning timing info."""
        first_head = backbone_heads[0]
        t0 = internal_ms()
        embeddings_2d, duration, chromaprint_hash = _compute_embeddings_for_backbone(
            backbone, first_head, library_path, config,
            pre_loaded_audio=shared_audio,
            pre_computed_chromaprint=shared_chromaprint,
        )
        elapsed_ms = internal_ms().value - t0.value
        return (backbone, backbone_heads, embeddings_2d, duration, chromaprint_hash, elapsed_ms)

    # Collect (backbone, heads, embeddings, ...) — either parallel or sequential
    embedding_results: list[tuple[str, list[HeadInfo], np.ndarray, float, str, float]] = []
    embedding_errors: dict[str, str] = {}
    if use_parallel:
        t_parallel_start = internal_ms()
        logger.debug(f"[processor] Computing embeddings for {len(backbone_items)} backbones in parallel (ThreadPoolExecutor)")
        with ThreadPoolExecutor(max_workers=len(backbone_items), thread_name_prefix="backbone") as pool:
            future_to_backbone = {
                pool.submit(_embed_one, bb, heads): bb
                for bb, heads in backbone_items
            }
            for future in as_completed(future_to_backbone):
                bb = future_to_backbone[future]
                try:
                    embedding_results.append(future.result())
                except RuntimeError as e:
                    logger.warning(f"[processor] Skipping backbone {bb}: {e}")
                    embedding_errors[bb] = str(e)
        parallel_wall_ms = internal_ms().value - t_parallel_start.value
        sequential_sum_ms = sum(r[5] for r in embedding_results)
        logger.debug(
            f"[processor] Parallel embeddings done: wall={parallel_wall_ms:.0f}ms, "
            f"sum_of_parts={sequential_sum_ms:.0f}ms, "
            f"speedup={sequential_sum_ms / max(parallel_wall_ms, 1):.2f}x"
        )
        timings["emb_wall"] = parallel_wall_ms
        for r in embedding_results:
            timings[f"emb_{r[0]}"] = r[5]
    else:
        # Single backbone — no thread overhead
        for backbone, backbone_heads in backbone_items:
            try:
                result_tuple = _embed_one(backbone, backbone_heads)
                embedding_results.append(result_tuple)
                timings[f"emb_{backbone}"] = result_tuple[5]
            except RuntimeError as e:
                logger.warning(f"[processor] Skipping backbone {backbone}: {e}")
                embedding_errors[backbone] = str(e)

    # Mark skipped heads from failed backbones
    for bb, err_msg in embedding_errors.items():
        for head in heads_by_backbone[bb]:
            all_head_results[head.name] = {"status": "skipped", "reason": err_msg}

    # Process head predictions sequentially (cheap, mutates shared state)
    for backbone, backbone_heads, embeddings_2d, _duration, _chromaprint_hash, _emb_ms in embedding_results:
        t_heads_start = internal_ms()
        result = _process_head_predictions(backbone_heads, embeddings_2d, config, tags_accum)
        timings[f"heads_{backbone}"] = internal_ms().value - t_heads_start.value
        # Store per-head timings
        for head_name, head_time_ms in result.per_head_timings.items():
            timings[f"head_{head_name}"] = head_time_ms
        heads_succeeded = result.heads_succeeded
        head_results = result.head_results
        regression_outputs = result.regression_heads
        head_outputs = result.all_head_outputs
        total_heads_succeeded += heads_succeeded
        all_head_results.update(head_results)
        regression_heads.extend(regression_outputs)
        all_head_outputs.extend(head_outputs)
        all_raw_segments.update(result.raw_segments_per_head)
        # Persist pooled track-level embedding vector for this backbone
        if db is not None and file_id is not None:
            t_vector_store = internal_ms()
            try:
                from nomarr.components.ml.ml_vector_pool_comp import (
                    get_embedding_dimension,
                    pool_embedding_for_storage,
                )

                vector = pool_embedding_for_storage(embeddings_2d)
                embed_dim = get_embedding_dimension(embeddings_2d)
                ops = db.register_vectors_track_backbone(backbone)
                ops.upsert_vector(
                    file_id=file_id,
                    model_suite_hash=model_suite_hash,
                    embed_dim=embed_dim,
                    vector=vector,
                    num_segments=embeddings_2d.shape[0],
                )
                timings[f"vector_store_{backbone}"] = internal_ms().value - t_vector_store.value
                logger.debug(
                    f"[processor] Persisted {backbone} vector: dim={embed_dim}, segments={embeddings_2d.shape[0]}",
                )
            except Exception:
                logger.warning(f"[processor] Failed to persist {backbone} vector for {path}", exc_info=True)
        del embeddings_2d
        logger.debug(f"[processor] Released {backbone} embeddings from memory")
    if total_heads_succeeded == 0:
        # Check if all heads were skipped (vs failed)
        all_skipped = all(
            result.get("status") == "skipped"
            for result in all_head_results.values()
        )
        if all_skipped:
            # All heads skipped due to short audio or other valid reasons
            # Return early with skipped result instead of raising error
            elapsed = round((internal_ms().value - start_all.value) / 1000, 2)
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
    t_mood = internal_ms()
    mood_tags = _collect_mood_outputs(regression_heads, all_head_outputs, config.models_dir, config, db)
    timings["mood_aggregation"] = internal_ms().value - t_mood.value
    tags_accum.update(mood_tags)
    mood_keys = [k for k in tags_accum if isinstance(k, str) and k.startswith("mood-")]
    logger.debug(f"[processor] Mood aggregation produced {len(mood_keys)} mood- tags: {mood_keys}")
    for mood_key in mood_keys:
        mood_value = tags_accum[mood_key]
        if isinstance(mood_value, list):
            logger.debug(f"[processor]   {mood_key}: {len(mood_value)} terms")
    # Build deferred DB writes (executed async by caller, not here)
    tags_accum[config.version_tag_key] = config.tagger_version
    db_tags = dict(tags_accum)
    deferred: DeferredFileWrites | None = None
    if db is not None and file_id is not None:
        deferred = DeferredFileWrites(
            file_id=file_id,
            path=path,
            db_tags=db_tags,
            namespace=config.namespace,
            tagger_version=config.tagger_version,
            chromaprint=chromaprint_from_ml,
            raw_segments=all_raw_segments if all_raw_segments else {},
        )
    elapsed_ms = internal_ms().value - start_all.value
    elapsed = round(elapsed_ms / 1000, 2)

    # Build timing summary string (attached to result, logged by worker)
    timing_summary: str | None = None
    if db is not None:
        # Group timings by category
        audio_load_ms = timings.get("audio_load", 0)
        # Embedding: use wall time if parallel, else sum of parts
        emb_per_backbone = {k: v for k, v in timings.items() if k.startswith("emb_") and k != "emb_wall"}
        emb_wall_ms = timings.get("emb_wall", sum(emb_per_backbone.values()))
        # Head: use per-backbone wall times (heads_<backbone>), which are already wall times
        # even when individual heads within ran in parallel
        heads_wall_per_bb = {k: v for k, v in timings.items() if k.startswith("heads_")}
        heads_wall_total = sum(heads_wall_per_bb.values())
        mood_ms = timings.get("mood_aggregation", 0)

        def _pct(ms: float) -> str:
            return f"{ms / elapsed_ms * 100:.0f}%" if elapsed_ms > 0 else "0%"

        emb_detail = "+".join(f"{k.replace('emb_', '')}={v:.0f}" for k, v in emb_per_backbone.items())
        # Head detail: "<count>x<wall_ms>" per backbone
        head_parts: list[str] = []
        for bb_key, bb_wall in heads_wall_per_bb.items():
            bb_name = bb_key.replace("heads_", "")
            bb_head_count = len(heads_by_backbone.get(bb_name, []))
            head_parts.append(f"{bb_head_count}x{bb_wall:.0f}")
        head_detail = "+".join(head_parts)

        timing_summary = (
            f"audio={audio_load_ms:.0f}({_pct(audio_load_ms)}) "
            f"emb={emb_wall_ms:.0f}({_pct(emb_wall_ms)}|{emb_detail}) "
            f"heads={heads_wall_total:.0f}({_pct(heads_wall_total)}|{head_detail}) "
            f"mood={mood_ms:.0f}({_pct(mood_ms)})"
        )
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
        timing_summary=timing_summary,
        deferred_writes=deferred,
    )
