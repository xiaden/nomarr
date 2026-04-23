"""Normalize hook payloads to canonical snake_case field names."""

from __future__ import annotations

import re
from typing import TypedDict

type JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | list["JSONValue"] | dict[str, "JSONValue"]
type NormalizedPayload = dict[str, object]
type RequiredValues = dict[str, object]

_ALIAS_MAP: dict[str, str] = {
    "agentId": "agent_id",
    "agentType": "agent_type",
    "hookEventName": "hook_event_name",
    "sessionId": "session_id",
    "toolInput": "tool_input",
    "toolName": "tool_name",
    "toolUseId": "tool_use_id",
    "transcriptPath": "transcript_path",
}

_PRETOOLUSE_REQUIRED_FIELDS: list[str] = [
    "session_id",
    "tool_use_id",
    "tool_name",
    "tool_input",
    "hook_event_name",
]

_SUBAGENTSTART_REQUIRED_FIELDS: list[str] = [
    "session_id",
    "agent_id",
    "hook_event_name",
]

_FIRST_CAMEL_PATTERN = re.compile(r"(.)([A-Z][a-z]+)")
_SECOND_CAMEL_PATTERN = re.compile(r"([a-z0-9])([A-Z])")
_REPEATED_UNDERSCORE_PATTERN = re.compile(r"__+")


class RequiredFieldResult(TypedDict):
    """Deterministic normalization/validation result for required hook fields."""

    missing_fields: list[str]
    normalized_payload: NormalizedPayload
    ok: bool
    values: RequiredValues


def normalize_key(key: str) -> str:
    """Convert a payload key to its canonical snake_case representation."""

    stripped = key.strip()
    if not stripped:
        return ""

    if stripped in _ALIAS_MAP:
        return _ALIAS_MAP[stripped]

    normalized = _FIRST_CAMEL_PATTERN.sub(r"\1_\2", stripped)
    normalized = _SECOND_CAMEL_PATTERN.sub(r"\1_\2", normalized)
    normalized = normalized.replace("-", "_")
    normalized = _REPEATED_UNDERSCORE_PATTERN.sub("_", normalized).lower()
    return _ALIAS_MAP.get(normalized, normalized)


def _normalize_tool_input_value(value: object) -> object:
    """Recursively normalize nested tool_input dictionaries only."""

    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for raw_key, raw_value in value.items():
            canonical_key = normalize_key(str(raw_key))
            if canonical_key in normalized and raw_key != canonical_key:
                continue
            normalized[canonical_key] = _normalize_tool_input_value(raw_value)
        return normalized

    if isinstance(value, list):
        return [_normalize_tool_input_value(item) for item in value]

    return value


def normalize_payload(payload: dict[str, object]) -> dict[str, object]:
    """Normalize top-level payload keys and recurse only into `tool_input`."""

    normalized: dict[str, object] = {}
    for raw_key, raw_value in payload.items():
        canonical_key = normalize_key(str(raw_key))
        if not canonical_key:
            continue

        value: object = raw_value
        if canonical_key == "tool_input":
            value = _normalize_tool_input_value(raw_value)

        if canonical_key in normalized and raw_key != canonical_key:
            continue

        normalized[canonical_key] = value
    return normalized


def normalize_payload_keys(payload: dict[str, object]) -> dict[str, object]:
    """Compatibility wrapper matching the design-contract naming."""

    return normalize_payload(payload)


def _coerce_required_value(field_name: str, value: object) -> tuple[bool, object]:
    """Return whether a required field is present along with its normalized value."""

    if field_name == "tool_input":
        return isinstance(value, dict), value

    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed != "", trimmed

    return value is not None, value


def extract_required(payload: dict[str, object], fields: list[str]) -> tuple[dict[str, object], list[str]]:
    """Extract canonical required fields and report which are missing/invalid."""

    extracted: dict[str, object] = {}
    missing: list[str] = []
    for field_name in fields:
        present, normalized_value = _coerce_required_value(field_name, payload.get(field_name))
        if not present:
            missing.append(field_name)
            continue
        extracted[field_name] = normalized_value
    return extracted, missing


def _normalize_required_fields(payload: dict[str, object], required_fields: list[str]) -> RequiredFieldResult:
    """Normalize payload keys and package deterministic validation signals."""

    normalized_payload = normalize_payload(payload)
    extracted, missing = extract_required(normalized_payload, required_fields)
    return {
        "missing_fields": missing,
        "normalized_payload": normalized_payload,
        "ok": not missing,
        "values": extracted,
    }


def normalize_required_pretooluse_fields(payload: dict[str, object]) -> RequiredFieldResult:
    """Normalize and validate the fields required by `PreToolUse(runSubagent)`."""

    return _normalize_required_fields(payload, _PRETOOLUSE_REQUIRED_FIELDS)


def normalize_required_subagentstart_fields(payload: dict[str, object]) -> RequiredFieldResult:
    """Normalize and validate the fields required by `SubagentStart`."""

    return _normalize_required_fields(payload, _SUBAGENTSTART_REQUIRED_FIELDS)


__all__ = [
    "JSONValue",
    "RequiredFieldResult",
    "extract_required",
    "normalize_key",
    "normalize_payload",
    "normalize_payload_keys",
    "normalize_required_pretooluse_fields",
    "normalize_required_subagentstart_fields",
]
