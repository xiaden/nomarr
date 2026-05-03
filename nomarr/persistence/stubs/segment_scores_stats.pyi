from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    AggResult,
    CollectionGetProtocol,
    GetModifierProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class SegmentScoresStatsUniqueGetUpsertNamespace(Protocol):
    get: UniqueGetModifierProtocol
    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class SegmentScoresStatsUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class SegmentScoresStatsGetCollectUpdateNamespace(Protocol):
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
class SegmentScoresStatsGetAggregateUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def aggregate(
        self,
        *,
        filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[AggResult]: ...
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class SegmentScoresStatsGetUpdateNamespace(Protocol):
    get: GetModifierProtocol
    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class SegmentScoresStatsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: SegmentScoresStatsUniqueGetUpsertNamespace
    _id: SegmentScoresStatsUniqueGetOnlyNamespace
    head_name: SegmentScoresStatsGetCollectUpdateNamespace
    tagger_version: SegmentScoresStatsGetCollectUpdateNamespace
    num_segments: SegmentScoresStatsGetAggregateUpdateNamespace
    pooling_strategy: SegmentScoresStatsGetCollectUpdateNamespace
    label_stats: SegmentScoresStatsGetUpdateNamespace
    processed_at: SegmentScoresStatsGetUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
