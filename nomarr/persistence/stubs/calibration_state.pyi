from __future__ import annotations

from typing import Protocol, runtime_checkable

from ._base import TraversalVerbProtocol

@runtime_checkable
class CalibrationStateNamespace(Protocol):
    model_has_calibration: TraversalVerbProtocol
