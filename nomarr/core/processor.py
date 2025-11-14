"""
High-level audio file processing orchestration.

Coordinates model inference, tag aggregation, and file writing.
"""

from __future__ import annotations

import contextlib
import gc
import logging
import os
import time
from collections import defaultdict
from typing import Any

import numpy as np

# Get Essentia version for tag versioning
try:
    import essentia

    ESSENTIA_VERSION = essentia.__version__
except (ImportError, AttributeError):
    ESSENTIA_VERSION = "unknown"

import nomarr.app as app
from nomarr.data.db import Database
from nomarr.ml.inference import compute_embeddings_for_backbone, make_head_only_predictor_batched
from nomarr.ml.models.discovery import discover_heads
from nomarr.ml.models.embed import pool_scores
from nomarr.ml.models.heads import run_head_decision
from nomarr.tagging.aggregation import (
    add_regression_mood_tiers,
    aggregate_mood_tiers,
    load_calibrations,
    normalize_tag_label,
)
from nomarr.tagging.writer import TagWriter


def _check_already_tagged(path: str, namespace: str, version_tag_key: str, current_version: str) -> bool:
    """Check if file already has correct version tag."""
    try:
        from mutagen import File as MutagenFile

        audio = MutagenFile(path)
        if not audio or not hasattr(audio, "tags") or not audio.tags:
            return False

        # Check for version tag in namespace
        for key in audio.tags:
            key_str = str(key)
            # MP4/M4A format
            if f"----:com.apple.iTunes:{namespace}:{version_tag_key}" in key_str:
                values = audio.tags[key]
                if values and hasattr(values[0], "decode"):
                    existing_version = values[0].decode("utf-8", errors="replace")
                    return existing_version == current_version
            # MP3 format
            elif key_str == f"TXXX:{namespace}:{version_tag_key}":
                values = audio.tags[key]
                if hasattr(values, "text") and values.text:
                    return str(values.text[0]) == current_version

        return False
    except Exception as e:
        logging.debug(f"[processor] Could not check version tag for {path}: {e}")
        return False


