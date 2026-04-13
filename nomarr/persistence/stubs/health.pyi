from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class HealthKeyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class HealthIdNamespace(Protocol):
    get: GetModifierProtocol

    def collect(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[Any]: ...

@runtime_checkable
class HealthComponentIdNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...
    def update(self, match_value: str, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class HealthComponentTypeNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class HealthNamespace(Protocol):
    get: CollectionGetProtocol
    _key: HealthKeyNamespace
    _id: HealthIdNamespace
    component_id: HealthComponentIdNamespace
    component_type: HealthComponentTypeNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
