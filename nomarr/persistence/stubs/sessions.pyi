from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class SessionsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class SessionsUniqueGetDeleteUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class SessionsGetDeleteNamespace(Protocol):
    get: GetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class SessionsGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class SessionsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: SessionsUniqueGetOnlyNamespace
    _id: SessionsUniqueGetOnlyNamespace
    session_id: SessionsUniqueGetDeleteUpsertNamespace
    user_id: SessionsGetDeleteNamespace
    expiry_timestamp: SessionsGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
