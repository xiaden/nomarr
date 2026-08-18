"""ML output stream persistence using PostgreSQL-backed facades."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.library.library_song_state_comp import transition_song_state
from nomarr.components.ml.onnx.ml_model_registry_comp import build_model_output_index_map
from nomarr.helpers.constants.file_states import STATE_NOT_PROCESSED, STATE_PROCESSED
from nomarr.helpers.dto.ml_dto import LoadedOutputStream

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


_STREAM_TABLE = "ml_output_streams"
_FILE_TABLE = "songs"
_OUTPUT_TABLE = "ml_model_outputs"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreamWrite:
    """Canonical write payload for one output stream."""

    output_id: str
    values: list[float]


@dataclass(frozen=True)
class StreamRecord:
    """Fetched canonical stream for one model output."""

    output_id: str
    output_index: int
    values: list[float]


def _stream_key(song_id: int, output_id: str | int) -> str:
    """Build the stable key for one canonical output stream."""
    return hashlib.sha1(f"{song_id}|{output_id}".encode()).hexdigest()


def _normalize_streams(streams: list[StreamWrite]) -> list[StreamWrite]:
    """Deduplicate writes by output id so the last stream wins within one batch."""
    deduped: dict[str, StreamWrite] = {}
    for stream in streams:
        output_id = stream.output_id
        deduped[output_id] = StreamWrite(
            output_id=output_id,
            values=[float(value) for value in stream.values],
        )
    return list(deduped.values())


def build_output_stream_payloads(streams: list[StreamWrite]) -> list[dict[str, Any]]:
    """Build canonical ``{output_id, values}`` stream payloads for the aggregate.

    Normalizes the write batch (last stream wins per output id) and returns the
    canonical payloads that ``db.ml.replace_song_inference_results`` persists to
    ``ml_output_streams``. The live write path no longer upserts streams
    directly — it forwards these payloads through the aggregate alongside the
    song's backbone vector payloads in one atomic replacement.
    """
    return [{"output_id": stream.output_id, "values": stream.values} for stream in _normalize_streams(streams)]


def fetch_output_streams(db: Database, song_id: int) -> list[StreamRecord]:
    """Fetch all canonical output streams linked to one song."""
    stream_docs = db.ml.list_output_streams_for_song(song_id)
    if not stream_docs:
        return []

    records: list[StreamRecord] = []
    for stream_doc in stream_docs:
        output_id = stream_doc.get("output_id")
        output_index = stream_doc.get("output_index")
        values = stream_doc.get("values", [])
        if not isinstance(output_id, str) or not isinstance(output_index, int) or not isinstance(values, list):
            continue

        records.append(
            StreamRecord(
                output_id=output_id,
                output_index=output_index,
                values=[float(value) for value in values],
            )
        )

    records.sort(key=lambda record: (record.output_index, record.output_id))
    return records


def build_output_stream_lookup(
    db: Database,
    head_infos: list[Any],
) -> dict[str, tuple[str, str]]:
    """Build ``{output_id: (head_name, label)}`` from registered outputs and heads."""
    output_index_map = build_model_output_index_map(db)
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
    song_id: int,
    file_path: str,
    head_infos: list[Any],
    *,
    output_lookup: dict[str, tuple[str, str]] | None = None,
) -> list[LoadedOutputStream]:
    """Load canonical streams for one song and enrich them with discovered head metadata."""
    stream_records = fetch_output_streams(db, song_id)
    if not stream_records:
        logger.warning(
            "[output_stream_store] No canonical output streams found for %s, transitioning to not_processed for re-inference",
            file_path,
        )
        transition_song_state(db, [song_id], STATE_PROCESSED, STATE_NOT_PROCESSED)
        return []

    lookup = resolve_output_stream_lookup(db, head_infos, cached_lookup=output_lookup)
    output_streams: list[LoadedOutputStream] = []
    unmatched_output_ids: list[str] = []

    for stream_record in stream_records:
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
        transition_song_state(db, [song_id], STATE_PROCESSED, STATE_NOT_PROCESSED)
        return []

    logger.debug(
        "[output_stream_store] Loaded %s canonical output streams for %s",
        len(output_streams),
        file_path,
    )
    return output_streams


def delete_output_streams(db: Database, song_id: int) -> int:
    """Delete all canonical output streams for one song."""
    stream_docs = db.ml.list_output_streams_for_song(song_id)
    stream_ids = sorted(
        {stream_id for stream_doc in stream_docs if isinstance((stream_id := stream_doc.get("id")), (str, int))}
    )
    if not stream_ids:
        return 0

    db.ml.remove_output_streams_for_song(song_id)
    return len(stream_ids)
