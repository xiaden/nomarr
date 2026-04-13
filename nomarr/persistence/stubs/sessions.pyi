from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol, GetOneProtocol

@runtime_checkable
class SessionsSessionIdNamespace(Protocol):
    get: GetOneProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class SessionsUserIdNamespace(Protocol):
    get: GetModifierProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class SessionsExpiryTimestampNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: int, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class SessionsNamespace(Protocol):
    get: CollectionGetProtocol
    session_id: SessionsSessionIdNamespace
    user_id: SessionsUserIdNamespace
    expiry_timestamp: SessionsExpiryTimestampNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
