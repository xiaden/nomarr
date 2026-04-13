from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import AggResult, CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class TagsRelNamespace(Protocol):
    get: GetModifierProtocol

    def count(self, value: str) -> int: ...
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def aggregate(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[AggResult]: ...

@runtime_checkable
class TagsValueNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class TagsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: Any
    _id: Any
    rel: TagsRelNamespace
    value: TagsValueNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    def traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
