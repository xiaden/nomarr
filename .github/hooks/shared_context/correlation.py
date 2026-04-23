"""Exact correlation helpers for shared-context hook lifecycle events."""

from __future__ import annotations

from typing import cast

from .context_tools import (
    _append_malformed_event,
    _append_record,
    _build_journal_state,
    _normalize_json_value,
    _normalize_lineage,
    _normalize_non_empty_string,
    context_read,
)
from .normalizer import JSONValue
from .storage import SessionStorage


def _pending_path_fragment(correlation_id: str) -> str:
    """Return the canonical relative pending-envelope path fragment."""

    return f"envelopes/pending/{correlation_id}.json"


def _normalize_effective_item_ids(value: object) -> list[str] | None:
    """Normalize a pending envelope item-id list."""

    if not isinstance(value, list):
        return None

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in value:
        normalized = _normalize_non_empty_string(raw_value)
        if normalized is None:
            return None
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _load_pending_envelopes(storage: SessionStorage) -> list[dict[str, object]]:
    """Read all pending envelopes in deterministic file-id order."""

    envelopes: list[dict[str, object]] = []
    for correlation_id in storage.list_pending_envelope_ids():
        envelope = storage.read_pending_envelope(correlation_id)
        if envelope is None:
            continue
        envelopes.append(envelope)
    return envelopes


