from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import cast

import pytest

HOOKS_DIR = Path(__file__).resolve().parents[1]
if str(HOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(HOOKS_DIR))

# ruff: noqa: E402
import shared_context.correlation as correlation_module
from shared_context.context_tools import context_add, context_read, context_shared
from shared_context.correlation import capture_pretooluse_spawn, correlate_subagent_start
from shared_context.normalizer import (
    JSONValue,
    extract_required,
    normalize_payload,
    normalize_required_pretooluse_fields,
    normalize_required_subagentstart_fields,
)
from shared_context.storage import SessionStorage, make_journal_record

_SESSION_COUNTER = count(1)


@pytest.fixture
def repo_root() -> Iterator[Path]:
    with TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


def _session_id(prefix: str) -> str:
    return f"{prefix}-{next(_SESSION_COUNTER):03d}"


def _storage(repo_root: Path, prefix: str) -> SessionStorage:
    return SessionStorage(session_id=_session_id(prefix), repo_root=repo_root)


def _journal_records(storage: SessionStorage, record_type: str) -> list[dict[str, object]]:
    return [record for record in storage.read_journal() if record.get("record_type") == record_type]


def _record_payload(record: dict[str, object]) -> dict[str, object]:
    payload = record.get("payload")
    assert isinstance(payload, dict)
    return payload


