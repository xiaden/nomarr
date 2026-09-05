"""Frozen observation stream / head-stream model and store (Plan B Phase 1).

Exposes the immutable value objects (:class:`~.records.StreamRecord`,
:class:`~.records.HeadStreamRecord`, :class:`~.records.ReconcileReport`,
:class:`~.records.ReindexReport`), the registry constants/columns, the two read/write
seams (:class:`~.store.StreamStore`, :class:`~.store.HeadStreamStore`), the current-stream
resolver seam (:class:`~.store.CurrentStreamResolver` plus its
:func:`~.store.make_current_stream_resolver` factory), and the reindex maintenance entry
points (:func:`~.reindex.reconcile_current_manifests`, :func:`~.reindex.reindex`).  Pure
contracts live in ``records``; the runtime read path (``store``) is the place artifact
references are resolved to real paths there, while ``reindex`` additionally resolves
current-format refs during its maintenance walk over the current manifests.
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
    ReindexReport,
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
from scripts.embedding_research.streams.reindex import (
    reconcile_current_manifests,
    reindex,
)
from scripts.embedding_research.streams.store import (
    CurrentStreamResolver,
    HeadStreamStore,
    StreamStore,
    make_current_stream_resolver,
)

__all__ = [
    "HEAD_STREAM_REGISTRY_COLUMNS",
    "HEAD_STREAM_TABLE",
    "STREAM_DTYPE",
    "STREAM_REGISTRY_COLUMNS",
    "STREAM_STATUSES",
    "STREAM_TABLE",
    "CurrentStreamResolver",
    "DuplicateStreamError",
    "HeadStreamRecord",
    "HeadStreamStore",
    "ReconcileReport",
    "ReindexReport",
    "StreamNotFoundError",
    "StreamNotReadyError",
    "StreamRecord",
    "StreamStore",
    "StreamStoreError",
    "StreamValidationError",
    "VerifyFailureError",
    "canonical_dim_by_head",
    "canonical_head_ids",
    "make_current_stream_resolver",
    "now_ms",
    "parse_dim_by_head",
    "parse_head_ids",
    "reconcile_current_manifests",
    "reindex",
    "validate_artifact_ref",
    "validate_dtype",
    "validate_fingerprint",
    "validate_status",
]
