from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    GetModifierProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class MlModelsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class MlModelsUniqueGetCollectNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class MlModelsUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class MlModelsGetCollectUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlModelsGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlModelsGetAggregateCollectUpdateNamespace(Protocol):
    get: GetModifierProtocol
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
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlModelsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MlModelsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: MlModelsUniqueGetOnlyNamespace
    _id: MlModelsUniqueGetCollectNamespace
    path: MlModelsUniqueGetUpsertNamespace
    backbone: MlModelsGetCollectUpdateNamespace
    head_type: MlModelsGetCollectUpdateNamespace
    model_stem: MlModelsGetCollectUpdateNamespace
    output_count: MlModelsGetUpdateNamespace
    fully_configured: MlModelsGetAggregateCollectUpdateNamespace
    is_known: MlModelsGetAggregateCollectUpdateNamespace
    source: MlModelsGetCollectUpdateNamespace
    head_release_date: MlModelsGetUpdateNamespace
    embedder_release_date: MlModelsGetUpdateNamespace
    registered_at: MlModelsGetOnlyNamespace
    updated_at: MlModelsGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    traversal: TraversalProtocol
