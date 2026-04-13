from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol, GetOneProtocol

@runtime_checkable
class WorkerClaimsFileIdNamespace(Protocol):
    get: GetOneProtocol

    def delete(self, value: str) -> int: ...

@runtime_checkable
class WorkerClaimsWorkerIdNamespace(Protocol):
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
class WorkerClaimsNamespace(Protocol):
    get: CollectionGetProtocol
    file_id: WorkerClaimsFileIdNamespace
    worker_id: WorkerClaimsWorkerIdNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
