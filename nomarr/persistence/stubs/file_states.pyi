from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from nomarr.persistence.stubs._base import CollectionGetProtocol, GetModifierProtocol

@runtime_checkable
class FileStatesIdNamespace(Protocol):
    get: GetModifierProtocol

@runtime_checkable
class FileStatesNamespace(Protocol):
    get: CollectionGetProtocol
    _key: FileStatesIdNamespace
    _id: FileStatesIdNamespace

    def count(self) -> int: ...
    def count_by_filter(self, filter_dict: dict[str, Any]) -> int: ...
    def transition(self, ids: list[str], from_edge_target: str, to_edge_target: str) -> None: ...
    def traversal(
        self,
        start: str | dict[str, Any],
        edge: str,
        *,
        target_filter: dict[str, Any] | None = ...,
        limit: int | None = ...,
        offset: int = ...,
    ) -> list[dict[str, Any]]: ...
