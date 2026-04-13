from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol, GetOneProtocol

@runtime_checkable
class LocksDocumentReferenceNamespace(Protocol):
    get: GetOneProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class LocksLockTypeNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class LocksAcquiredAtNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LocksHolderNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class LocksExpiresAtNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: float, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LocksStatusNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class LocksNamespace(Protocol):
    get: CollectionGetProtocol
    document_reference: LocksDocumentReferenceNamespace
    lock_type: LocksLockTypeNamespace
    acquired_at: LocksAcquiredAtNamespace
    expires_at: LocksExpiresAtNamespace
    holder: LocksHolderNamespace
    status: LocksStatusNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
