"""Runtime protocol helpers for schema-driven persistence stubs.

The detailed typing surface lives in ``_base.pyi``. This runtime module exists
so ``nomarr.persistence.stubs`` can be imported normally by Python.
"""

from __future__ import annotations

from typing import Any, Protocol, TypedDict, runtime_checkable

from nomarr.persistence.schema import FilterDict


class AggResult(TypedDict):
    """Aggregate result for field value counts."""

    value: str
    count: int


@runtime_checkable
class GetOneProtocol(Protocol):
    """Protocol for unique-value lookup helpers."""

    def __call__(self, value: Any) -> dict[str, Any] | None: ...


@runtime_checkable
class GetOneByIdProtocol(Protocol):
    """Protocol for collection-level single-document `_id` helpers."""

    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...

    def id(self, doc_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class GetManyProtocol(Protocol):
    """Protocol for multi-result lookup helpers."""

    def __call__(
        self,
        value: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class GetManyByFilterProtocol(Protocol):
    """Protocol for collection-level multi-document lookup helpers."""

    def __call__(self, ids: list[str]) -> list[dict[str, Any]]: ...

    def id(self, ids: list[str]) -> list[dict[str, Any]]: ...

    def by_filter(
        self,
        filter_dict: dict[str, Any],
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


@runtime_checkable
class CollectionGetProtocol(Protocol):
    """Protocol for collection-level callable get namespaces."""

    one: GetOneByIdProtocol
    many: GetManyByFilterProtocol

    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...


@runtime_checkable
class GetModifierProtocol(Protocol):
    """Protocol for field-level get modifiers."""

    def __call__(self, value: Any) -> dict[str, Any] | None | list[dict[str, Any]]: ...

    def one(self, value: Any) -> dict[str, Any] | None: ...

    def many(
        self,
        value: Any,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def in_(
        self,
        values: list[Any] | FilterDict,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...

    def like(
        self,
        pattern: str,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]: ...


__all__ = [
    "AggResult",
    "CollectionGetProtocol",
    "GetManyByFilterProtocol",
    "GetManyProtocol",
    "GetModifierProtocol",
    "GetOneByIdProtocol",
    "GetOneProtocol",
]
