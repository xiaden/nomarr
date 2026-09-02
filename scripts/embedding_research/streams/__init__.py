"""Frozen observation stream / head-stream model and store (Plan B Phase 1).

Exposes the immutable value objects (:class:`~.records.StreamRecord`,
:class:`~.records.HeadStreamRecord`, :class:`~.records.ReconcileReport`), the registry
constants/columns, and the two read/write seams (:class:`~.store.StreamStore`,
:class:`~.store.HeadStreamStore`).  Pure contracts live in ``records``; the store layer
(``store``) is the only place artifact references are resolved to real paths.
"""

from scripts.embedding_research.streams.records import (
    HEAD_STREAM_REGISTRY_COLUMNS,
    HEAD_STREAM_TABLE,
    STREAM_DTYPE,
    STREAM_REGISTRY_COLUMNS,
    STREAM_STATUSES,
    STREAM_TABLE,
    DuplicateStreamError,
    HeadStreamRecord,
    ReconcileReport,
    StreamNotFoundError,
    StreamNotReadyError,
    StreamRecord,
    StreamStoreError,
    StreamValidationError,
    VerifyFailureError,
    canonical_dim_by_head,
    canonical_head_ids,
    now_ms,
    parse_dim_by_head,
    parse_head_ids,
    validate_artifact_ref,
    validate_dtype,
    validate_fingerprint,
    validate_status,
)
from scripts.embedding_research.streams.store import HeadStreamStore, StreamStore

__all__ = [
    "HEAD_STREAM_REGISTRY_COLUMNS",
    "HEAD_STREAM_TABLE",
    "STREAM_DTYPE",
    "STREAM_REGISTRY_COLUMNS",
    "STREAM_STATUSES",
    "STREAM_TABLE",
    "DuplicateStreamError",
    "HeadStreamRecord",
    "HeadStreamStore",
    "ReconcileReport",
    "StreamNotFoundError",
    "StreamNotReadyError",
    "StreamRecord",
    "StreamStore",
    "StreamStoreError",
    "StreamValidationError",
    "VerifyFailureError",
    "canonical_dim_by_head",
    "canonical_head_ids",
    "now_ms",
    "parse_dim_by_head",
    "parse_head_ids",
    "validate_artifact_ref",
    "validate_dtype",
    "validate_fingerprint",
    "validate_status",
]
