"""Audio file processing workflow.

Orchestrates the full ML tagging pipeline: path validation, embedding computation,
head prediction, mood aggregation, and optional DB persistence.

NOTE: Does not write tags to audio files — that is handled by write_file_tags_wf.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import numpy as np

from nomarr.components.infrastructure.path_comp import build_library_path_from_db
from nomarr.components.library.library_file_mutation_comp import bulk_delete_files
from nomarr.components.ml.audio.ml_audio_comp import (
    AudioLoadCrashError,
    AudioLoadShutdownError,
    load_audio_mono,
    should_skip_short,
)
from nomarr.components.ml.audio.ml_chromaprint_comp import compute_chromaprint
from nomarr.components.ml.inference.ml_backbone_embed_comp import compute_backbone_embeddings
from nomarr.components.ml.inference.ml_head_pipeline_comp import run_heads
from nomarr.components.ml.onnx.ml_cache import ONNXModelCache
from nomarr.components.ml.onnx.ml_discovery_comp import compute_model_suite_hash
from nomarr.components.ml.onnx.ml_model_registry_comp import build_model_output_id_map
from nomarr.components.ml.resources.ml_timing_comp import build_timing_summary
from nomarr.components.ml.vectors.ml_vector_persist_comp import persist_backbone_vector
from nomarr.components.tagging.tagging_aggregation_comp import collect_mood_outputs
from nomarr.helpers.dto.ml_edge_dto import MLEdgeWrites
from nomarr.helpers.dto.processing_dto import DeferredFileWrites, ProcessFileResult, ProcessorConfig
from nomarr.helpers.dto.tags_dto import Tags
from nomarr.helpers.time_helper import internal_ms

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.helpers.dto.path_dto import LibraryPath
    from nomarr.persistence.db import Database


def process_file_workflow(
    path: str,
    config: ProcessorConfig,
    cache: ONNXModelCache,
    db: Database | None = None,
    file_id: str | None = None,
) -> ProcessFileResult:
    """Run the full ML tagging pipeline for one audio file.

    Validates the path, computes embeddings per backbone, runs all heads in parallel,
    aggregates mood tiers, and optionally persists results to the database.

    Args:
        path: Path to the audio file.
        config: Processing configuration (models_dir, namespace, tagger_version, etc.).
        db: Optional database instance. If provided, results are persisted.
        file_id: library_files document _id. Avoids path-based lookup when provided.
        cache: Pre-warmed ONNXModelCache. Created on demand if not provided.

    Returns:
        ProcessFileResult with elapsed time, head outcomes, mood aggregations, and tags.

    Raises:
        ValueError: If path validation fails.
        RuntimeError: If no heads are found or all heads fail.

    """
    library_path: LibraryPath | None = None
    if db is not None:
        library_path = build_library_path_from_db(stored_path=path, db=db, library_id=None, check_disk=True)
        if not library_path.is_valid():
            error_message = f"Path validation failed ({library_path.status}): {library_path.reason}"
            logger.error(f"[process_file_workflow] {error_message} - {path}")
            raise ValueError(error_message)
        path = str(library_path.absolute)
        logger.debug(f"[process_file_workflow] Path validated for library_id={library_path.library_id}: {path}")
    else:
        error_message = "Database not available!"
        logger.error(f"[process_file_workflow] {error_message}")
        raise ValueError(error_message)
    start_all = internal_ms()
    timings: dict[str, float] = {}  # operation_name -> duration_ms
    # Use the caller-provided ONNXModelCache; fall back to on-demand discovery
    # only during the transition period (no caller passes a cache yet).
    if not cache.warm:
        cache.warm = True  # Blocking: loads all ONNX sessions via setter
    heads_by_backbone = cache.heads
    if not heads_by_backbone:
        msg = f"No head models found under {config.models_dir}"
        raise RuntimeError(msg)
    timings["model_discovery"] = internal_ms().value - start_all.value

    class TagAccumulator(dict):
        pass

    tags_accum = TagAccumulator()
    all_head_results: dict[str, Any] = {}
    all_head_outputs: list[Any] = []
    regression_heads: list[tuple[Any, list[float]]] = []
    total_heads_succeeded = 0
    all_raw_segments: dict[str, tuple[np.ndarray, list[str]]] = {}
    # Compute model suite hash once for vector persistence (not per backbone)
    model_suite_hash = compute_model_suite_hash(config.models_dir)
    if library_path is None:
        raise ValueError("Cannot process file without database connection (library_path is None)")

    # Load audio ONCE before the backbone loop (both backbones use same sample rate)
    # This eliminates redundant fork-isolated loads + chromaprint computations
    t_audio_load = internal_ms()
    first_backbone = next(iter(heads_by_backbone))
    target_sr = cache.backbones[first_backbone].preprocess_params.sample_rate
    try:
        shared_audio = load_audio_mono(library_path, target_sr=target_sr)
    except AudioLoadShutdownError:
        raise
    except AudioLoadCrashError as e:
        logger.error(f"[processor] Audio load crashed for {path}: {e}")
        if db:
            bulk_delete_files(db, [path])
            logger.info(f"[processor] Deleted invalid file: {path}")
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
    embed_result = compute_backbone_embeddings(cache, heads_by_backbone, shared_audio.waveform)
    timings.update(embed_result.timings)

    # Mark skipped heads from failed backbones
    for bb, error_message in embed_result.errors.items():
        for head in heads_by_backbone[bb]:
            all_head_results[head.name] = {"status": "skipped", "reason": error_message}

    # Process head predictions sequentially (cheap, mutates shared state)
    for item in embed_result.embeddings:
        backbone, backbone_heads, embeddings_2d = item.backbone, item.heads, item.embeddings
        t_heads_start = internal_ms()
        result = run_heads(backbone_heads, embeddings_2d, tags_accum)
        timings[f"heads_{backbone}"] = internal_ms().value - t_heads_start.value
        # Store per-head timings
        for head_name, head_time_ms in result.per_head_timings.items():
            timings[f"head_{head_name}"] = head_time_ms
        total_heads_succeeded += result.heads_succeeded
        all_head_results.update(result.head_results)
        regression_heads.extend(result.regression_heads)
        all_head_outputs.extend(result.all_head_outputs)
        all_raw_segments.update(result.raw_segments_per_head)
        # Persist pooled track-level embedding vector for this backbone
        if db is not None and file_id is not None:
            assert library_path.library_id is not None  # validated above
            library_key = library_path.library_id.split("/")[-1]
            elapsed_store = persist_backbone_vector(
                db, file_id, backbone, embeddings_2d, model_suite_hash, path, library_key
            )
            if elapsed_store is not None:
                timings[f"vector_store_{backbone}"] = elapsed_store
        del embeddings_2d
        logger.debug(f"[processor] Released {backbone} embeddings from memory")
    if total_heads_succeeded == 0:
        # Check if all heads were skipped (vs failed)
        all_skipped = all(result.get("status") == "skipped" for result in all_head_results.values())
        if all_skipped:
            # All heads skipped due to short audio or other valid reasons
            # Return early with skipped result instead of raising error
            elapsed = round((internal_ms().value - start_all.value) / 1000, 2)
            logger.info(f"[processor] All heads skipped for {path} (e.g., audio too short) - returning empty result")
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
    mood_tags = collect_mood_outputs(regression_heads, all_head_outputs)
    timings["mood_aggregation"] = internal_ms().value - t_mood.value
    tags_accum.update(mood_tags)
    # Build tag→output edge mapping for deferred tag_model_output writes.
    # Queries the graph once to map model ONNX path+label → output vertex _id.
    output_edges: dict[str, tuple[str, float]] = {}
    if db is not None and all_head_outputs:
        output_id_map = build_model_output_id_map(db)
        for ho in all_head_outputs:
            path_map = output_id_map.get(ho.head._path)
            if path_map is not None:
                output_id = path_map.get(ho.label)
                if output_id is not None:
                    output_edges[f"nom:{ho.model_key}"] = (output_id, ho.value)

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
            chromaprint=shared_chromaprint,
            raw_segments=all_raw_segments or {},
            ml_edges=MLEdgeWrites(output_edges=output_edges) if output_edges else None,
        )
    elapsed_ms = internal_ms().value - start_all.value
    elapsed = round(elapsed_ms / 1000, 2)

    # Build timing summary string (attached to result, logged by worker)
    timing_summary: str | None = None
    if db is not None:
        timing_summary = build_timing_summary(timings, elapsed_ms, heads_by_backbone)
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
        mood_aggregations=mood_info or None,
        tags=Tags.from_dict(dict(tags_accum)),
        timing_summary=timing_summary,
        deferred_writes=deferred,
    )
