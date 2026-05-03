from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    DeleteModifierProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class MetaUniqueGetCollectDeleteUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    delete: DeleteModifierProtocol
    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class MetaGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class MetaNamespace(Protocol):
    get: CollectionGetProtocol
    key: MetaUniqueGetCollectDeleteUpsertNamespace
    value: MetaGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
