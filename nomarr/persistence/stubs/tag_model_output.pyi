from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class TagModelOutputUniqueGetUpdateNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class TagModelOutputUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class TagModelOutputGetCollectDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class TagModelOutputGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class TagModelOutputGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class TagModelOutputGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class TagModelOutputNamespace(Protocol):
    get: CollectionGetProtocol
    _key: TagModelOutputUniqueGetUpdateNamespace
    _id: TagModelOutputUniqueGetOnlyNamespace
    _from: TagModelOutputGetCollectDeleteNamespace
    _to: TagModelOutputGetDeleteNamespace
    score: TagModelOutputGetUpdateNamespace
    created_at: TagModelOutputGetOnlyNamespace
    updated_at: TagModelOutputGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
