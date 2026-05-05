from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.helpers.filter_types import AggResult as AggResult

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

@runtime_checkable
class GetVerbProtocol(Protocol):
    """Field-level get verb (``_GetVerb``). Attached as ``collection.<field>.get``."""

    def __call__(self, value: Any) -> dict[str, Any] | None | list[dict[str, Any]]: ...
    def many(self, value: Any, *, limit: int | None = ..., offset: int = ...) -> list[dict[str, Any]]: ...
    def in_(self, values: list[Any], *, limit: int | None = ..., offset: int = ...) -> list[dict[str, Any]]: ...
    def gte(self, value: Any, *, limit: int | None = ..., offset: int = ...) -> list[dict[str, Any]]: ...
    def lte(self, value: Any, *, limit: int | None = ..., offset: int = ...) -> list[dict[str, Any]]: ...
    def like(self, pattern: str, *, limit: int | None = ..., offset: int = ...) -> list[dict[str, Any]]: ...

@runtime_checkable
class DeleteVerbProtocol(Protocol):
    """Field-level delete verb (``_DeleteVerb``). Attached as ``collection.<field>.delete``."""

    def __call__(self, value: Any) -> int: ...
    def in_(self, values: list[Any]) -> int: ...

@runtime_checkable
class FieldAccessorProtocol(Protocol):
    """Field accessor (``FieldAccessor``). Attached as ``collection.<field>``."""

    get: GetVerbProtocol
    delete: DeleteVerbProtocol

    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update(self, value: Any, fields: dict[str, Any]) -> None: ...
    def upsert(self, value: Any, fields: dict[str, Any]) -> list[str]: ...
    def count(self, value: Any) -> int: ...

@runtime_checkable
class CollectionGetVerbProtocol(Protocol):
    """Collection-level get verb (``_CollectionGetVerb``). Attached as ``collection.get``."""

    def __call__(
        self,
        *args: Any,
        limit: int | None = ...,
        offset: int = ...,
        **kwargs: Any,
    ) -> dict[str, Any] | None | list[dict[str, Any]]: ...
    def many(
        self,
        *args: Any,
        limit: int | None = ...,
        offset: int = ...,
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...
    def in_(
        self,
        *args: Any,
        limit: int | None = ...,
        offset: int = ...,
        **kwargs: Any,
    ) -> list[dict[str, Any]]: ...
    def gte(
        self,
        field_name: str,
        threshold: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def lte(
        self,
        field_name: str,
        threshold: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def like(
        self,
        field_name: str,
        pattern: str,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

@runtime_checkable
class CollectionDeleteVerbProtocol(Protocol):
    """Collection-level delete verb (``_CollectionDeleteVerb``). Attached as ``collection.delete``."""

    def __call__(self, *args: Any, **kwargs: Any) -> int: ...

@runtime_checkable
class DeleteWithCascadeProtocol(CollectionDeleteVerbProtocol, Protocol):
    """Collection delete with ``cascade`` attached (collections with outbound CASCADE edges)."""

    def cascade(self, file_ids: list[str]) -> int: ...

@runtime_checkable
class TraversalVerbProtocol(Protocol):
    """Traversal verb (``_TraversalVerb``). Attached as ``collection.<edge_name>``."""

    def __call__(self, doc_id: str, limit: int | None = ...) -> list[dict[str, Any]]: ...
    def by_ids(self, ids: list[str], limit: int | None = ..., **filters: Any) -> list[dict[str, Any]]: ...
