from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class TagModelOutputGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class TagModelOutputKeyNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class TagModelOutputDeleteNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class TagModelOutputFromNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class TagModelOutputUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class TagModelOutputNamespace(Protocol):
    get: CollectionGetProtocol
    _key: TagModelOutputKeyNamespace
    _id: TagModelOutputGetOnlyNamespace
    _from: TagModelOutputFromNamespace
    _to: TagModelOutputDeleteNamespace
    score: TagModelOutputUpdateNamespace
    created_at: TagModelOutputGetOnlyNamespace
    updated_at: TagModelOutputUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
