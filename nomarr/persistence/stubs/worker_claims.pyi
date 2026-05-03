from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class WorkerClaimsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class WorkerClaimsUniqueGetDeleteNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol

@runtime_checkable
class WorkerClaimsGetCollectDeleteNamespace(Protocol):
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
class WorkerClaimsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class WorkerClaimsGetCollectNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class WorkerClaimsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: WorkerClaimsUniqueGetOnlyNamespace
    _id: WorkerClaimsUniqueGetOnlyNamespace
    file_id: WorkerClaimsUniqueGetDeleteNamespace
    worker_id: WorkerClaimsGetCollectDeleteNamespace
    claimed_at: WorkerClaimsGetOnlyNamespace
    claim_type: WorkerClaimsGetCollectNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
