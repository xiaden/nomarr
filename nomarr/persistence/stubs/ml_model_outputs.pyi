from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import TraversalVerbProtocol

@runtime_checkable
class MlModelOutputsNamespace(Protocol):
    model_has_output: TraversalVerbProtocol
