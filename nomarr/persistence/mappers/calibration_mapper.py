"""Map calibration storage records to domain value objects.

This module is the persistence layer's row↔domain conversion point for
calibration state and history (ADR-032/040/046, ASR-0013/0014): event/data
envelopes, JSONB internals, integer row ids, and generated timestamps never
surface above here.  The two public state converters
(:func:`calibration_state_from_record`,
:func:`calibration_state_from_joined_record`) and the state persistence
payload builder (:func:`calibration_state_payload`) are consumed by
``ml.py``.  The history builders/converter
(:func:`calibration_history_payload`,
:func:`calibration_history_from_record`) back the natural-identity snapshot
intents that Plan C's facade will call.

Epoch-millisecond handling: ``updated_at``/``created_at`` are integer
milliseconds since epoch (project convention ``now_ms().value``) — never
seconds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.helpers.dataclasses.calibration_history_dataclass import CalibrationHistorySnapshot
from nomarr.helpers.dataclasses.calibration_state_dataclass import CalibrationState

if TYPE_CHECKING:
    from nomarr.helpers.dto.calibration_repo_dto import CalibrationHistoryRecord, CalibrationStateRecord


def _state_from_data(model_id: str, state_data: dict[str, Any], updated_at: int | None = None) -> CalibrationState:
    """Build a domain state from the JSONB payload and persistence metadata.

    ``sample_count`` round-trips through the ``"n"`` key in the JSONB envelope
    (the repo's internal key for the count); ``sample_count`` is read back via
    ``state_data.get("n", state_data.get("sample_count", 0))`` for tolerance of
    either spelling.
    """
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
    )


def calibration_state_from_record(record: CalibrationStateRecord) -> CalibrationState:
    """Map a repository row DTO without exposing its row identity."""
    return _state_from_data(record["model_id"], record["state_data"], record["updated_at"])


def calibration_state_from_joined_record(record: dict[str, Any]) -> CalibrationState:
    """Map a repository join result to the same domain contract.

    The joined record carries extra model metadata (including ``backbone_id``)
    for ``RegisteredModel`` construction in Plan C; the mapper reads only the
    calibration state fields and never forwards ``backbone_id`` (or any model
    metadata) into :class:`CalibrationState` — the domain value has no such
    field.
    """
    return _state_from_data(
        record["model_id"],
        record["state_data"],
        record.get("updated_at"),
    )


def calibration_state_payload(state: CalibrationState) -> dict[str, Any]:
    """Encode domain calibration semantics for the repository JSONB column.

    Produces the exact internal envelope keys the repo/``state_data`` contract
    uses: ``head_name``, ``label``, ``calibration_def_hash``, ``histogram``,
    ``histogram_bins``, ``p5``, ``p95``, ``"n"`` (the repo's internal key for
    ``sample_count``), ``underflow_count``, ``overflow_count``.
    """
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


def calibration_history_payload(snapshot: CalibrationHistorySnapshot) -> dict[str, Any]:
    """Encode a domain snapshot into the metrics dict consumed by the repository.

    Produces the internal metrics payload for
    ``CalibrationRepo.add_calibration_history_snapshot(model_id, head_name,
    label, snapshot_at, metrics)``.  The repository builds the storage ``data``
    envelope itself (injecting ``head_name``/``label`` and the stable
    ``event``), so this payload carries only the named snapshot metrics:
    ``p5``/``p95``, ``sample_count``/``underflow_count``/``overflow_count``,
    the optional deltas (``p5_delta``/``p95_delta``/``n_delta``), and the
    optional stable ``output_id`` (string-only, forwarded verbatim, never
    int-encoded).  ``None`` deltas and ``output_id`` are omitted so the
    envelope stays free of spurious null keys.
    """
    payload: dict[str, Any] = {
        "p5": snapshot.p5,
        "p95": snapshot.p95,
        "sample_count": snapshot.sample_count,
        "underflow_count": snapshot.underflow_count,
        "overflow_count": snapshot.overflow_count,
    }
    if snapshot.p5_delta is not None:
        payload["p5_delta"] = snapshot.p5_delta
    if snapshot.p95_delta is not None:
        payload["p95_delta"] = snapshot.p95_delta
    if snapshot.n_delta is not None:
        payload["n_delta"] = snapshot.n_delta
    if snapshot.output_id is not None:
        payload["output_id"] = snapshot.output_id
    return payload


def calibration_history_from_record(record: CalibrationHistoryRecord) -> CalibrationHistorySnapshot:
    """Map a repository history row DTO to the domain snapshot.

    ``head_name``/``label``/``output_id`` are read from the ``data`` envelope;
    ``snapshot_at`` maps from the ``created_at`` epoch-ms column (the same
    semantic instant).  Percentiles and deltas are coerced to ``float``, counts
    and ``n_delta`` to ``int``; absent deltas are ``None``.
    """
    data = record["data"]
    p5_delta = data.get("p5_delta")
    p95_delta = data.get("p95_delta")
    n_delta = data.get("n_delta")
    return CalibrationHistorySnapshot(
        model_id=record["model_id"],
        head_name=str(data.get("head_name", "")),
        label=str(data.get("label", "")),
        snapshot_at=record["created_at"],
        p5=float(data.get("p5", 0.0)),
        p95=float(data.get("p95", 0.0)),
        sample_count=int(data.get("sample_count", 0)),
        underflow_count=int(data.get("underflow_count", 0)),
        overflow_count=int(data.get("overflow_count", 0)),
        p5_delta=float(p5_delta) if p5_delta is not None else None,
        p95_delta=float(p95_delta) if p95_delta is not None else None,
        n_delta=int(n_delta) if n_delta is not None else None,
        output_id=data.get("output_id"),
    )


__all__ = [
    "calibration_history_from_record",
    "calibration_history_payload",
    "calibration_state_from_joined_record",
    "calibration_state_from_record",
    "calibration_state_payload",
]
