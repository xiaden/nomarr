"""Component-owned persistence helpers for canonical ML output streams."""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from nomarr.components.ml.onnx.ml_model_registry_comp import build_model_output_index_map
from nomarr.helpers.dto.ml_dto import LoadedOutputStream

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


_STREAM_COLLECTION = "ml_output_streams"
_FILE_COLLECTION = "library_files"
_OUTPUT_COLLECTION = "ml_model_outputs"

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


def _as_document_id(collection: str, doc_id_or_key: str) -> str:
    """Normalize an Arango `_id` or `_key` into a full document `_id`."""
    if "/" in doc_id_or_key:
        return doc_id_or_key
    return f"{collection}/{doc_id_or_key}"


def _document_key(doc_id_or_key: str) -> str:
    """Extract the document `_key` from an Arango `_id` or `_key`."""
    if "/" in doc_id_or_key:
        return doc_id_or_key.split("/", 1)[1]
    return doc_id_or_key


def _stream_key(file_id: str, output_id: str) -> str:
    """Build the stable document key for one canonical output stream."""
    file_key = _document_key(file_id)
    output_key = _document_key(output_id)
    return hashlib.sha1(f"{file_key}|{output_key}".encode()).hexdigest()


def _file_stream_edge_key(file_id: str, stream_id: str) -> str:
    """Build the stable edge key linking a file to one stream document."""
    return hashlib.sha256(f"{file_id}:{stream_id}".encode()).hexdigest()[:16]


def _output_stream_edge_key(output_id: str, stream_id: str) -> str:
    """Build the stable edge key linking a model output to one stream document."""
    return hashlib.sha256(f"{output_id}:{stream_id}".encode()).hexdigest()[:16]


def _normalize_streams(streams: list[StreamWrite]) -> list[StreamWrite]:
    """Deduplicate writes by output id so the last stream wins within one batch."""
    deduped: dict[str, StreamWrite] = {}
    for stream in streams:
        output_id = _as_document_id(_OUTPUT_COLLECTION, stream.output_id)
        deduped[output_id] = StreamWrite(
            output_id=output_id,
            values=[float(value) for value in stream.values],
        )
    return list(deduped.values())


def upsert_output_streams(db: Database, *, file_id: str, streams: list[StreamWrite]) -> None:
    """Upsert canonical raw output streams and ensure their file/output edges exist."""
    if not streams:
        return

    normalized_file_id = _as_document_id(_FILE_COLLECTION, file_id)
    normalized_streams = _normalize_streams(streams)
    db.ml.replace_output_streams_for_file(
        file_id=normalized_file_id,
        stream_payloads=[
            {
                "output_id": stream.output_id,
                "values": stream.values,
            }
            for stream in normalized_streams
        ],
    )


def fetch_output_streams(db: Database, file_id: str) -> list[StreamRecord]:
    """Fetch all canonical output streams linked to one file."""
    normalized_file_id = _as_document_id(_FILE_COLLECTION, file_id)
    stream_docs = db.ml.list_output_streams_for_file(normalized_file_id)
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


def load_output_streams_for_file(
    db: Database,
    file_id: str,
    file_path: str,
    head_infos: list[Any],
    *,
    output_lookup: dict[str, tuple[str, str]] | None = None,
) -> list[LoadedOutputStream]:
    """Load canonical streams for one file and enrich them with discovered head metadata."""
    stream_records = fetch_output_streams(db, file_id)
    if not stream_records:
        logger.warning(
            "[output_stream_store] No canonical output streams found for %s, skipping (file needs reprocessing)",
            file_path,
        )
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
            "skipping (file needs reprocessing): %s",
            len(unmatched_output_ids),
            file_path,
            unmatched_output_ids,
        )
        return []

    logger.debug(
        "[output_stream_store] Loaded %s canonical output streams for %s",
        len(output_streams),
        file_path,
    )
    return output_streams


def delete_output_streams(db: Database, file_id: str) -> int:
    """Delete all canonical output streams and both edge types for one file."""
    normalized_file_id = _as_document_id(_FILE_COLLECTION, file_id)
    stream_docs = db.ml.list_output_streams_for_file(normalized_file_id)
    stream_ids = sorted(
        {stream_id for stream_doc in stream_docs if isinstance((stream_id := stream_doc.get("_id")), str)}
    )
    if not stream_ids:
        return 0

    db.ml.replace_output_streams_for_file(normalized_file_id, [])
    return len(stream_ids)
