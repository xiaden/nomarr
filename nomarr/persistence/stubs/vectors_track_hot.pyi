from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class VectorsTrackHotNamespace(Protocol):
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
    def upsert_vector(
        self,
        file_id: str,
        model_suite_hash: str,
        embed_dim: int,
        vector: list[float],
        num_segments: int,
    ) -> None: ...
    def move_collection(self, dest: str) -> int: ...
