from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import (
    CollectionGetProtocol,
    TraversalProtocol,
    UniqueGetModifierProtocol,
)

@runtime_checkable
class FileStatesUniqueGetOnlyNamespace(Protocol):
    get: UniqueGetModifierProtocol

@runtime_checkable
class FileStatesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: FileStatesUniqueGetOnlyNamespace
    _id: FileStatesUniqueGetOnlyNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None: ...
    traversal: TraversalProtocol