def process_file(
    path: str,
    force: bool = False,
    progress_callback=None,
    config: dict[str, Any] | None = None,
    db_path: str | None = None,
) -> dict[str, Any]:
    """
    Main entry point: tag an audio file using all available heads.

    Architecture:
        1. Group heads by backbone (yamnet, vggish, effnet)
        2. For each backbone: compute embeddings ONCE (load → segment → embed)
        3. For each head in backbone: reuse cached embeddings (embed → head predict → pool)

    This avoids redundant embedding computation:
        - Old: 17 heads × full pipeline = ~100s per file
        - New: 3 backbones × embedding + 17 heads × head-only = ~30-50s per file

    Args:
        path: Path to audio file
        force: Ignore version/overwrite guards
        progress_callback: Optional callback(current, total, head_name, event) called during processing
        config: Configuration dict (defaults to app.cfg if not provided)
        db_path: Database path (defaults to app.DB_PATH if not provided)
    """
    from nomarr.ml.cache import check_and_evict_idle_cache, touch_cache

    # Check if cache should be evicted due to inactivity before processing
    if check_and_evict_idle_cache():
        logging.info("[processor] Cache was evicted due to inactivity, will reload on demand")

    # Touch cache to update last access time
    touch_cache()

    # Use injected config or fallback to app.cfg for backward compatibility
    if config is None:
        config = app.cfg
    if db_path is None:
        db_path = app.DB_PATH

    models_dir: str = config["models_dir"]

    if not os.path.exists(path):
        raise RuntimeError(f"File not found: {path}")
    if not os.access(path, os.R_OK):
        raise RuntimeError(f"File not readable: {path}")

    min_dur = int(config["min_duration_s"])
    allow_short = bool(config["allow_short"])
    batch_size = int(config.get("batch_size", 11))
    overwrite = bool(config["overwrite_tags"])
    ns = str(config["namespace"])
    version_tag_key = str(config["version_tag"])
    tagger_version = str(config["tagger_version"])

    # Skip if already tagged with current version (unless force=True)
    if not force and _check_already_tagged(path, ns, version_tag_key, tagger_version):
        logging.info(f"[processor] Skipping {path} - already tagged with version {tagger_version}")
        return {
            "file": path,
            "elapsed": 0.0,
            "duration": 0.0,
            "heads_processed": 0,
            "tags_written": 0,
            "skipped": True,
            "skip_reason": f"already_tagged_v{tagger_version}",
            "tags": {},
        }

    heads = discover_heads(models_dir)
    if not heads:
        raise RuntimeError(f"No head models found under {models_dir}")

    logging.info(f"[processor] Discovered {len(heads)} heads")
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

    # Progress weighting: embeddings are ~60% of work, heads are ~40%
    EMBEDDING_WEIGHT = 0.6
    HEAD_WEIGHT = 0.4
    num_backbones = len(heads_by_backbone)
    num_heads = len(heads)

    def report_progress(current_item: int, total_items: int, name: str, state: str, is_embedding: bool):
        """Report weighted progress for embedding or head phase."""
        if not progress_callback:
            return

        if is_embedding:
            # Embedding phase: 0-60% of total progress
            phase_progress = (current_item / total_items) if total_items > 0 else 0
            overall_progress = phase_progress * EMBEDDING_WEIGHT
            # Scale to percentage (0-100) and convert to "current/total" format
            virtual_current = int(overall_progress * 100)
            virtual_total = 100
        else:
            # Head phase: 60-100% of total progress
            phase_progress = (current_item / total_items) if total_items > 0 else 0
            overall_progress = EMBEDDING_WEIGHT + (phase_progress * HEAD_WEIGHT)
            virtual_current = int(overall_progress * 100)
            virtual_total = 100

        try:
            progress_callback(virtual_current, virtual_total, name, state)
        except TypeError:
            # Fallback for older callback signatures
            with contextlib.suppress(Exception):
                progress_callback(current_item, total_items, name)

    # Process each backbone group completely (embeddings → heads → drop) to minimize memory usage
    # This allows running more workers by not holding all backbone embeddings in memory simultaneously

    for backbone_idx, (backbone, backbone_heads) in enumerate(heads_by_backbone.items(), 1):
        # Use the first head to determine SR and segmentation params
        # (all heads on same backbone should use same SR/segmentation)
        first_head = backbone_heads[0]
        target_sr = first_head.sidecar.sr
        seg_len, hop_len = first_head.sidecar.segment_hop
        emb_graph = first_head.embedding_graph

        # === STEP 1: Compute embeddings for this backbone ===
        embed_name = f"computing {backbone} embeddings"
        report_progress(backbone_idx - 1, num_backbones, embed_name, "start", is_embedding=True)

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

            # Notify UI that embedding computation is complete
            report_progress(backbone_idx, num_backbones, embed_name, "complete", is_embedding=True)

        except RuntimeError as e:
            logging.warning(f"[processor] Skipping backbone {backbone}: {e}")
            # Notify UI that embedding computation failed
            report_progress(backbone_idx, num_backbones, embed_name, "complete", is_embedding=True)
            # Mark all heads in this backbone as skipped
            for h in backbone_heads:
                head_results[h.name] = {"status": "skipped", "reason": str(e)}
            continue

        # === STEP 2: Process all heads for this backbone using the cached embeddings ===
        for head_info in backbone_heads:
            # Calculate head index in overall list for progress reporting
            idx = heads.index(head_info) + 1
            head_name = head_info.name

            # Notify UI that a head is starting
            report_progress(idx - 1, num_heads, head_name, "start", is_embedding=False)

            try:
                t_head = time.time()

                # Build head-only predictor (batched with explicit batch size for VRAM control)
                head_predict_fn = make_head_only_predictor_batched(head_info, embeddings_2d, batch_size=batch_size)

                # Run predictions for ALL segments (potentially in multiple batches)
                S = head_predict_fn()  # Returns [num_segments, num_classes]

                # Pool segment predictions
                pooled_vec = pool_scores(S, mode="trimmed_mean", trim_perc=0.1, nan_policy="omit")

            except Exception as e:
                logging.error(f"[processor] Processing error for {head_name}: {e}", exc_info=True)
                head_results[head_name] = {"status": "error", "error": str(e), "stage": "processing"}
                report_progress(idx, num_heads, head_name, "complete", is_embedding=False)
                continue

            try:
                decision = run_head_decision(head_info.sidecar, pooled_vec, prefix="")

                # Build versioned tag keys using runtime framework version and model metadata
                # Normalize labels (non_happy -> not_happy) before building keys
                # Capture head_info in closure to avoid late binding issue
                head_tags = decision.as_tags(
                    key_builder=lambda label, h=head_info: h.build_versioned_tag_key(
                        normalize_tag_label(label),
                        framework_version=ESSENTIA_VERSION,
                        calib_method="none",
                        calib_version=0,
                    )
                )

                # Combined log: processing complete + tags produced
                logging.info(
                    f"[processor] Head {head_name} complete: {len(S)} patches → {len(head_tags)} tags "
                    f"in {time.time() - t_head:.1f}s"
                )

                if len(head_tags) == 0:
                    logging.warning(f"[processor] Head {head_name} produced ZERO tags")

                tags_accum.update(head_tags)
                heads_succeeded += 1

                # Capture raw segment predictions for regression heads (approachability, engagement)
                # These will be used to generate mood tier tags with variance-based confidence
                if head_info.head_type == "identity" and head_name.endswith("_regression"):
                    # S is [num_segments, 1] for regression heads, extract first column
                    if S.ndim == 2:
                        raw_values = [float(x) for x in S[:, 0]]  # Extract first column as float list
                    else:
                        raw_values = [float(x) for x in S]  # Already 1D
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

                # Report progress after successful head
                report_progress(idx, num_heads, head_name, "complete", is_embedding=False)

            except Exception as e:
                logging.error(f"[processor] Decision error for {head_name}: {e}", exc_info=True)
                head_results[head_name] = {"status": "error", "error": str(e), "stage": "decision"}
                report_progress(idx, num_heads, head_name, "complete", is_embedding=False)
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

    # Convert regression head predictions (approachability, engagement) to mood tier tags
    add_regression_mood_tiers(tags_accum, regression_predictions)

    # Load calibrations if available (conditional - gracefully handles missing files)
    calibrations = load_calibrations(models_dir)
    if calibrations:
        logging.info(f"[aggregation] Loaded calibrations for {len(calibrations)} labels")
    else:
        logging.debug("[aggregation] No calibrations found, using raw scores")

    aggregate_mood_tiers(tags_accum, mood_terms if mood_terms else None, calibrations)

    tags_accum[version_tag_key] = tagger_version
    logging.info(f"[processor] Writing {len(tags_accum)} tags to file")
    writer.write(path, tags_accum)
    logging.info("[processor] Tag write complete")

    # Update library database with the newly written tags
    try:
        from nomarr.core.library_scanner import update_library_file_from_tags

        if db_path:
            db = Database(db_path)
            try:
                # Pass tagger_version so library scanner marks file as tagged
                update_library_file_from_tags(db, path, ns, tagged_version=tagger_version)
                logging.info(f"[processor] Updated library database for {path}")
            finally:
                db.close()
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
