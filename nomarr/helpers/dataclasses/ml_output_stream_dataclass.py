"""Domain value objects for persisted ML output activation streams.

These types are the contract at the ML persistence intent boundary.  They carry
only the stable output identity and activation data; song identifiers and row
metadata remain persistence concerns.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OutputStreamWrite:
    """Command to replace one model output's activation stream."""

    output_id: str
    values: list[float]
    output_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, str) or not self.output_id.strip():
            raise ValueError("OutputStreamWrite.output_id must not be blank")
        if not isinstance(self.values, list):
            raise TypeError("OutputStreamWrite.values must be a list")
        if self.output_index is not None and not isinstance(self.output_index, int):
            raise TypeError("OutputStreamWrite.output_index must be an int or None")
        object.__setattr__(self, "values", [float(value) for value in self.values])


@dataclass(frozen=True, slots=True)
class OutputStream:
    """Persisted activation stream exposed by the ML intent facade.

    ``output_index`` is optional because legacy rows may not have an index.  The
    storage row id, song foreign key, and timestamp are intentionally omitted.
    """

    output_id: str
    values: list[float]
    output_index: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.output_id, str) or not self.output_id.strip():
            raise ValueError("OutputStream.output_id must not be blank")
        if not isinstance(self.values, list):
            raise TypeError("OutputStream.values must be a list")
        if self.output_index is not None and not isinstance(self.output_index, int):
            raise TypeError("OutputStream.output_index must be an int or None")
        object.__setattr__(self, "values", [float(value) for value in self.values])


__all__ = ["OutputStream", "OutputStreamWrite"]
