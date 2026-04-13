from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import AggResult, CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class MlModelOutputsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class MlModelOutputsKeyNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MlModelOutputsCollectUpdateNamespace(Protocol):
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
class MlModelOutputsAggregateUpdateNamespace(Protocol):
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
class MlModelOutputsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: MlModelOutputsKeyNamespace
    _id: MlModelOutputsGetOnlyNamespace
    output_index: MlModelOutputsCollectUpdateNamespace
    label: MlModelOutputsCollectUpdateNamespace
    fully_labeled: MlModelOutputsAggregateUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def cascade(self, ids: list[str]) -> int: ...
