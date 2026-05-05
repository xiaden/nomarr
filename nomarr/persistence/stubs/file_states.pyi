from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import TraversalVerbProtocol

@runtime_checkable
class FileStatesNamespace(Protocol):
    file_has_state: TraversalVerbProtocol
    def transition(self, file_ids: list[str], from_state: str, to_state: str) -> None: ...
