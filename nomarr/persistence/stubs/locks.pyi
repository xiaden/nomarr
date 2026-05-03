from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class LocksUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class LocksUniqueGetDeleteUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class LocksGetCollectNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LocksGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LocksGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LocksNamespace(Protocol):
    get: CollectionGetProtocol
    _key: LocksUniqueGetOnlyNamespace
    _id: LocksUniqueGetOnlyNamespace
    document_reference: LocksUniqueGetDeleteUpsertNamespace
    lock_type: LocksGetCollectNamespace
    expires_at: LocksGetUpdateNamespace
    acquired_at: LocksGetOnlyNamespace
    holder: LocksGetOnlyNamespace
    status: LocksGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