def correlate_subagent_start(
    storage: SessionStorage,
    subagent_session_id: str,
    subagent_agent_id: str,
) -> dict:
    """Activate the exact pending envelope for a matching ``SubagentStart`` event.

    Matches by exact pair: ``pending.session_id == subagent_session_id`` and
    ``pending.correlation_id == subagent_agent_id``. When multiple pending
    envelopes match (duplicate hook deliveries), the one with the smallest
    ``created_journal_seq`` wins and the others are logged as duplicates.

    This function is idempotent: if an active envelope already exists for
    ``subagent_agent_id`` it returns ``status="duplicate"`` without re-writing
    state.

    After activation, writes:
    - a ``spawn_activated`` journal record.
    - an immutable active envelope keyed by ``subagent_agent_id``.
    - ``context_item_consumed`` records for each reserved ``next_child`` item.

    Args:
        storage: The session storage for the current session.
        subagent_session_id: Non-empty session id from the ``SubagentStart``
            event payload.
        subagent_agent_id: Non-empty agent id from the ``SubagentStart``
            event payload; also used as the correlation key.

    Returns:
        A dict with keys:
        - ``status`` (str): ``"activated"`` on success, ``"duplicate"`` when
          an active envelope already existed, ``"no_match"`` when no valid
          pending envelope could be found.
        - ``active_envelope`` (dict): present for ``activated`` and
          ``duplicate`` statuses; the immutable envelope that was written or
          already existed.

    Raises:
        ValueError: If ``subagent_session_id`` or ``subagent_agent_id`` are
            empty.
    """

    normalized_session_id = _normalize_non_empty_string(subagent_session_id)
    normalized_agent_id = _normalize_non_empty_string(subagent_agent_id)
    if normalized_session_id is None or normalized_agent_id is None:
        raise ValueError("subagent_session_id and subagent_agent_id must be non-empty strings.")

    pending_matches: list[dict[str, object]] = []
    for envelope in _load_pending_envelopes(storage):
        session_id = _normalize_non_empty_string(envelope.get("session_id"))
        correlation_id = _normalize_non_empty_string(envelope.get("correlation_id"))
        if session_id == normalized_session_id and correlation_id == normalized_agent_id:
            pending_matches.append(envelope)

    if not pending_matches:
        _append_record(
            storage,
            record_type="orphaned_pending_envelope",
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            payload={
                "agent_id": normalized_agent_id,
                "reason": "no_exact_pending_match",
                "session_id": normalized_session_id,
            },
        )
        return {"status": "no_match"}

    existing_active = storage.read_active_envelope(normalized_agent_id)
    if existing_active is not None:
        _append_record(
            storage,
            record_type="duplicate_event_ignored",
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            payload={
                "agent_id": normalized_agent_id,
                "reason": "active_envelope_already_exists",
                "session_id": normalized_session_id,
            },
        )
        return {"active_envelope": existing_active, "status": "duplicate"}

    def _created_seq(envelope: dict[str, object]) -> int:
        created = envelope.get("created_journal_seq")
        return created if isinstance(created, int) else -1

    if any(_created_seq(envelope) < 0 for envelope in pending_matches):
        _append_malformed_event(
            storage,
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            reason="pending_envelope_missing_created_journal_seq",
            details={"agent_id": normalized_agent_id},
        )
        return {"status": "no_match"}

    chosen_pending = min(pending_matches, key=_created_seq)
    duplicate_pendings = [
        envelope for envelope in pending_matches if envelope is not chosen_pending and _created_seq(envelope) >= 0
    ]
    for duplicate in duplicate_pendings:
        duplicate_correlation_id = _normalize_non_empty_string(duplicate.get("correlation_id"))
        _append_record(
            storage,
            record_type="duplicate_event_ignored",
            agent_id=normalized_agent_id,
            correlation_id=duplicate_correlation_id,
            payload={
                "agent_id": normalized_agent_id,
                "reason": "duplicate_pending_envelope",
                "session_id": normalized_session_id,
                "winning_created_journal_seq": _created_seq(chosen_pending),
            },
        )

    parent_agent_id = _normalize_non_empty_string(chosen_pending.get("parent_agent_id"))
    raw_parent_lineage = chosen_pending.get("parent_lineage")
    if not isinstance(raw_parent_lineage, list):
        _append_malformed_event(
            storage,
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            reason="pending_envelope_parent_lineage_invalid",
            details={"agent_id": normalized_agent_id},
        )
        return {"status": "no_match"}
    parent_lineage = _normalize_lineage(cast("list[str]", raw_parent_lineage))
    effective_item_ids = _normalize_effective_item_ids(chosen_pending.get("eligible_item_ids"))
    reserved_item_ids = _normalize_effective_item_ids(chosen_pending.get("reserved_next_child_item_ids"))
    correlation_id = _normalize_non_empty_string(chosen_pending.get("correlation_id"))
    if parent_agent_id is None or effective_item_ids is None or reserved_item_ids is None or correlation_id is None:
        _append_malformed_event(
            storage,
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            reason="pending_envelope_missing_required_fields",
            details={"agent_id": normalized_agent_id},
        )
        return {"status": "no_match"}

    activation_record = storage.append_journal_record(
        record_type="spawn_activated",
        agent_id=normalized_agent_id,
        correlation_id=correlation_id,
        payload={
            "activated_from": _pending_path_fragment(correlation_id),
            "agent_id": normalized_agent_id,
            "effective_item_ids": cast("JSONValue", effective_item_ids),
            "parent_agent_id": parent_agent_id,
        },
    )
    active_envelope = {
        "activated_at": activation_record["timestamp"],
        "activated_from": _pending_path_fragment(correlation_id),
        "activated_journal_seq": activation_record["journal_seq"],
        "agent_id": normalized_agent_id,
        "child_lineage": [*parent_lineage, parent_agent_id, normalized_agent_id],
        "correlation_id": correlation_id,
        "effective_item_ids": effective_item_ids,
        "parent_agent_id": parent_agent_id,
        "schema_version": 1,
        "session_id": normalized_session_id,
    }

    try:
        storage.write_active_envelope(normalized_agent_id, active_envelope)
    except FileExistsError:
        existing_raced_active = storage.read_active_envelope(normalized_agent_id)
        _append_record(
            storage,
            record_type="duplicate_event_ignored",
            agent_id=normalized_agent_id,
            correlation_id=normalized_agent_id,
            payload={
                "agent_id": normalized_agent_id,
                "reason": "active_envelope_race",
                "session_id": normalized_session_id,
            },
        )
        return {
            "active_envelope": existing_raced_active if existing_raced_active is not None else active_envelope,
            "status": "duplicate",
        }

    for item_id in reserved_item_ids:
        _append_record(
            storage,
            record_type="context_item_consumed",
            agent_id=normalized_agent_id,
            correlation_id=correlation_id,
            payload={
                "item_id": item_id,
                "reserved_for": correlation_id,
            },
        )

    return {"active_envelope": active_envelope, "status": "activated"}


