from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from ._base import (
    CollectionGetVerbProtocol,
    DeleteWithCascadeProtocol,
    FieldAccessorProtocol,
    TraversalVerbProtocol,
)

@runtime_checkable
class MlModelsNamespace(Protocol):
    get: CollectionGetVerbProtocol
    delete: DeleteWithCascadeProtocol
    truncate: Callable[[], None]
    def insert(self, docs: list[dict[str, Any]]) -> list[str]: ...
    def count(self, *args: Any, **kwargs: Any) -> int: ...
    def update(self, *args: Any, **kwargs: Any) -> None: ...
    def upsert(self, *args: Any, **kwargs: Any) -> list[str]: ...
    def update_many(self, docs: list[dict[str, Any]]) -> None: ...
    def upsert_batch(self, docs: list[dict[str, Any]], match_fields: str | list[str]) -> list[str]: ...
    def aggregate(self, *args: Any, **kwargs: Any) -> list[Any]: ...
    model_has_output: TraversalVerbProtocol
    model_has_calibration: TraversalVerbProtocol
    path: FieldAccessorProtocol
    backbone: FieldAccessorProtocol
    head_type: FieldAccessorProtocol
    model_stem: FieldAccessorProtocol
    output_count: FieldAccessorProtocol
    fully_configured: FieldAccessorProtocol
    is_known: FieldAccessorProtocol
    source: FieldAccessorProtocol
    head_release_date: FieldAccessorProtocol
    embedder_release_date: FieldAccessorProtocol
    registered_at: FieldAccessorProtocol
    updated_at: FieldAccessorProtocol
