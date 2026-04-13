from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import AggResult, CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class LibraryPipelineStatesLibraryKeyNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...
    def delete(self, value: str) -> int: ...

@runtime_checkable
class LibraryPipelineStatesPipelineStateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...
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
class LibraryPipelineStatesNamespace(Protocol):
    get: CollectionGetProtocol
    library_key: LibraryPipelineStatesLibraryKeyNamespace
    pipeline_state: LibraryPipelineStatesPipelineStateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
