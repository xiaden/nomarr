from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import AggResult, CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class MlModelsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MlModelsCollectNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class MlModelsUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlModelsCollectUpdateNamespace(Protocol):
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
class MlModelsAggregateUpdateNamespace(Protocol):
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
class MlModelsPathNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class MlModelsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: MlModelsGetOnlyNamespace
    _id: MlModelsCollectNamespace
    path: MlModelsPathNamespace
    backbone: MlModelsCollectUpdateNamespace
    head_type: MlModelsCollectUpdateNamespace
    model_stem: MlModelsCollectUpdateNamespace
    output_count: MlModelsUpdateNamespace
    fully_configured: MlModelsAggregateUpdateNamespace
    is_known: MlModelsAggregateUpdateNamespace
    source: MlModelsCollectUpdateNamespace
    head_release_date: MlModelsUpdateNamespace
    embedder_release_date: MlModelsUpdateNamespace
    registered_at: MlModelsGetOnlyNamespace
    updated_at: MlModelsUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def cascade(self, ids: list[str]) -> int: ...
    def traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