def _as_object_dict(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _as_string_list(value: object) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return list(value)


def _json_dict(**values: JSONValue) -> dict[str, JSONValue]:
    return values


def _capture_spawn(
    storage: SessionStorage,
    *,
    tool_use_id: str,
    parent_agent_id: str = "parent-agent",
    parent_lineage: list[str] | None = None,
    tool_input_summary: dict[str, object] | None = None,
) -> dict[str, object]:
    return capture_pretooluse_spawn(
        storage,
        session_id=storage.session_id,
        tool_use_id=tool_use_id,
        parent_agent_id=parent_agent_id,
        parent_lineage=parent_lineage or [],
        tool_input_summary=tool_input_summary or {"agentName": "Support-Researcher"},
        transcript_path="/tmp/transcript.jsonl",
        cwd="/tmp/workspace",
    )


# 1. Normalization tests


def test_normalization_snake_case_passthrough() -> None:
    payload: dict[str, object] = {
        "session_id": "session-001",
        "tool_use_id": "tool-001",
        "agent_id": "agent-001",
        "tool_name": "runSubagent",
        "tool_input": {"agent_name": "Support-Researcher"},
        "hook_event_name": "PreToolUse",
        "transcript_path": "/tmp/transcript.jsonl",
        "agent_type": "support",
    }

    normalized = normalize_payload(payload)

    assert normalized == payload


def test_normalization_camel_to_snake() -> None:
    payload: dict[str, object] = {
        "sessionId": "session-002",
        "toolUseId": "tool-002",
        "agentId": "agent-002",
        "toolName": "runSubagent",
        "toolInput": {"agentName": "Support-Researcher"},
        "hookEventName": "PreToolUse",
        "transcriptPath": "/tmp/transcript.jsonl",
        "agentType": "support",
    }

    normalized = normalize_payload(payload)

    assert normalized == {
        "session_id": "session-002",
        "tool_use_id": "tool-002",
        "agent_id": "agent-002",
        "tool_name": "runSubagent",
        "tool_input": {"agent_name": "Support-Researcher"},
        "hook_event_name": "PreToolUse",
        "transcript_path": "/tmp/transcript.jsonl",
        "agent_type": "support",
    }


def test_normalization_mixed_payload() -> None:
    payload: dict[str, object] = {
        "sessionId": "camel-session",
        "session_id": "snake-session",
        "toolUseId": "camel-tool",
        "tool_use_id": "snake-tool",
        "agentId": "camel-agent",
        "agent_id": "snake-agent",
        "toolName": "camel-name",
        "tool_name": "snake-name",
        "toolInput": {"agentName": "CamelAgent"},
        "tool_input": {"agent_name": "SnakeAgent"},
        "hookEventName": "CamelEvent",
        "hook_event_name": "SnakeEvent",
    }

    normalized = normalize_payload(payload)

    assert normalized == {
        "session_id": "snake-session",
        "tool_use_id": "snake-tool",
        "agent_id": "snake-agent",
        "tool_name": "snake-name",
        "tool_input": {"agent_name": "SnakeAgent"},
        "hook_event_name": "SnakeEvent",
    }


def test_normalization_tool_input_recursion() -> None:
    payload: dict[str, object] = {
        "toolInput": {
            "agentName": "Support-Researcher",
            "taskConfig": {
                "maxItems": 3,
                "childSteps": [{"stepName": "collectData"}],
            },
        }
    }

    normalized = normalize_payload(payload)

    assert normalized == {
        "tool_input": {
            "agent_name": "Support-Researcher",
            "task_config": {
                "max_items": 3,
                "child_steps": [{"step_name": "collectData"}],
            },
        }
    }


def test_extract_required_all_present() -> None:
    raw_payload: dict[str, object] = {
        "sessionId": "session-003",
        "toolUseId": "tool-003",
        "toolName": "runSubagent",
        "toolInput": {"agentName": "Support-Researcher"},
        "hookEventName": "PreToolUse",
    }
    payload = normalize_payload(raw_payload)

    extracted, missing = extract_required(
        payload,
        ["session_id", "tool_use_id", "tool_name", "tool_input", "hook_event_name"],
    )

    assert extracted == {
        "session_id": "session-003",
        "tool_use_id": "tool-003",
        "tool_name": "runSubagent",
        "tool_input": {"agent_name": "Support-Researcher"},
        "hook_event_name": "PreToolUse",
    }
    assert missing == []


def test_extract_required_partial_missing() -> None:
    raw_payload: dict[str, object] = {
        "sessionId": "session-004",
        "toolInput": {"agentName": "Support-Researcher"},
        "hookEventName": "PreToolUse",
    }
    payload = normalize_payload(raw_payload)

    extracted, missing = extract_required(
        payload,
        ["session_id", "tool_use_id", "tool_name", "tool_input", "hook_event_name"],
    )

    assert extracted == {
        "session_id": "session-004",
        "tool_input": {"agent_name": "Support-Researcher"},
        "hook_event_name": "PreToolUse",
    }
    assert missing == ["tool_use_id", "tool_name"]


# 2. Storage round-trip tests


def test_journal_append_and_read(repo_root: Path) -> None:
    storage = _storage(repo_root, "journal-roundtrip")
    record = make_journal_record(
        record_type="context_item_written",
        session_id=storage.session_id,
        journal_seq=1,
        agent_id="agent-a",
        correlation_id="corr-a",
        payload=_json_dict(item_id="ctx_001", delivery="sticky"),
    )

    storage.append_journal(cast("dict[str, object]", record))

    assert storage.read_journal() == [record]


def test_journal_lf_only(repo_root: Path) -> None:
    storage = _storage(repo_root, "journal-lf")
    record = make_journal_record(
        record_type="context_item_written",
        session_id=storage.session_id,
        journal_seq=1,
        agent_id="agent-a",
        correlation_id=None,
        payload=_json_dict(item_id="ctx_002", delivery="sticky"),
    )

    storage.append_journal(cast("dict[str, object]", record))
    raw_bytes = storage.journal_path.read_bytes()

    assert b"\r" not in raw_bytes
    assert raw_bytes.endswith(b"\n")


def test_journal_monotonic_seq(repo_root: Path) -> None:
    storage = _storage(repo_root, "journal-seq")
    written_seqs: list[int] = []
    for item_index in range(3):
        record = storage.append_journal_record(
            record_type="context_item_written",
            agent_id="agent-a",
            correlation_id=None,
            payload=_json_dict(item_id=f"ctx_seq_{item_index}", delivery="sticky"),
        )
        written_seqs.append(record["journal_seq"])

    assert written_seqs == [1, 2, 3]
    assert [record["journal_seq"] for record in storage.read_journal()] == [1, 2, 3]


def test_journal_malformed_line_skip(repo_root: Path) -> None:
    storage = _storage(repo_root, "journal-malformed")
    first_record = make_journal_record(
        record_type="context_item_written",
        session_id=storage.session_id,
        journal_seq=1,
        agent_id="agent-a",
        correlation_id=None,
        payload=_json_dict(item_id="ctx_first", delivery="sticky"),
    )
    second_record = make_journal_record(
        record_type="context_item_written",
        session_id=storage.session_id,
        journal_seq=2,
        agent_id="agent-b",
        correlation_id=None,
        payload=_json_dict(item_id="ctx_second", delivery="sticky"),
    )
    storage.append_journal(cast("dict[str, object]", first_record))

    with storage.journal_path.open("ab") as handle:
        handle.write(b"this is not json\n")
        handle.write(json.dumps(second_record, ensure_ascii=False, sort_keys=True).encode("utf-8") + b"\n")

    assert storage.read_journal() == [first_record, second_record]


def test_pending_envelope_write_read(repo_root: Path) -> None:
    storage = _storage(repo_root, "pending-roundtrip")
    envelope = {"correlation_id": "tool-001", "session_id": storage.session_id, "schema_version": 1}

    storage.write_pending_envelope("tool-001", envelope)

    assert storage.read_pending_envelope("tool-001") == envelope


def test_pending_envelope_write_once(repo_root: Path) -> None:
    storage = _storage(repo_root, "pending-once")
    envelope = {"correlation_id": "tool-002", "session_id": storage.session_id, "schema_version": 1}

    storage.write_pending_envelope("tool-002", envelope)

    with pytest.raises(FileExistsError):
        storage.write_pending_envelope("tool-002", envelope)


def test_active_envelope_write_read(repo_root: Path) -> None:
    storage = _storage(repo_root, "active-roundtrip")
    envelope = {"agent_id": "agent-child", "session_id": storage.session_id, "schema_version": 1}

    storage.write_active_envelope("agent-child", envelope)

    assert storage.read_active_envelope("agent-child") == envelope


def test_active_envelope_write_once(repo_root: Path) -> None:
    storage = _storage(repo_root, "active-once")
    envelope = {"agent_id": "agent-child", "session_id": storage.session_id, "schema_version": 1}

    storage.write_active_envelope("agent-child", envelope)

    with pytest.raises(FileExistsError):
        storage.write_active_envelope("agent-child", envelope)


def test_make_journal_record_schema(repo_root: Path) -> None:
    storage = _storage(repo_root, "journal-schema")
    record = make_journal_record(
        record_type="spawn_pending_written",
        session_id=storage.session_id,
        journal_seq=7,
        agent_id="agent-a",
        correlation_id="corr-007",
        payload=_json_dict(eligible_item_ids=cast("JSONValue", ["ctx_007"])),
    )

    assert set(record) == {
        "agent_id",
        "correlation_id",
        "journal_seq",
        "payload",
        "record_type",
        "session_id",
        "timestamp",
    }
    assert record["record_type"] == "spawn_pending_written"
    assert record["journal_seq"] == 7
    assert record["session_id"] == storage.session_id
    assert record["agent_id"] == "agent-a"
    assert record["correlation_id"] == "corr-007"
    assert record["payload"] == {"eligible_item_ids": ["ctx_007"]}
    assert isinstance(record["timestamp"], str)
    assert record["timestamp"].endswith("Z")


# 3. Context tool tests


def test_context_shared_writes_sticky_record(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-shared")

    context_shared(storage, "parent-a", [], "note", {"value": "sticky"})

    records = _journal_records(storage, "context_item_written")
    assert len(records) == 1
    assert _record_payload(records[0])["delivery"] == "sticky"


def test_context_add_writes_next_child_record(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-add-next-child")

    context_add(storage, "parent-a", [], "note", {"value": "one-shot"})

    records = _journal_records(storage, "context_item_written")
    assert len(records) == 1
    payload = _record_payload(records[0])
    assert payload["delivery"] == "next_child"
    assert payload["scope"] == "direct_child"


def test_context_add_explicit_sticky(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-add-sticky")

    context_add(storage, "parent-a", [], "note", {"value": "persist"}, delivery="sticky")

    records = _journal_records(storage, "context_item_written")
    assert len(records) == 1
    payload = _record_payload(records[0])
    assert payload["delivery"] == "sticky"
    assert payload["scope"] == "descendants"


def test_context_shared_replace_key_supersedes(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-supersede")
    first_item = context_shared(storage, "parent-a", [], "note", {"value": "first"}, replace_key="topic")
    second_item = context_shared(storage, "parent-a", [], "note", {"value": "second"}, replace_key="topic")

    superseded = _journal_records(storage, "context_item_superseded")

    assert len(superseded) == 1
    assert _record_payload(superseded[0]) == {
        "item_id": first_item["item_id"],
        "replace_key": "topic",
        "superseded_by": second_item["item_id"],
    }


def test_context_read_returns_sticky_items(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-sticky")
    item = context_shared(storage, "parent-a", [], "note", {"value": "hello"})

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert [entry["item_id"] for entry in result["items"]] == [item["item_id"]]
    assert result["items"][0]["payload"] == {"value": "hello"}


def test_context_read_excludes_superseded(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-superseded")
    first_item = context_shared(storage, "parent-a", [], "note", {"value": "first"}, replace_key="topic")
    second_item = context_shared(storage, "parent-a", [], "note", {"value": "second"}, replace_key="topic")

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert [entry["item_id"] for entry in result["items"]] == [second_item["item_id"]]
    assert all(entry["item_id"] != first_item["item_id"] for entry in result["items"])


def test_context_read_excludes_consumed_next_child(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-consumed")
    next_child_item = context_add(storage, "parent-a", [], "note", {"value": "single-use"})
    _capture_spawn(storage, tool_use_id="tool-100", parent_agent_id="parent-a")
    correlate_subagent_start(storage, subagent_session_id=storage.session_id, subagent_agent_id="tool-100")

    parent_view = context_read(storage, current_agent_id="parent-a", current_lineage=[])

    assert next_child_item["item_id"] not in [entry["item_id"] for entry in parent_view["items"]]


def test_context_read_stable_ordering(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-order")
    first_item = context_shared(storage, "parent-a", [], "note", {"value": 1})
    second_item = context_shared(storage, "parent-a", [], "note", {"value": 2})
    third_item = context_shared(storage, "parent-a", [], "note", {"value": 3})

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert [entry["item_id"] for entry in result["items"]] == [
        first_item["item_id"],
        second_item["item_id"],
        third_item["item_id"],
    ]
    assert [entry["journal_seq"] for entry in result["items"]] == sorted(
        entry["journal_seq"] for entry in result["items"]
    )


def test_context_read_redacts_restricted(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-redacted")
    context_shared(storage, "parent-a", [], "note", {"token": "secret"}, sensitivity="restricted")

    journal_record = _journal_records(storage, "context_item_written")[0]
    journal_payload = _record_payload(journal_record)
    assert journal_payload["payload"] == {"redacted": True, "sensitivity": "restricted"}
    assert journal_payload["payload_redacted"] is True

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert result["items"][0]["payload"] == {"redacted": True, "sensitivity": "restricted"}


def test_context_read_max_items_truncation(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-truncate")
    first_item = context_shared(storage, "parent-a", [], "note", {"value": "one"})
    second_item = context_shared(storage, "parent-a", [], "note", {"value": "two"})
    context_shared(storage, "parent-a", [], "note", {"value": "three"})

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"], max_items=2)

    assert [entry["item_id"] for entry in result["items"]] == [first_item["item_id"], second_item["item_id"]]
    assert len(result["items"]) == 2


def test_context_read_tags_any_filter(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-tags")
    first_item = context_shared(storage, "parent-a", [], "note", {"value": "alpha"}, tags=["alpha"])
    context_shared(storage, "parent-a", [], "note", {"value": "beta"}, tags=["beta"])
    third_item = context_shared(storage, "parent-a", [], "note", {"value": "alpha-gamma"}, tags=["alpha", "gamma"])

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"], tags_any=["alpha"])

    assert [entry["item_id"] for entry in result["items"]] == [first_item["item_id"], third_item["item_id"]]


# 4. Correlation tests


def test_capture_pretooluse_spawn_creates_pending(repo_root: Path) -> None:
    storage = _storage(repo_root, "capture-pending")

    result = _capture_spawn(storage, tool_use_id="tool-201")

    assert result["status"] == "pending_created"
    pending = storage.read_pending_envelope("tool-201")
    assert pending is not None
    assert pending["correlation_id"] == "tool-201"
    assert pending["session_id"] == storage.session_id
    assert _journal_records(storage, "spawn_pending_written")


def test_capture_pretooluse_spawn_duplicate(repo_root: Path) -> None:
    storage = _storage(repo_root, "capture-duplicate")
    first = _capture_spawn(storage, tool_use_id="tool-202")
    second = _capture_spawn(storage, tool_use_id="tool-202")

    assert first["status"] == "pending_created"
    assert second["status"] == "duplicate"
    assert len(storage.list_pending_envelope_ids()) == 1
    duplicate_records = _journal_records(storage, "duplicate_event_ignored")
    assert len(duplicate_records) == 1
    assert _record_payload(duplicate_records[0])["reason"] == "pending_envelope_already_exists"


def test_correlate_subagent_start_activates(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-activate")
    sticky_item = context_shared(storage, "parent-a", [], "note", {"value": "carry"})
    _capture_spawn(storage, tool_use_id="tool-203", parent_agent_id="parent-a")

    result = correlate_subagent_start(
        storage,
        subagent_session_id=storage.session_id,
        subagent_agent_id="tool-203",
    )

    assert result["status"] == "activated"
    active = storage.read_active_envelope("tool-203")
    assert active is not None
    assert active["agent_id"] == "tool-203"
    assert active["correlation_id"] == "tool-203"
    effective_item_ids = _as_string_list(active["effective_item_ids"])
    assert sticky_item["item_id"] in effective_item_ids


def test_correlate_subagent_start_no_match(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-no-match")
    _capture_spawn(storage, tool_use_id="tool-204")

    result = correlate_subagent_start(
        storage,
        subagent_session_id="different-session",
        subagent_agent_id="tool-204",
    )

    assert result == {"status": "no_match"}
    assert storage.read_active_envelope("tool-204") is None


def test_correlate_subagent_start_wrong_agent_id(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-wrong-agent")
    _capture_spawn(storage, tool_use_id="tool-205")

    result = correlate_subagent_start(
        storage,
        subagent_session_id=storage.session_id,
        subagent_agent_id="tool-205-other",
    )

    assert result == {"status": "no_match"}
    assert storage.read_active_envelope("tool-205-other") is None


def test_correlate_subagent_start_duplicate_activation(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-duplicate")
    _capture_spawn(storage, tool_use_id="tool-206")
    first = correlate_subagent_start(storage, subagent_session_id=storage.session_id, subagent_agent_id="tool-206")
    second = correlate_subagent_start(storage, subagent_session_id=storage.session_id, subagent_agent_id="tool-206")

    assert first["status"] == "activated"
    assert second["status"] == "duplicate"
    assert storage.read_active_envelope("tool-206") is not None
    duplicate_records = _journal_records(storage, "duplicate_event_ignored")
    assert any(
        _record_payload(record).get("reason") == "active_envelope_already_exists" for record in duplicate_records
    )


def test_correlate_next_child_reservation_consumed(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-reserve-consume")
    next_child_item = context_add(storage, "parent-a", [], "note", {"value": "single-use"})

    _capture_spawn(storage, tool_use_id="tool-207", parent_agent_id="parent-a")
    reserved = _journal_records(storage, "next_child_reserved")
    assert len(reserved) == 1
    assert _record_payload(reserved[0])["item_id"] == next_child_item["item_id"]

    correlate_subagent_start(storage, subagent_session_id=storage.session_id, subagent_agent_id="tool-207")
    consumed = _journal_records(storage, "context_item_consumed")

    assert len(consumed) == 1
    assert _record_payload(consumed[0]) == {
        "item_id": next_child_item["item_id"],
        "reserved_for": "tool-207",
    }


def test_correlate_next_child_not_in_later_spawn(repo_root: Path) -> None:
    storage = _storage(repo_root, "correlate-no-steal")
    next_child_item = context_add(storage, "parent-a", [], "note", {"value": "single-use"})

    first = _capture_spawn(storage, tool_use_id="tool-208-a", parent_agent_id="parent-a")
    second = _capture_spawn(storage, tool_use_id="tool-208-b", parent_agent_id="parent-a")

    first_pending = _as_object_dict(first["pending_envelope"])
    second_pending = _as_object_dict(second["pending_envelope"])
    first_eligible_item_ids = _as_string_list(first_pending["eligible_item_ids"])
    first_reserved_item_ids = _as_string_list(first_pending["reserved_next_child_item_ids"])
    second_eligible_item_ids = _as_string_list(second_pending["eligible_item_ids"])
    second_reserved_item_ids = _as_string_list(second_pending["reserved_next_child_item_ids"])

    assert next_child_item["item_id"] in first_eligible_item_ids
    assert next_child_item["item_id"] in first_reserved_item_ids
    assert next_child_item["item_id"] not in second_eligible_item_ids
    assert second_reserved_item_ids == []


# 5. Malformed/orphan tests


def test_malformed_event_missing_session_id(repo_root: Path) -> None:
    storage = _storage(repo_root, "anomaly-malformed")

    correlation_module._append_malformed_event(
        storage,
        agent_id="agent-a",
        correlation_id=None,
        reason="missing_session_id",
        details={"missing_fields": ["session_id"]},
    )

    malformed_records = _journal_records(storage, "malformed_event_ignored")
    assert len(malformed_records) == 1
    assert _record_payload(malformed_records[0]) == {
        "details": {"missing_fields": ["session_id"]},
        "reason": "missing_session_id",
    }


def test_orphaned_pending_no_child_start(repo_root: Path) -> None:
    storage = _storage(repo_root, "anomaly-orphaned")
    next_child_item = context_add(storage, "parent-a", [], "note", {"value": "single-use"})
    _capture_spawn(storage, tool_use_id="tool-209", parent_agent_id="parent-a")

    result = context_read(storage, current_agent_id="parent-a", current_lineage=[])

    assert next_child_item["item_id"] not in [entry["item_id"] for entry in result["items"]]


def test_context_read_redacts_ephemeral(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-ephemeral")
    context_shared(storage, "parent-a", [], "note", {"token": "temporary"}, sensitivity="ephemeral")

    journal_record = _journal_records(storage, "context_item_written")[0]
    journal_payload = _record_payload(journal_record)
    assert journal_payload["payload"] == {"redacted": True, "sensitivity": "ephemeral"}
    assert journal_payload["payload_redacted"] is True

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert result["items"][0]["payload"] == {"redacted": True, "sensitivity": "ephemeral"}


def test_context_read_excludes_expired_item(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-expired")
    context_shared(
        storage,
        "parent-a",
        [],
        "note",
        {"value": "stale"},
        expires_at="2000-01-01T00:00:00Z",
    )

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert result["items"] == []


def test_context_read_excludes_gated_item_without_gate_labels(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-gate-excluded")
    context_shared(storage, "parent-a", [], "note", {"value": "alpha"}, gate_label="alpha")

    result = context_read(storage, current_agent_id="child-a", current_lineage=["parent-a"])

    assert result["items"] == []


def test_context_read_includes_gated_item_with_matching_gate_label(repo_root: Path) -> None:
    storage = _storage(repo_root, "context-read-gate-included")
    item = context_shared(storage, "parent-a", [], "note", {"value": "alpha"}, gate_label="alpha")

    result = context_read(
        storage,
        current_agent_id="child-a",
        current_lineage=["parent-a"],
        gate_labels=["alpha"],
    )

    assert [entry["item_id"] for entry in result["items"]] == [item["item_id"]]


def test_normalize_required_pretooluse_fields_all_present() -> None:
    payload: dict[str, object] = {
        "sessionId": "session-010",
        "toolUseId": "tool-010",
        "toolName": "runSubagent",
        "toolInput": {"agentName": "Support-Researcher"},
        "hookEventName": "PreToolUse",
    }

    result = normalize_required_pretooluse_fields(payload)

    assert result["ok"] is True
    assert result["missing_fields"] == []
    assert result["values"] == {
        "session_id": "session-010",
        "tool_use_id": "tool-010",
        "tool_name": "runSubagent",
        "tool_input": {"agent_name": "Support-Researcher"},
        "hook_event_name": "PreToolUse",
    }


def test_normalize_required_pretooluse_fields_missing_required_values() -> None:
    payload: dict[str, object] = {
        "sessionId": "session-011",
        "toolInput": {"agentName": "Support-Researcher"},
        "hookEventName": "PreToolUse",
    }

    result = normalize_required_pretooluse_fields(payload)

    assert result["ok"] is False
    assert result["missing_fields"] == ["tool_use_id", "tool_name"]


def test_normalize_required_subagentstart_fields_all_present() -> None:
    payload: dict[str, object] = {
        "sessionId": "session-012",
        "agentId": "agent-012",
        "hookEventName": "SubagentStart",
    }

    result = normalize_required_subagentstart_fields(payload)

    assert result["ok"] is True
    assert result["missing_fields"] == []
    assert result["values"] == {
        "session_id": "session-012",
        "agent_id": "agent-012",
        "hook_event_name": "SubagentStart",
    }
