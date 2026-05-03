from __future__ import annotations

from typing import Any, Protocol, TypedDict

from nomarr.helpers.filter_types import FilterDict

class AggResult(TypedDict):
    value: str
    count: int

class GetOneProtocol(Protocol):
    def __call__(self, value: Any) -> dict[str, Any] | None: ...

class GetOneByIdProtocol(Protocol):
    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...
    def id(self, doc_id: str) -> dict[str, Any] | None: ...

class GetManyProtocol(Protocol):
    def __call__(
        self,
        value: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class GetManyByFilterProtocol(Protocol):
    def __call__(self, ids: list[str]) -> list[dict[str, Any]]: ...
    def id(self, ids: list[str]) -> list[dict[str, Any]]: ...
    def by_filter(
        self,
        filter_dict: dict[str, Any],
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class CollectionGetProtocol(Protocol):
    one: GetOneByIdProtocol
    many: GetManyByFilterProtocol

    def __call__(self, doc_id: str) -> dict[str, Any] | None: ...

class UniqueGetModifierProtocol(Protocol):
    """GetModifierProtocol for unique fields: __call__ returns a single doc or None."""
    def __call__(self, value: Any) -> dict[str, Any] | None: ...
    def one(self, value: Any) -> dict[str, Any] | None: ...
    def many(
        self,
        value: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def in_(
        self,
        values: list[Any] | FilterDict,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def like(
        self,
        pattern: str,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class GetModifierProtocol(Protocol):
    def __call__(self, value: Any) -> dict[str, Any] | None | list[dict[str, Any]]: ...
    def one(self, value: Any) -> dict[str, Any] | None: ...
    def many(
        self,
        value: Any,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def in_(
        self,
        values: list[Any] | FilterDict,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def like(
        self,
        pattern: str,
        *,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...

class DeleteModifierProtocol(Protocol):
    def __call__(self, value: Any) -> int: ...
    def in_(self, values: list[Any]) -> int: ...

class TraversalProtocol(Protocol):
    def __call__(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
    def by_ids(
        self,
        start_ids: list[str],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        target_like_starts_with: tuple[str, str] | None = ...,
    ) -> list[dict[str, Any]]: ...
