"""Calibrated tags database updater workflow.

This workflow applies calibration to existing library files without re-running ML inference.
It reconstructs HeadOutput objects from canonical raw output streams and calibration
metadata, then re-runs aggregation to update mood-* tags IN THE DATABASE ONLY.

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
from typing import TYPE_CHECKING, Any, cast

from nomarr.components.library.library_records_comp import find_library_containing_path
from nomarr.components.library.library_song_query_comp import (
    _library_identity,
    _song_identity,
    get_library_song,
)
from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.ml.calibration.ml_calibration_comp import mood_tags_to_assignments
from nomarr.components.ml.calibration.ml_calibration_state_comp import (
    get_calibration_version,
    load_calibration_lookup,
    update_file_calibration_hash,
)
from nomarr.components.ml.inference.ml_output_stream_store_comp import (
    build_output_stream_lookup,
    load_output_streams_for_song,
)
from nomarr.components.ml.onnx.ml_discovery_comp import discover_heads
from nomarr.components.tagging.tagging_aggregation_comp import aggregate_mood_tags
from nomarr.components.tagging.tagging_reconstruction_comp import (
    reconstruct_head_outputs_from_streams,
)
from nomarr.helpers.constants.file_states import STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH
from nomarr.helpers.dataclasses.song_tag_dataclass import (
    CalibrationMoodMarker,
    MoodReplacementCommand,
)

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.helpers.dto.calibration_dto import WriteCalibratedTagsParams
    from nomarr.helpers.dto.ml_head_dto import HeadInfo
    from nomarr.persistence.db import Database

logger = logging.getLogger(__name__)


def _resolve_song_identity_for_path(db: Database, file_path: str) -> SongIdentity:
    """Resolve a physical library path to its natural ADR-048 locator."""
    library = find_library_containing_path(db, file_path)
    if library is None:
        raise FileNotFoundError(f"File not found in a configured library: {file_path}")
    song = get_library_song(db, file_path, library=library)
    if song is None:
        raise FileNotFoundError(f"File not found in the library database: {file_path}")
    return _song_identity(song, _library_identity(library))


@dataclass
class BatchContext:
    """Pre-computed invariants for batch calibration apply.

    When processing many files, these values are computed once per chunk and reused,
    while DB reads remain live component calls per file.

    Attributes:
        heads: Discovered HeadInfo objects from discover_heads()
        calibrations: Calibration data from load_calibration_lookup()
        calibration_version: Global calibration version string
        output_stream_lookup: Optional cached mapping of output_id to
            ``(head_name, label)`` derived from registered model outputs.
        pending_mood_commands: Accumulated typed mood commands for the owner's
            deferred all-or-none batch write.
        pending_calibration_hashes: Accumulated (song, calibration_version) updates.

    """

    heads: list[Any]
    calibrations: dict[str, Any]
    calibration_version: str | None
    output_stream_lookup: dict[str, tuple[str, str]] | None = None
    pending_mood_commands: list[MoodReplacementCommand] = field(default_factory=list)
    pending_calibration_hashes: list[tuple[SongIdentity, str]] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)


def write_calibrated_tags_wf(
    db: Database,
    params: WriteCalibratedTagsParams,
    *,
    batch_ctx: BatchContext | None = None,
) -> bool:
    """Update mood-* tags in the database by re-applying calibration.

    DB-only operation — does NOT write to audio files on disk.
    File writes are handled by the reconcile / write_file_tags_wf pipeline
    which reads the updated DB mood tags and writes them to disk.

    This workflow:
    1. Loads canonical output streams from DB for the file
    2. Loads calibration metadata from calibration_state
    3. Discovers HeadInfo from models directory
    4. Reconstructs HeadOutput objects from streams + calibration
    5. Re-runs aggregation to compute mood-* tags
    6. Updates mood-* tags in DB
    7. Records calibration_hash on the file record

    This is much faster than retagging because it skips ML inference entirely,
    reusing the canonical raw output streams already stored in the database.

    Sequencing (binding): computation -> mood publication + marker (owner
    transaction) -> separate locator-addressed calibration hash/state ->
    ``STATE_TAGS_NOT_FRESH`` marking for filesystem reconciliation by locator.
    The single-file branch is self-contained: on a successful mood publication
    (``UPDATED``/``UNCHANGED``) it records the hash and marks the located song
    ``STATE_TAGS_NOT_FRESH`` for downstream reconciliation. A non-success
    owner status returns ``False`` without a hash or state change;
    ``AMBIGUOUS_COMMIT`` is never retried by this caller.

    Batch mode defers both the mood commands and the hash updates to
    ``apply_calibration_wf``, which owns the flush and the corresponding
    reconciliation marking for the whole chunk.

    Args:
        db: Database instance (must provide library, tags accessors)
        params: WriteCalibratedTagsParams containing:
            - file_path: Absolute path to audio file
            - models_dir: Path to models directory
            - namespace: Tag namespace (e.g., "nom")
            - version_tag_key: Un-namespaced key for version tag
            - calibrate_heads: Whether to use versioned calibration files
        batch_ctx: Pre-computed batch context (batch optimization).
            When provided, reuses cached heads, calibrations, and output lookup
            metadata instead of re-computing them for every file. DB writes are
            deferred to the batch flush.

    Returns:
        ``True`` when tags were queued or written; ``False`` when no
        calibrated output was available.

    Raises:
        FileNotFoundError: If file not found in library database
        ValueError: If no heads discovered

    """
    file_path = params.file_path
    models_dir = params.models_dir
    logger.debug("[calibrated_tags] Processing %s", file_path)
    song = _resolve_song_identity_for_path(db, file_path)

    # Use cached values from batch context when available
    heads: list[Any] | None = batch_ctx.heads if batch_ctx is not None else None
    calibrations = batch_ctx.calibrations if batch_ctx is not None else load_calibration_lookup(db)

    # Use discovered heads or discover them
    heads_list: list[Any]
    if heads is None:
        heads_list = discover_heads(models_dir, db)
        if not heads_list:
            msg = f"No heads discovered in {models_dir}"
            raise ValueError(msg)
    else:
        heads_list = heads

    output_stream_lookup = batch_ctx.output_stream_lookup if batch_ctx is not None else None
    if output_stream_lookup is None:
        output_stream_lookup = build_output_stream_lookup(db, heads_list)
        if batch_ctx is not None:
            with batch_ctx._lock:
                if batch_ctx.output_stream_lookup is None:
                    batch_ctx.output_stream_lookup = output_stream_lookup
                output_stream_lookup = batch_ctx.output_stream_lookup

    output_streams = load_output_streams_for_song(
        db,
        song,
        file_path,
        heads_list,
        output_lookup=output_stream_lookup,
    )
    if not output_streams:
        logger.warning("[calibrated_tags] No output streams found for %s", file_path)
        return False

    head_outputs = reconstruct_head_outputs_from_streams(
        output_streams=output_streams,
        head_infos=cast("list[HeadInfo]", heads_list),
        calibrations=calibrations,
    )
    if not head_outputs:
        logger.warning("[calibrated_tags] No calibrated outputs reconstructed for %s", file_path)
        return False
    mood_tags = aggregate_mood_tags(head_outputs)
    # mood_tags may be None when all labels conflict or scores are below threshold.
    # None is a valid calibration result — the owner clears all mood tiers while
    # still applying the marker, and the hash is updated so the file is not
    # re-queued on every apply run.
    if not mood_tags:
        logger.debug(
            "[calibrated_tags] No mood tags produced for %s — clearing tiers and marking hash",
            file_path,
        )

    assignments = mood_tags_to_assignments(mood_tags)
    global_version = batch_ctx.calibration_version if batch_ctx is not None else get_calibration_version(db)
    marker = (
        CalibrationMoodMarker.calibrated(global_version)
        if global_version is not None
        else CalibrationMoodMarker.uncalibrated()
    )
    command = MoodReplacementCommand(song=song, assignments=assignments, marker=marker)

    # Mood publication (assignments + marker) precedes the separate locator
    # hash/state update. Batch mode defers one all-or-none owner transaction;
    # single-file mode publishes immediately through the exact tag owner.
    if batch_ctx is not None:
        with batch_ctx._lock:
            batch_ctx.pending_mood_commands.append(command)
            if global_version:
                batch_ctx.pending_calibration_hashes.append((song, global_version))
    else:
        # Single-file mode publishes immediately through the exact tag owner and
        # consumes the typed result exactly like the batch path: only a successful
        # publication may advance to the separate locator hash/state step and
        # the STATE_TAGS_NOT_FRESH reconciliation marking. AMBIGUOUS_COMMIT is
        # never retried by the caller (owner contract: no blind retry).
        mood_result = db.library.tags.replace_mood_tags(song, assignments, marker)
        if mood_result.status not in ("UPDATED", "UNCHANGED"):
            logger.warning(
                "[calibrated_tags] Mood publication did not complete (%s)",
                mood_result.status,
            )
            return False
        if global_version:
            update_file_calibration_hash(db, song, global_version)
        if STATE_TAGS_CURRENT in db.app.song_state_membership(song):
            transition_song_state(db, [song], STATE_TAGS_CURRENT, STATE_TAGS_NOT_FRESH)
        logger.debug("[calibrated_tags] Updated mood tags in DB for %s", file_path)
    return True
