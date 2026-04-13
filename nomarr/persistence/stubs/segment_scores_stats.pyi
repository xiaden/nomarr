from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import AggResult, CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class SegmentScoresStatsGetOnlyNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class SegmentScoresStatsKeyNamespace(Protocol):
    get: GetModifierProtocol

    def upsert(self, docs: list[dict[str, Any]], match_field: str | list[str]) -> list[str]: ...

@runtime_checkable
class SegmentScoresStatsCollectUpdateNamespace(Protocol):
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
class SegmentScoresStatsAggregateUpdateNamespace(Protocol):
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
class SegmentScoresStatsUpdateNamespace(Protocol):
    get: GetModifierProtocol

    def update(self, match_value: Any, fields: dict[str, Any]) -> None: ...

@runtime_checkable
class SegmentScoresStatsNamespace(Protocol):
    get: CollectionGetProtocol
    _key: SegmentScoresStatsKeyNamespace
    _id: SegmentScoresStatsGetOnlyNamespace
    head_name: SegmentScoresStatsCollectUpdateNamespace
    tagger_version: SegmentScoresStatsCollectUpdateNamespace
    num_segments: SegmentScoresStatsAggregateUpdateNamespace
    pooling_strategy: SegmentScoresStatsCollectUpdateNamespace
    label_stats: SegmentScoresStatsUpdateNamespace
    processed_at: SegmentScoresStatsUpdateNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def delete(self, ids: list[str]) -> None: ...
    def delete_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def update_by_filter(self, filter_dict: dict[str, Any], fields: dict[str, Any]) -> None: ...
    def cascade(self, ids: list[str]) -> int: ...
    def truncate(self) -> None: ...
