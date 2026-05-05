from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import DeleteWithCascadeProtocol, TraversalVerbProtocol

@runtime_checkable
class MlModelsNamespace(Protocol):
    delete: DeleteWithCascadeProtocol
    model_has_output: TraversalVerbProtocol
    model_has_calibration: TraversalVerbProtocol
