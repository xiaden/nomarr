"""Map calibration storage records to domain value objects."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState

if TYPE_CHECKING:
    from nomarr.helpers.dto.calibration_repo_dto import CalibrationStateRecord


def _state_from_data(
    model_id: str, state_data: dict[str, Any], updated_at: int | None = None, **extra: Any
) -> CalibrationState:
    """Build a domain state from the JSONB payload and persistence metadata."""
    return CalibrationState(
        model_id=model_id,
        head_name=str(state_data.get("head_name", "")),
        label=str(state_data.get("label", "")),
        calibration_def_hash=str(state_data.get("calibration_def_hash", "")),
        histogram=state_data.get("histogram", {}),
        histogram_bins=state_data.get("histogram_bins"),
        p5=float(state_data.get("p5", 0.0)),
        p95=float(state_data.get("p95", 1.0)),
        sample_count=int(state_data.get("n", state_data.get("sample_count", 0))),
        underflow_count=int(state_data.get("underflow_count", 0)),
        overflow_count=int(state_data.get("overflow_count", 0)),
        updated_at=updated_at,
        backbone_id=extra.get("backbone_id"),
    )


def calibration_state_from_record(record: CalibrationStateRecord) -> CalibrationState:
    """Map a repository row DTO without exposing its row identity."""
    return _state_from_data(record["model_id"], record["state_data"], record["updated_at"])


def calibration_state_from_joined_record(record: dict[str, Any]) -> CalibrationState:
    """Map a repository join result to the same domain contract."""
    return _state_from_data(
        record["model_id"],
        record["state_data"],
        record.get("updated_at"),
        backbone_id=record.get("backbone_id"),
    )


def calibration_state_payload(state: CalibrationState) -> dict[str, Any]:
    """Encode domain calibration semantics for the repository JSONB column."""
    return {
        "head_name": state.head_name,
        "label": state.label,
        "calibration_def_hash": state.calibration_def_hash,
        "histogram": state.histogram,
        "histogram_bins": state.histogram_bins,
        "p5": state.p5,
        "p95": state.p95,
        "n": state.sample_count,
        "underflow_count": state.underflow_count,
        "overflow_count": state.overflow_count,
    }


__all__ = ["calibration_state_from_joined_record", "calibration_state_from_record", "calibration_state_payload"]
