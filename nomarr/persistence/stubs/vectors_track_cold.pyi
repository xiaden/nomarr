from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class VectorsTrackColdNamespace(Protocol):
    def ann_search(
        self,
        query_vector: list[float],
        limit: int,
        nprobe: int,
        *,
        filter: dict[str, Any] | None = ...,
    ) -> list[dict[str, Any]]: ...
    def get_vector(self, file_id: str) -> dict[str, Any] | None: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
