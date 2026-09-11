"""ML output stream persistence using PostgreSQL-backed facades."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.dto.ml_dto import LoadedOutputStream

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStream
    from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
    from nomarr.persistence.db import Database


logger = logging.getLogger(__name__)


def fetch_output_streams(db: Database, song: SongIdentity) -> list[OutputStream]:
    """Fetch all canonical output streams linked to one song."""
    # Concurrent persistence-facade work owns row-to-domain mapping; this
    # component consumes only the resulting domain objects.
    records = db.ml.list_output_streams_for_song(song)
    return sorted(
        records,
        key=lambda record: (
            record.output_index if record.output_index is not None else float("inf"),
            record.output_id,
        ),
    )


def build_output_stream_lookup(
    db: Database,
    head_infos: list[Any],
) -> dict[str, tuple[str, str]]:
    """Build ``{output_id: (head_name, label)}`` from registered outputs and heads."""
    output_index_map = db.ml.model_output_index_map()
    output_lookup: dict[str, tuple[str, str]] = {}

    for head_info in head_infos:
        model_path = str(head_info.model_path)
        model_outputs = output_index_map.get(model_path, {})
        if not model_outputs:
            logger.debug(
                "[output_stream_store] No registered model outputs found for %s (%s)",
                head_info.name,
                model_path,
            )
            continue

        for output_index, output_id in model_outputs.items():
            if not 0 <= output_index < len(head_info.labels):
                logger.warning(
                    "[output_stream_store] Output index %s for %s falls outside discovered labels; skipping %s",
                    output_index,
                    head_info.name,
                    output_id,
                )
                continue

            output_lookup[output_id] = (
                str(head_info.name),
                str(head_info.labels[output_index]),
            )

    return output_lookup


def resolve_output_stream_lookup(
    db: Database,
    head_infos: list[Any],
    *,
    cached_lookup: dict[str, tuple[str, str]] | None = None,
) -> dict[str, tuple[str, str]]:
    """Return cached output-stream enrichment metadata when available."""
    if cached_lookup is not None:
        return cached_lookup
    return build_output_stream_lookup(db, head_infos)


def load_output_streams_for_song(
    db: Database,
    song: SongIdentity,
    file_path: str,
    head_infos: list[Any],
    *,
    output_lookup: dict[str, tuple[str, str]] | None = None,
) -> list[LoadedOutputStream]:
    """Load canonical streams for one song and enrich them with discovered head metadata."""
    stream_records = fetch_output_streams(db, song)
    if not stream_records:
        logger.warning(
            "[output_stream_store] No canonical output streams found for %s, transitioning to not_processed for re-inference",
            file_path,
        )
        transition_song_state(db, [song], STATE_PROCESSED, STATE_NOT_PROCESSED)
        return []

    lookup = resolve_output_stream_lookup(db, head_infos, cached_lookup=output_lookup)
    output_streams: list[LoadedOutputStream] = []
    unmatched_output_ids: list[str] = []

    for stream_record in stream_records:
        if stream_record.output_index is None:
            # Legacy rows without ordering metadata cannot be reconstructed into
            # the indexed LoadedOutputStream contract.
            continue
        output_meta = lookup.get(stream_record.output_id)
        if output_meta is None:
            unmatched_output_ids.append(stream_record.output_id)
            continue

        head_name, label = output_meta
        output_streams.append(
            LoadedOutputStream(
                head_name=head_name,
                output_id=stream_record.output_id,
                output_index=stream_record.output_index,
                label=label,
                values=list(stream_record.values),
            )
        )

    if unmatched_output_ids:
        logger.warning(
            "[output_stream_store] %s canonical output streams for %s could not be matched to discovered heads, "
            "transitioning to not_processed for re-inference: %s",
            len(unmatched_output_ids),
            file_path,
            unmatched_output_ids,
        )
        transition_song_state(db, [song], STATE_PROCESSED, STATE_NOT_PROCESSED)
        return []

    logger.debug(
        "[output_stream_store] Loaded %s canonical output streams for %s",
        len(output_streams),
        file_path,
    )
    return output_streams