def capture_pretooluse_spawn(
    storage: SessionStorage,
    session_id: str,
    tool_use_id: str,
    parent_agent_id: str,
    parent_lineage: list[str],
    tool_input_summary: dict,
    transcript_path: str,
    cwd: str,
) -> dict:
    """Freeze the authoritative pending envelope for a ``runSubagent`` spawn.

    Reads the current context snapshot from the parent agent's perspective,
    separates sticky items (inherit by reference) from ``next_child`` items
    (consume on first use), writes reservation journal records for ``next_child``
    items, then writes an immutable pending envelope keyed by ``tool_use_id``.

    This function is idempotent: if a pending envelope already exists for
    ``tool_use_id`` it returns ``status="duplicate"`` without re-writing state.

    Args:
        storage: The session storage for the current session.
        session_id: Non-empty session identifier.
        tool_use_id: Non-empty tool-use id from the ``PreToolUse`` event;
            used as the correlation key between this capture and the
            subsequent ``SubagentStart`` activation.
        parent_agent_id: Non-empty identifier of the spawning agent.
        parent_lineage: Ordered list of ancestor agent ids for the parent.
        tool_input_summary: Bounded metadata extracted from ``tool_input``;
            persisted with the envelope for debugging (not the full prompt).
        transcript_path: Path to the current agent's transcript file.
        cwd: Working directory at spawn time.

    Returns:
        A dict with keys:
        - ``status`` (str): ``"pending_created"`` on success, ``"duplicate"``
          when the envelope already existed, ``"no_match"`` on validation
          failure.
        - ``correlation_id`` (str): present for ``pending_created`` and
          ``duplicate`` statuses; equals ``tool_use_id``.
        - ``pending_envelope`` (dict): present for ``pending_created`` and
          ``duplicate`` statuses; the immutable envelope that was written or
          already existed.

    Raises:
        ValueError: If any of the required non-empty string arguments are
            empty or ``None``.
    """

    normalized_session_id = _normalize_non_empty_string(session_id)
    normalized_tool_use_id = _normalize_non_empty_string(tool_use_id)
    normalized_parent_agent_id = _normalize_non_empty_string(parent_agent_id)
    normalized_parent_lineage = _normalize_lineage(parent_lineage)
    normalized_transcript_path = _normalize_non_empty_string(transcript_path)
    normalized_cwd = _normalize_non_empty_string(cwd)
    if (
        normalized_session_id is None
        or normalized_tool_use_id is None
        or normalized_parent_agent_id is None
        or normalized_transcript_path is None
        or normalized_cwd is None
    ):
        raise ValueError(
            "session_id, tool_use_id, parent_agent_id, transcript_path, and cwd must be non-empty strings."
        )

    existing_pending = storage.read_pending_envelope(normalized_tool_use_id)
    if existing_pending is not None:
        _append_record(
            storage,
            record_type="duplicate_event_ignored",
            agent_id=normalized_parent_agent_id,
            correlation_id=normalized_tool_use_id,
            payload={
                "correlation_id": normalized_tool_use_id,
                "reason": "pending_envelope_already_exists",
                "session_id": normalized_session_id,
            },
        )
        return {
            "correlation_id": normalized_tool_use_id,
            "pending_envelope": existing_pending,
            "status": "duplicate",
        }

    context_snapshot = context_read(
        storage,
        current_agent_id=normalized_parent_agent_id,
        current_lineage=normalized_parent_lineage,
        include_self_owned=True,
    )
    snapshot_items = context_snapshot.get("items", [])
    if not isinstance(snapshot_items, list):
        _append_malformed_event(
            storage,
            agent_id=normalized_parent_agent_id,
            correlation_id=normalized_tool_use_id,
            reason="context_read_items_not_list",
        )
        return {"status": "no_match"}

    journal_state = _build_journal_state(storage)
    eligible_item_ids: list[str] = []
    reserved_next_child_item_ids: list[str] = []
    for raw_item in snapshot_items:
        if not isinstance(raw_item, dict):
            continue
        item_id = _normalize_non_empty_string(raw_item.get("item_id"))
        owner_agent = _normalize_non_empty_string(raw_item.get("owner_agent_id"))
        delivery = _normalize_non_empty_string(raw_item.get("delivery"))
        if item_id is None or owner_agent is None or delivery is None:
            continue
        if item_id not in journal_state.items_by_id:
            continue
        if delivery == "sticky":
            eligible_item_ids.append(item_id)
        elif delivery == "next_child" and owner_agent == normalized_parent_agent_id:
            eligible_item_ids.append(item_id)
            reserved_next_child_item_ids.append(item_id)

    for item_id in reserved_next_child_item_ids:
        _append_record(
            storage,
            record_type="next_child_reserved",
            agent_id=normalized_parent_agent_id,
            correlation_id=normalized_tool_use_id,
            payload={
                "item_id": item_id,
                "owner_agent_id": normalized_parent_agent_id,
            },
        )

    normalized_tool_input_summary = _normalize_json_value(cast("dict[str, object]", tool_input_summary))
    if not isinstance(normalized_tool_input_summary, dict):
        _append_malformed_event(
            storage,
            agent_id=normalized_parent_agent_id,
            correlation_id=normalized_tool_use_id,
            reason="tool_input_summary_not_object",
        )
        return {"status": "no_match"}

    pending_record = storage.append_journal_record(
        record_type="spawn_pending_written",
        agent_id=normalized_parent_agent_id,
        correlation_id=normalized_tool_use_id,
        payload={
            "eligible_item_ids": cast("JSONValue", eligible_item_ids),
            "pending_envelope_path": _pending_path_fragment(normalized_tool_use_id),
            "reserved_next_child_item_ids": cast("JSONValue", reserved_next_child_item_ids),
        },
    )
    pending_envelope = {
        "correlation_id": normalized_tool_use_id,
        "created_at": pending_record["timestamp"],
        "created_journal_seq": pending_record["journal_seq"],
        "cwd": normalized_cwd,
        "eligible_item_ids": eligible_item_ids,
        "hook_event_name": "PreToolUse",
        "parent_agent_id": normalized_parent_agent_id,
        "parent_lineage": normalized_parent_lineage,
        "reserved_next_child_item_ids": reserved_next_child_item_ids,
        "schema_version": 1,
        "session_id": normalized_session_id,
        "tool_input_summary": normalized_tool_input_summary,
        "tool_name": "runSubagent",
        "transcript_path": normalized_transcript_path,
    }

    try:
        storage.write_pending_envelope(normalized_tool_use_id, pending_envelope)
    except FileExistsError:
        existing_raced_pending = storage.read_pending_envelope(normalized_tool_use_id)
        _append_record(
            storage,
            record_type="duplicate_event_ignored",
            agent_id=normalized_parent_agent_id,
            correlation_id=normalized_tool_use_id,
            payload={
                "correlation_id": normalized_tool_use_id,
                "reason": "pending_envelope_race",
                "session_id": normalized_session_id,
            },
        )
        return {
            "correlation_id": normalized_tool_use_id,
            "pending_envelope": existing_raced_pending if existing_raced_pending is not None else pending_envelope,
            "status": "duplicate",
        }

    return {
        "correlation_id": normalized_tool_use_id,
        "pending_envelope": pending_envelope,
        "status": "pending_created",
    }


__all__ = ["capture_pretooluse_spawn", "correlate_subagent_start"]
