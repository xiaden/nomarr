"""Type stubs for schema-driven persistence namespaces.

These Protocol classes provide mypy and IDE support for the dynamically
constructed namespace objects. Callers type-hint against these Protocols.
"""

from __future__ import annotations

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionDeleteVerbProtocol,
    CollectionGetVerbProtocol,
    DeleteVerbProtocol,
    DeleteWithCascadeProtocol,
    FieldAccessorProtocol,
    GetVerbProtocol,
    TraversalVerbProtocol,
)

__all__ = [
    "AggResult",
    "CollectionDeleteVerbProtocol",
    "CollectionGetVerbProtocol",
    "DeleteVerbProtocol",
    "DeleteWithCascadeProtocol",
    "FieldAccessorProtocol",
    "GetVerbProtocol",
    "TraversalVerbProtocol",
]
