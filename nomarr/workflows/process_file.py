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
  - If provided, must support: db.library.*, db.tags.*, db.conn
  - Used to update library_files and library_tags after successful tagging

USAGE:
    from nomarr.workflows.process_file import process_file_workflow
    from nomarr.helpers.dataclasses import ProcessorConfig

    config = ProcessorConfig(
        models_dir="/app/models",
        namespace="nom",
        # ... other config values
    )

    result = process_file(
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
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.ml import backend_essentia
from nomarr.ml.inference import compute_embeddings_for_backbone, make_head_only_predictor_batched
from nomarr.ml.models.discovery import HeadInfo, discover_heads
from nomarr.ml.models.embed import pool_scores
from nomarr.ml.models.heads import run_head_decision
from nomarr.tagging.aggregation import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    load_calibrations,
    normalize_tag_label,
)
from nomarr.tagging.writer import TagWriter

# Get Essentia version for tag versioning
ESSENTIA_VERSION = backend_essentia.get_version()

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses import ProcessorConfig
    from nomarr.persistence.db import Database


def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    db: Database | None = None,
) -> dict[str, Any]:
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
        Dict with processing results:
        - file: str - path to processed file
        - elapsed: float - total processing time in seconds
        - duration: float - audio duration in seconds
        - heads_processed: int - number of heads that succeeded
        - tags_written: int - number of tags written to file
        - head_results: dict[str, dict] - per-head processing outcomes
        - mood_aggregations: dict[str, int] | None - mood tier counts if written
        - tags: dict[str, Any] - all tags that were written to file

    Raises:
        RuntimeError: If no heads found in models_dir, or all heads fail processing

    Example:
        >>> from nomarr.helpers.dataclasses import ProcessorConfig
        >>> config = ProcessorConfig(models_dir="/app/models", namespace="nom", ...)
        >>> result = process_file("/music/song.mp3", config, db=my_database)
        >>> print(f"Processed {result['file']} in {result['elapsed']}s")
    """
    from nomarr.ml.cache import check_and_evict_idle_cache, touch_cache

    # Cache management (module handles eviction policy)
    check_and_evict_idle_cache()
    touch_cache()

    # Extract config values
    models_dir = config.models_dir
    min_dur = config.min_duration_s
    allow_short = config.allow_short
    batch_size = config.batch_size
    overwrite = config.overwrite_tags
    ns = config.namespace
    version_tag_key = config.version_tag_key
    tagger_version = config.tagger_version

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

    writer = TagWriter(overwrite=overwrite, namespace=ns)
    tags_accum: dict[str, Any] = {}
    head_results: dict[str, Any] = {}  # Track per-head outcomes

    # Track regression head predictions for mood integration
    # Format: {head_name: [segment_values]}
    regression_predictions: dict[str, list[float]] = {}

    heads_succeeded = 0
    duration_final = None
    start_all = time.time()

    # Group heads by backbone for embedding reuse
    heads_by_backbone = defaultdict(list)
    for h in heads:
        heads_by_backbone[h.backbone].append(h)

    logging.info(
        f"[processor] Grouped {len(heads)} heads into {len(heads_by_backbone)} backbones: "
        f"{ {k: len(v) for k, v in heads_by_backbone.items()} }"
    )

    # Process each backbone group completely (embeddings → heads → drop) to minimize memory usage
    # This allows running more workers by not holding all backbone embeddings in memory simultaneously

    for backbone, backbone_heads in heads_by_backbone.items():
        # Use the first head to determine SR and segmentation params
        # (all heads on same backbone should use same SR/segmentation)
        first_head = backbone_heads[0]
        target_sr = first_head.sidecar.sr
        seg_len, hop_len = first_head.sidecar.segment_hop
        emb_graph = first_head.embedding_graph

        # === STEP 1: Compute embeddings for this backbone ===
        logging.info(f"[processor] Computing embeddings for {backbone}: sr={target_sr} ({len(backbone_heads)} heads)")

        try:
            t_emb = time.time()
            embeddings_2d, duration = compute_embeddings_for_backbone(
                backbone=backbone,
                emb_graph=emb_graph,
                target_sr=target_sr,
                segment_s=seg_len,
                hop_s=hop_len,
                path=path,
                min_duration_s=min_dur,
                allow_short=allow_short,
            )
            if duration_final is None:
                duration_final = float(duration)

            logging.info(
                f"[processor] Embeddings for {backbone} computed in {time.time() - t_emb:.1f}s: "
                f"shape={embeddings_2d.shape}"
            )

        except RuntimeError as e:
            logging.warning(f"[processor] Skipping backbone {backbone}: {e}")
            # Mark all heads in this backbone as skipped
            for head in backbone_heads:
                head_results[head.name] = {"status": "skipped", "reason": str(e)}
            continue

        # === STEP 2: Process all heads for this backbone using the cached embeddings ===
        for head_info in backbone_heads:
            head_name = head_info.name

            try:
                t_head = time.time()

                # Build head-only predictor (batched with explicit batch size for VRAM control)
                head_predict_fn = make_head_only_predictor_batched(head_info, embeddings_2d, batch_size=batch_size)

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

                # Initialize calibration map on tags_accum if not present
                if not hasattr(tags_accum, "_calibration_map"):
                    tags_accum._calibration_map = {}  # type: ignore

                def _build_key(
                    label: str, head: HeadInfo = head_info, calib_map: dict = tags_accum._calibration_map
                ) -> str:  # type: ignore
                    model_key, calibration_id = head.build_versioned_tag_key(
                        normalize_tag_label(label),
                        framework_version=ESSENTIA_VERSION,
                        calib_method="none",
                        calib_version=0,
                    )
                    calib_map[model_key] = calibration_id
                    return model_key

                head_tags = decision.as_tags(key_builder=_build_key)

                # DEBUG: Log tag generation details
                logging.debug(
                    f"[processor] Head {head_name} ({head_info.head_type}) produced {len(head_tags)} tags"
                )
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
                if head_info.head_type == "identity" and head_name.endswith("_regression"):
                    # segment_scores is [num_segments, 1] for regression heads, extract first column
                    if segment_scores.ndim == 2:
                        raw_values = [float(x) for x in segment_scores[:, 0]]  # Extract first column as float list
                    else:
                        raw_values = [float(x) for x in segment_scores]  # Already 1D
                    regression_predictions[head_name] = raw_values
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
                logging.error(f"[processor] Decision error for {head_name}: {e}", exc_info=True)
                head_results[head_name] = {"status": "error", "error": str(e), "stage": "decision"}
                continue

        # === STEP 3: Drop embeddings after processing all heads for this backbone ===
        # This frees memory and allows more parallel workers
        del embeddings_2d

        # Force Python garbage collection to free predictor objects
        gc.collect()

        logging.info(f"[processor] Released {backbone} embeddings and predictors from memory")

    if heads_succeeded == 0:
        raise RuntimeError("No heads produced decisions; refusing to write tags")

    # Derive mood terms from discovered heads (e.g., "mood relaxed" or "mood_relaxed" -> 'relaxed')
    mood_terms: set[str] = set()
    for h in heads:
        name = getattr(h, "name", "") or ""
        # Normalize spaces to underscores for consistent pattern matching
        name_normalized = name.replace(" ", "_")
        # Head names might look like "mood relaxed" or "mood_relaxed-audioset-yamnet-1"
        if "mood_" in name_normalized.lower():
            # Split on hyphen first to isolate the base name
            base = name_normalized.split("-", 1)[0]
            try:
                term = base.split("mood_", 1)[1]
                if term:
                    mood_terms.add(term.lower())
                    logging.debug(f"[processor] Extracted mood term '{term.lower()}' from head '{name}'")
            except Exception:
                pass

    logging.info(f"[processor] Derived mood terms from heads: {mood_terms}")

    # DEBUG: Log tags before aggregation
    logging.debug(f"[processor] Tags before mood aggregation: {len(tags_accum)} total")
    tier_tags = [k for k in tags_accum if isinstance(k, str) and k.endswith("_tier")]
    logging.debug(f"[processor]   {len(tier_tags)} tier tags found")
    if tier_tags:
        logging.debug(f"[processor]   Sample tier tags: {tier_tags[:5]}")

    # Convert regression head predictions (approachability, engagement) to mood tier tags
    add_regression_mood_tiers(tags_accum, regression_predictions)

    # DEBUG: Log tags after regression tiers
    logging.debug(f"[processor] Tags after regression tiers: {len(tags_accum)} total")

    # Load calibrations if available (conditional - gracefully handles missing files)
    # Use calibrate_heads flag from config to determine which calibration files to load
    calibrations = load_calibrations(models_dir, calibrate_heads=config.calibrate_heads)
    if calibrations:
        logging.info(f"[aggregation] Loaded calibrations for {len(calibrations)} labels")
    else:
        logging.debug("[aggregation] No calibrations found, using raw scores")

    aggregate_mood_tiers(tags_accum, mood_terms if mood_terms else None, calibrations)

    # DEBUG: Log mood aggregation results
    mood_keys = [k for k in tags_accum if isinstance(k, str) and k.startswith("mood-")]
    logging.info(f"[processor] Mood aggregation produced {len(mood_keys)} mood- tags: {mood_keys}")
    for mood_key in mood_keys:
        val = tags_accum[mood_key]
        if isinstance(val, list):
            logging.debug(f"[processor]   {mood_key}: {len(val)} terms")

    tags_accum[version_tag_key] = tagger_version
    logging.info(f"[processor] Writing {len(tags_accum)} tags to file")

    # DEBUG: Log calibration map
    if hasattr(tags_accum, "_calibration_map"):
        calib_map = tags_accum._calibration_map  # type: ignore
        logging.debug(f"[processor] Calibration map has {len(calib_map)} entries")

    writer.write(path, tags_accum)
    logging.info("[processor] Tag write complete")

    # Update library database with the newly written tags (if db provided)
    if db is not None:
        try:
            from nomarr.workflows.scan_library import update_library_file_from_tags

            # Extract calibration map if present
            calibration_map = getattr(tags_accum, "_calibration_map", None)

            # Pass tagger_version so library scanner marks file as tagged
            update_library_file_from_tags(db, path, ns, tagged_version=tagger_version, calibration=calibration_map)
            logging.info(f"[processor] Updated library database for {path}")
        except Exception as e:
            # Don't fail the entire processing if library update fails
            logging.warning(f"[processor] Failed to update library database: {e}")

    elapsed = round(time.time() - start_all, 2)

    # Collect mood aggregation info if written
    mood_info = {}
    for key in ["mood-strict", "mood-regular", "mood-loose"]:
        if key in tags_accum:
            val = tags_accum[key]
            if isinstance(val, dict | list):
                mood_info[key] = len(val)

    return {
        "file": path,
        "elapsed": elapsed,
        "duration": duration_final,
        "heads_processed": heads_succeeded,
        "tags_written": len(tags_accum),
        "head_results": head_results,
        "mood_aggregations": mood_info if mood_info else None,
        "tags": dict(tags_accum),  # Include actual tags for CLI display
    }
