"""Deterministic shared-context read/write helpers for hook tooling."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final, cast

from .normalizer import JSONValue, normalize_key
from .storage import SessionStorage

VALID_DELIVERIES: Final[frozenset[str]] = frozenset({"next_child", "sticky"})
VALID_SCOPES: Final[frozenset[str]] = frozenset({"descendants", "direct_child"})
VALID_SENSITIVITIES: Final[frozenset[str]] = frozenset({"ephemeral", "normal", "restricted"})


@dataclass(frozen=True)
class StoredContextItem:
    """Canonical context item reconstructed from the append-only journal."""

    delivery: str
    expires_at: str | None
    gate_label: str | None
    item_id: str
    journal_seq: int
    kind: str
    owner_agent_id: str
    owner_lineage: list[str]
    payload: dict[str, JSONValue]
    replace_key: str | None
    scope: str
    sensitivity: str
    source_op: str
    tags: list[str]


@dataclass(frozen=True)
class JournalContextState:
    """Derived state for context items and their lifecycle transitions."""

    consumed_item_ids: set[str]
    items_by_id: dict[str, StoredContextItem]
    reserved_item_ids: set[str]
    superseded_item_ids: set[str]

    @property
    def ordered_items(self) -> list[StoredContextItem]:
        """Return items in stable ascending journal order."""

        return sorted(self.items_by_id.values(), key=lambda item: item.journal_seq)


def _normalize_non_empty_string(value: object) -> str | None:
    """Return a trimmed non-empty string, or `None` when unusable."""

    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _normalize_string_list(values: object, *, canonicalize: bool = False) -> list[str] | None:
    """Return a deterministic de-duplicated string list."""

    if not isinstance(values, list):
        return None

    normalized_values: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        normalized = _normalize_non_empty_string(raw_value)
        if normalized is None:
            return None
        if canonicalize:
            normalized = normalize_key(normalized)
            if not normalized:
                return None
        if normalized in seen:
            continue
        seen.add(normalized)
        normalized_values.append(normalized)
    return normalized_values


def _normalize_optional_string(value: object) -> str | None:
    """Normalize optional string metadata to a trimmed value or `None`."""

    return _normalize_non_empty_string(value)


def _normalize_delivery(value: str) -> str:
    """Canonicalize and validate a delivery mode."""

    normalized = normalize_key(value)
    if normalized not in VALID_DELIVERIES:
        raise ValueError(f"Unsupported delivery: {value}")
    return normalized


def _normalize_scope(value: str) -> str:
    """Canonicalize and validate a visibility scope."""

    normalized = normalize_key(value)
    if normalized not in VALID_SCOPES:
        raise ValueError(f"Unsupported scope: {value}")
    return normalized


def _normalize_sensitivity(value: str) -> str:
    """Canonicalize and validate a sensitivity level."""

    normalized = normalize_key(value)
    if normalized not in VALID_SENSITIVITIES:
        raise ValueError(f"Unsupported sensitivity: {value}")
    return normalized


def _normalize_kind(value: str) -> str:
    """Canonicalize and validate a non-empty context kind."""

    normalized = normalize_key(value)
    if not normalized:
        raise ValueError("kind must be a non-empty string.")
    return normalized


def _normalize_json_value(value: object) -> JSONValue:
    """Recursively normalize a JSON-compatible value, canonicalizing dict keys."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    if isinstance(value, list):
        return [_normalize_json_value(item) for item in value]

    if isinstance(value, dict):
        normalized: dict[str, JSONValue] = {}
        for raw_key, raw_value in value.items():
            key_name = normalize_key(str(raw_key))
            if not key_name:
                continue
            if key_name in normalized:
                continue
            normalized[key_name] = _normalize_json_value(raw_value)
        return normalized

    raise ValueError(f"Unsupported JSON value type: {type(value).__name__}")


def _normalize_payload_dict(payload: dict[str, object]) -> dict[str, JSONValue]:
    """Normalize a context payload into a canonical JSON object."""

    normalized_payload = _normalize_json_value(payload)
    if not isinstance(normalized_payload, dict):
        raise ValueError("payload must be a JSON object.")
    return normalized_payload


def _normalize_expires_at(value: str | None) -> str | None:
    """Normalize and validate an ISO8601 expiration timestamp when supplied."""

    normalized = _normalize_optional_string(value)
    if normalized is None:
        return None

    _parse_timestamp(normalized)
    return normalized


def _parse_timestamp(value: str) -> datetime | None:
    """Parse an ISO8601 timestamp, accepting a trailing `Z`."""

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _is_expired(expires_at: str | None) -> bool:
    """Return whether an item expiration lies in the past."""

    if expires_at is None:
        return False

    parsed = _parse_timestamp(expires_at)
    if parsed is None:
        return True

    return parsed <= _uuid_utc_now()


def _uuid_utc_now() -> datetime:
    """Return a UTC timestamp using the repository-compliant UUID clock path."""

    gregorian_epoch = datetime(1582, 10, 15, tzinfo=UTC)
    return gregorian_epoch + timedelta(microseconds=uuid.uuid1().time / 10)


def _redacted_payload(sensitivity: str) -> dict[str, JSONValue]:
    """Return the deterministic redacted payload envelope for sensitive items."""

    return {"redacted": True, "sensitivity": sensitivity}


def _journal_payload_for_context_item(
    payload: dict[str, JSONValue],
    sensitivity: str,
) -> tuple[dict[str, JSONValue], bool]:
    """Return the persisted payload and whether the journal payload was redacted."""

    if sensitivity in {"restricted", "ephemeral"}:
        return _redacted_payload(sensitivity), True
    return payload, False


def _append_record(
    storage: SessionStorage,
    *,
    record_type: str,
    agent_id: str,
    correlation_id: str | None,
    payload: dict[str, JSONValue],
) -> int:
    """Append one canonical journal record and return its sequence number."""

    record = storage.append_journal_record(
        record_type=record_type,
        agent_id=agent_id,
        correlation_id=correlation_id,
        payload=payload,
    )
    return record["journal_seq"]


def _append_malformed_event(
    storage: SessionStorage,
    *,
    agent_id: str,
    reason: str,
    correlation_id: str | None = None,
    details: dict[str, JSONValue] | None = None,
) -> int:
    """Append a deterministic malformed/anomaly journal record."""

    payload: dict[str, JSONValue] = {"reason": reason}
    if details is not None:
        payload["details"] = cast("JSONValue", details)
    return _append_record(
        storage,
        record_type="malformed_event_ignored",
        agent_id=agent_id,
        correlation_id=correlation_id,
        payload=payload,
    )


def _extract_item_id(payload: object) -> str | None:
    """Extract a referenced item id from a lifecycle payload when present."""

    if not isinstance(payload, dict):
        return None

    for key_name in ("item_id", "old_item_id"):
        item_id = _normalize_non_empty_string(payload.get(key_name))
        if item_id is not None:
            return item_id
    return None


def _parse_context_item(record: dict[str, object]) -> StoredContextItem | None:
    """Parse one `context_item_written` record into canonical in-memory state."""

    if record.get("record_type") != "context_item_written":
        return None

    payload = record.get("payload")
    if not isinstance(payload, dict):
        return None

    journal_seq = record.get("journal_seq")
    item_id = _normalize_non_empty_string(payload.get("item_id"))
    source_op = _normalize_non_empty_string(payload.get("source_op"))
    owner_agent_id = _normalize_non_empty_string(payload.get("owner_agent_id"))
    owner_lineage = _normalize_string_list(payload.get("owner_lineage"))
    kind = _normalize_non_empty_string(payload.get("kind"))
    tags = _normalize_string_list(payload.get("tags"), canonicalize=True)
    delivery = _normalize_non_empty_string(payload.get("delivery"))
    scope = _normalize_non_empty_string(payload.get("scope"))
    sensitivity = _normalize_non_empty_string(payload.get("sensitivity"))
    expires_at = _normalize_optional_string(payload.get("expires_at"))
    gate_label = _normalize_optional_string(payload.get("gate_label"))
    replace_key = _normalize_optional_string(payload.get("replace_key"))
    item_payload = payload.get("payload")

    if not isinstance(journal_seq, int):
        return None
    if not isinstance(item_payload, dict):
        return None
    if item_id is None or source_op is None or owner_agent_id is None or owner_lineage is None or kind is None:
        return None
    if tags is None or delivery is None or scope is None or sensitivity is None:
        return None

    try:
        normalized_delivery = _normalize_delivery(delivery)
        normalized_scope = _normalize_scope(scope)
        normalized_sensitivity = _normalize_sensitivity(sensitivity)
        normalized_kind = _normalize_kind(kind)
        normalized_payload = _normalize_payload_dict(cast("dict[str, object]", item_payload))
    except ValueError:
        return None

    return StoredContextItem(
        delivery=normalized_delivery,
        expires_at=expires_at,
        gate_label=gate_label,
        item_id=item_id,
        journal_seq=journal_seq,
        kind=normalized_kind,
        owner_agent_id=owner_agent_id,
        owner_lineage=owner_lineage,
        payload=normalized_payload,
        replace_key=replace_key,
        scope=normalized_scope,
        sensitivity=normalized_sensitivity,
        source_op=source_op,
        tags=tags,
    )


def _journal_sort_key(record: dict[str, object]) -> int:
    """Return a stable integer sort key for journal records."""

    journal_seq = record.get("journal_seq")
    return journal_seq if isinstance(journal_seq, int) else 0


def _build_journal_state(storage: SessionStorage) -> JournalContextState:
    """Reconstruct current context-item lifecycle state from the journal."""

    items_by_id: dict[str, StoredContextItem] = {}
    superseded_item_ids: set[str] = set()
    consumed_item_ids: set[str] = set()
    reserved_item_ids: set[str] = set()

    records = sorted(storage.read_journal(), key=_journal_sort_key)
    for record in records:
        parsed_item = _parse_context_item(record)
        if parsed_item is not None:
            items_by_id[parsed_item.item_id] = parsed_item
            continue

        payload = record.get("payload")
        item_id = _extract_item_id(payload)
        record_type = record.get("record_type")
        if item_id is None or not isinstance(record_type, str):
            continue
        if record_type == "context_item_superseded":
            superseded_item_ids.add(item_id)
        elif record_type == "context_item_consumed":
            consumed_item_ids.add(item_id)
        elif record_type == "next_child_reserved":
            reserved_item_ids.add(item_id)

    return JournalContextState(
        consumed_item_ids=consumed_item_ids,
        items_by_id=items_by_id,
        reserved_item_ids=reserved_item_ids,
        superseded_item_ids=superseded_item_ids,
    )


def _is_descendant(owner_agent_id: str, current_agent_id: str, current_lineage: list[str]) -> bool:
    """Return whether `current_agent_id` is a descendant of the owner."""

    return current_agent_id != owner_agent_id and owner_agent_id in current_lineage


def _matches_scope(item: StoredContextItem, *, current_agent_id: str, current_lineage: list[str]) -> bool:
    """Check whether an item's scope permits visibility to the current agent."""

    if item.owner_agent_id == current_agent_id:
        return True
    if not _is_descendant(item.owner_agent_id, current_agent_id, current_lineage):
        return False
    if item.scope == "descendants":
        return True
    if item.scope == "direct_child":
        return bool(current_lineage) and current_lineage[-1] == item.owner_agent_id
    return False


def _passes_gate(item: StoredContextItem, gate_labels: list[str] | None) -> bool:
    """Return whether an item passes deterministic gate-label filtering."""

    if item.gate_label is None:
        return True
    if gate_labels is None:
        return False
    return item.gate_label in gate_labels


def _passes_tags(item: StoredContextItem, tags_any: list[str] | None) -> bool:
    """Return whether an item matches the requested tag subset."""

    if not tags_any:
        return True
    return any(tag in item.tags for tag in tags_any)


def _is_live_for_general_reads(item: StoredContextItem, state: JournalContextState) -> bool:
    """Return whether an item remains active for general journal-based reads."""

    if _is_expired(item.expires_at):
        return False
    if item.item_id in state.superseded_item_ids:
        return False
    if item.delivery == "next_child" and item.item_id in state.consumed_item_ids:
        return False
    return not (item.delivery == "next_child" and item.item_id in state.reserved_item_ids)


def _serialize_output_item(item: StoredContextItem) -> dict[str, object]:
    """Serialize an item into the recommended `context_read` output shape."""

    payload: dict[str, JSONValue]
    if item.sensitivity in {"restricted", "ephemeral"}:
        payload = _redacted_payload(item.sensitivity)
    else:
        payload = item.payload

    return {
        "delivery": item.delivery,
        "gate_label": item.gate_label,
        "item_id": item.item_id,
        "journal_seq": item.journal_seq,
        "kind": item.kind,
        "owner_agent_id": item.owner_agent_id,
        "payload": payload,
        "scope": item.scope,
        "sensitivity": item.sensitivity,
        "tags": list(item.tags),
    }


def _payload_size_bytes(item: dict[str, object]) -> int:
    """Compute the UTF-8 payload size for truncation accounting."""

    payload = item.get("payload", {})
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return len(serialized.encode("utf-8"))


def _normalize_filter_tags(values: list[str] | None) -> list[str] | None:
    """Normalize optional tag filters using canonical tag casing rules."""

    if values is None:
        return None
    return _normalize_string_list(cast("object", values), canonicalize=True) or []


def _normalize_filter_gate_labels(values: list[str] | None) -> list[str] | None:
    """Normalize optional gate-label filters."""

    if values is None:
        return None
    return _normalize_string_list(cast("object", values), canonicalize=False) or []


def _normalize_lineage(lineage: list[str]) -> list[str]:
    """Normalize an agent lineage chain to trimmed non-empty ids."""

    normalized = _normalize_string_list(cast("object", lineage), canonicalize=False)
    if normalized is None:
        raise ValueError("lineage must contain only non-empty strings.")
    return normalized


def _canonical_item_metadata(
    *,
    item_id: str,
    journal_seq: int,
    owner_agent_id: str,
    owner_lineage: list[str],
    kind: str,
    payload: dict[str, JSONValue],
    tags: list[str],
    delivery: str,
    scope: str,
    gate_label: str | None,
    replace_key: str | None,
    sensitivity: str,
    expires_at: str | None,
    source_op: str,
) -> dict[str, object]:
    """Return the canonical context-item metadata shape."""

    return {
        "delivery": delivery,
        "expires_at": expires_at,
        "gate_label": gate_label,
        "item_id": item_id,
        "journal_seq": journal_seq,
        "kind": kind,
        "owner_agent_id": owner_agent_id,
        "owner_lineage": owner_lineage,
        "payload": payload,
        "replace_key": replace_key,
        "scope": scope,
        "sensitivity": sensitivity,
        "source_op": source_op,
        "tags": tags,
    }


def context_shared(
    storage: SessionStorage,
    owner_agent_id: str,
    owner_lineage: list[str],
    kind: str,
    payload: dict,
    *,
    tags: list[str] | None = None,
    scope: str = "descendants",
    gate_label: str | None = None,
    replace_key: str | None = None,
    sensitivity: str = "normal",
    expires_at: str | None = None,
) -> dict:
    """Write a sticky shared-context item owned by the current agent.

    Args:
        storage: The session storage for the current session.
        owner_agent_id: Non-empty identifier of the writing agent.
        owner_lineage: Ordered list of ancestor agent ids; empty for root agents.
        kind: Semantic category label for the item (non-empty string).
        payload: Arbitrary JSON-serializable dict to persist.
        tags: Optional list of tag strings for filtering.
        scope: Visibility scope for the item. Defaults to ``"descendants"``.
            Valid values: ``"descendants"``, ``"direct_child"``, ``"global"``.
        gate_label: Optional label that restricts delivery to agents that
            explicitly request this label via ``gate_labels`` in ``context_read``.
        replace_key: When set, supersedes any live sticky item owned by this
            agent with the same ``replace_key`` before writing the new item.
        sensitivity: Controls journal payload storage. ``"normal"`` stores the
            full payload; ``"restricted"`` and ``"ephemeral"`` redact the
            payload in the journal and return a placeholder.
            Valid values: ``"normal"``, ``"restricted"``, ``"ephemeral"``.
        expires_at: Optional ISO 8601 UTC expiry timestamp after which the item
            is excluded from ``context_read`` results.

    Returns:
        A dict with canonical item metadata: ``item_id``, ``journal_seq``,
        ``owner_agent_id``, ``owner_lineage``, ``kind``, ``payload``, ``tags``,
        ``delivery``, ``scope``, ``gate_label``, ``replace_key``,
        ``sensitivity``, ``expires_at``, ``source_op``.

    Raises:
        ValueError: If ``owner_agent_id`` is empty, ``tags`` contains empty
            strings, or any normalized field value is invalid.
    """

    normalized_owner_agent_id = _normalize_non_empty_string(owner_agent_id)
    if normalized_owner_agent_id is None:
        raise ValueError("owner_agent_id must be a non-empty string.")

    normalized_owner_lineage = _normalize_lineage(owner_lineage)
    normalized_kind = _normalize_kind(kind)
    normalized_payload = _normalize_payload_dict(cast("dict[str, object]", payload))
    normalized_tags = _normalize_string_list(cast("object", tags or []), canonicalize=True)
    if normalized_tags is None:
        raise ValueError("tags must contain only non-empty strings.")
    normalized_scope = _normalize_scope(scope)
    normalized_gate_label = _normalize_optional_string(gate_label)
    normalized_replace_key = _normalize_optional_string(replace_key)
    normalized_sensitivity = _normalize_sensitivity(sensitivity)
    normalized_expires_at = _normalize_expires_at(expires_at)
    item_id = f"ctx_{uuid.uuid4().hex[:12]}"

    state = _build_journal_state(storage)
    if normalized_replace_key is not None:
        for existing_item in state.ordered_items:
            if existing_item.delivery != "sticky":
                continue
            if existing_item.owner_agent_id != normalized_owner_agent_id:
                continue
            if existing_item.replace_key != normalized_replace_key:
                continue
            if not _is_live_for_general_reads(existing_item, state):
                continue
            _append_record(
                storage,
                record_type="context_item_superseded",
                agent_id=normalized_owner_agent_id,
                correlation_id=None,
                payload={
                    "item_id": existing_item.item_id,
                    "replace_key": normalized_replace_key,
                    "superseded_by": item_id,
                },
            )

    persisted_payload, payload_redacted = _journal_payload_for_context_item(
        normalized_payload,
        normalized_sensitivity,
    )
    record_payload: dict[str, JSONValue] = {
        "delivery": "sticky",
        "expires_at": normalized_expires_at,
        "gate_label": normalized_gate_label,
        "item_id": item_id,
        "kind": normalized_kind,
        "owner_agent_id": normalized_owner_agent_id,
        "owner_lineage": cast("JSONValue", normalized_owner_lineage),
        "payload": cast("JSONValue", persisted_payload),
        "payload_redacted": payload_redacted,
        "replace_key": normalized_replace_key,
        "scope": normalized_scope,
        "sensitivity": normalized_sensitivity,
        "source_op": "context_shared",
        "state": "active",
        "tags": cast("JSONValue", normalized_tags),
    }
    journal_seq = _append_record(
        storage,
        record_type="context_item_written",
        agent_id=normalized_owner_agent_id,
        correlation_id=None,
        payload=record_payload,
    )
    return _canonical_item_metadata(
        item_id=item_id,
        journal_seq=journal_seq,
        owner_agent_id=normalized_owner_agent_id,
        owner_lineage=normalized_owner_lineage,
        kind=normalized_kind,
        payload=normalized_payload,
        tags=normalized_tags,
        delivery="sticky",
        scope=normalized_scope,
        gate_label=normalized_gate_label,
        replace_key=normalized_replace_key,
        sensitivity=normalized_sensitivity,
        expires_at=normalized_expires_at,
        source_op="context_shared",
    )


def context_add(
    storage: SessionStorage,
    owner_agent_id: str,
    owner_lineage: list[str],
    kind: str,
    payload: dict,
    *,
    delivery: str = "next_child",
    tags: list[str] | None = None,
    scope: str | None = None,
    gate_label: str | None = None,
    replace_key: str | None = None,
    sensitivity: str = "normal",
    expires_at: str | None = None,
) -> dict:
    """Write a context item with explicit delivery semantics.

    Args:
        storage: The session storage for the current session.
        owner_agent_id: Non-empty identifier of the writing agent.
        owner_lineage: Ordered list of ancestor agent ids.
        kind: Semantic category label for the item.
        payload: Arbitrary JSON-serializable dict to persist.
        delivery: Delivery mode. Defaults to ``"next_child"``.
            - ``"sticky"``: persistent across all descendants within scope.
            - ``"next_child"``: consumed by the first direct child spawn;
              defaults ``scope`` to ``"direct_child"``.
            - ``"ephemeral"``: single-read delivery.
        tags: Optional tag strings for filtering.
        scope: Visibility scope. When ``None``, defaults to ``"direct_child"``
            for ``next_child`` delivery and ``"descendants"`` otherwise.
        gate_label: Optional gate label restricting delivery.
        replace_key: Supersedes matching live items owned by this agent.
        sensitivity: ``"normal"``, ``"restricted"``, or ``"ephemeral"``.
            ``"restricted"`` and ``"ephemeral"`` redact the journal payload.
        expires_at: Optional ISO 8601 UTC expiry timestamp.

    Returns:
        A dict with canonical item metadata (same shape as ``context_shared``).

    Raises:
        ValueError: If ``owner_agent_id`` is empty, ``tags`` contains empty
            strings, or any normalized field value is invalid.
    """

    normalized_owner_agent_id = _normalize_non_empty_string(owner_agent_id)
    if normalized_owner_agent_id is None:
        raise ValueError("owner_agent_id must be a non-empty string.")

    normalized_owner_lineage = _normalize_lineage(owner_lineage)
    normalized_kind = _normalize_kind(kind)
    normalized_payload = _normalize_payload_dict(cast("dict[str, object]", payload))
    normalized_delivery = _normalize_delivery(delivery)
    normalized_tags = _normalize_string_list(cast("object", tags or []), canonicalize=True)
    if normalized_tags is None:
        raise ValueError("tags must contain only non-empty strings.")
    default_scope = "direct_child" if normalized_delivery == "next_child" else "descendants"
    normalized_scope = _normalize_scope(scope or default_scope)
    normalized_gate_label = _normalize_optional_string(gate_label)
    normalized_replace_key = _normalize_optional_string(replace_key)
    normalized_sensitivity = _normalize_sensitivity(sensitivity)
    normalized_expires_at = _normalize_expires_at(expires_at)
    item_id = f"ctx_{uuid.uuid4().hex[:12]}"

    persisted_payload, payload_redacted = _journal_payload_for_context_item(
        normalized_payload,
        normalized_sensitivity,
    )
    record_payload: dict[str, JSONValue] = {
        "delivery": normalized_delivery,
        "expires_at": normalized_expires_at,
        "gate_label": normalized_gate_label,
        "item_id": item_id,
        "kind": normalized_kind,
        "owner_agent_id": normalized_owner_agent_id,
        "owner_lineage": cast("JSONValue", normalized_owner_lineage),
        "payload": cast("JSONValue", persisted_payload),
        "payload_redacted": payload_redacted,
        "replace_key": normalized_replace_key,
        "scope": normalized_scope,
        "sensitivity": normalized_sensitivity,
        "source_op": "context_add",
        "state": "active",
        "tags": cast("JSONValue", normalized_tags),
    }
    journal_seq = _append_record(
        storage,
        record_type="context_item_written",
        agent_id=normalized_owner_agent_id,
        correlation_id=None,
        payload=record_payload,
    )
    return _canonical_item_metadata(
        item_id=item_id,
        journal_seq=journal_seq,
        owner_agent_id=normalized_owner_agent_id,
        owner_lineage=normalized_owner_lineage,
        kind=normalized_kind,
        payload=normalized_payload,
        tags=normalized_tags,
        delivery=normalized_delivery,
        scope=normalized_scope,
        gate_label=normalized_gate_label,
        replace_key=normalized_replace_key,
        sensitivity=normalized_sensitivity,
        expires_at=normalized_expires_at,
        source_op="context_add",
    )


def context_read(
    storage: SessionStorage,
    current_agent_id: str,
    current_lineage: list[str],
    *,
    include_self_owned: bool = True,
    tags_any: list[str] | None = None,
    gate_labels: list[str] | None = None,
    max_items: int | None = None,
    max_payload_bytes: int | None = None,
) -> dict:
    """Read the current agent's effective shared-context view deterministically.

    When an active envelope exists for ``current_agent_id``, only the exact
    pre-computed ``effective_item_ids`` from that envelope are returned (the
    envelope path). When no envelope exists, the journal state is scanned for
    all live items that are in-scope for this agent (the fallback path).
    Self-owned items are appended after both paths when ``include_self_owned``
    is ``True``.

    Args:
        storage: The session storage for the current session.
        current_agent_id: Non-empty identifier of the reading agent.
        current_lineage: Ordered list of ancestor agent ids.
        include_self_owned: When ``True`` (default), items written by
            ``current_agent_id`` are included even if scope filtering would
            exclude them.
        tags_any: When set, only items tagged with at least one of these tags
            are included.
        gate_labels: When set, only items with a ``gate_label`` that is in this
            list (or items with no ``gate_label``) are included.
        max_items: Optional upper bound on returned items (applied after
            sorting by ``journal_seq``).
        max_payload_bytes: Optional byte budget for total serialized item
            payloads (applied after sorting; items that would exceed the budget
            are dropped).

    Returns:
        A dict with keys:
        - ``agent_id`` (str): normalized ``current_agent_id``.
        - ``items`` (list[dict]): ordered list of serialized context items.
        - ``lineage`` (list[str]): normalized ``current_lineage``.
        - ``session_id`` (str): the session this read applies to.

    Raises:
        ValueError: If ``current_agent_id`` is empty, or ``max_items`` /
            ``max_payload_bytes`` are negative.
    """

    normalized_current_agent_id = _normalize_non_empty_string(current_agent_id)
    if normalized_current_agent_id is None:
        raise ValueError("current_agent_id must be a non-empty string.")

    normalized_current_lineage = _normalize_lineage(current_lineage)
    normalized_tags_any = _normalize_filter_tags(tags_any)
    normalized_gate_labels = _normalize_filter_gate_labels(gate_labels)
    if max_items is not None and max_items < 0:
        raise ValueError("max_items must be >= 0 when provided.")
    if max_payload_bytes is not None and max_payload_bytes < 0:
        raise ValueError("max_payload_bytes must be >= 0 when provided.")

    state = _build_journal_state(storage)
    active_envelope = storage.read_active_envelope(normalized_current_agent_id)
    selected_items: list[StoredContextItem] = []
    selected_ids: set[str] = set()

    if active_envelope is not None:
        effective_item_ids = _normalize_string_list(active_envelope.get("effective_item_ids"))
        envelope_session_id = _normalize_non_empty_string(active_envelope.get("session_id"))
        envelope_agent_id = _normalize_non_empty_string(active_envelope.get("agent_id"))
        if (
            effective_item_ids is None
            or envelope_session_id != storage.session_id
            or envelope_agent_id != normalized_current_agent_id
        ):
            _append_malformed_event(
                storage,
                agent_id=normalized_current_agent_id,
                reason="invalid_active_envelope",
                correlation_id=normalized_current_agent_id,
                details={"agent_id": normalized_current_agent_id},
            )
            return {
                "agent_id": normalized_current_agent_id,
                "items": [],
                "lineage": normalized_current_lineage,
                "session_id": storage.session_id,
            }

        for item_id in effective_item_ids:
            item = state.items_by_id.get(item_id)
            if item is None:
                _append_malformed_event(
                    storage,
                    agent_id=normalized_current_agent_id,
                    reason="missing_effective_item",
                    correlation_id=normalized_current_agent_id,
                    details={"item_id": item_id},
                )
                return {
                    "agent_id": normalized_current_agent_id,
                    "items": [],
                    "lineage": normalized_current_lineage,
                    "session_id": storage.session_id,
                }
            if not _passes_tags(item, normalized_tags_any):
                continue
            if not _passes_gate(item, normalized_gate_labels):
                continue
            if item.item_id in selected_ids:
                continue
            selected_ids.add(item.item_id)
            selected_items.append(item)
    else:
        for item in state.ordered_items:
            if not include_self_owned and item.owner_agent_id == normalized_current_agent_id:
                continue
            if not _matches_scope(
                item, current_agent_id=normalized_current_agent_id, current_lineage=normalized_current_lineage
            ):
                continue
            if not _is_live_for_general_reads(item, state):
                continue
            if not _passes_tags(item, normalized_tags_any):
                continue
            if not _passes_gate(item, normalized_gate_labels):
                continue
            if item.item_id in selected_ids:
                continue
            selected_ids.add(item.item_id)
            selected_items.append(item)

    if include_self_owned:
        for item in state.ordered_items:
            if item.owner_agent_id != normalized_current_agent_id:
                continue
            if item.item_id in selected_ids:
                continue
            if not _is_live_for_general_reads(item, state):
                continue
            if not _passes_tags(item, normalized_tags_any):
                continue
            if not _passes_gate(item, normalized_gate_labels):
                continue
            selected_ids.add(item.item_id)
            selected_items.append(item)

    ordered_items = sorted(selected_items, key=lambda item: item.journal_seq)
    output_items: list[dict[str, object]] = []
    payload_bytes_used = 0
    for item in ordered_items:
        serialized_item = _serialize_output_item(item)
        item_payload_bytes = _payload_size_bytes(serialized_item)
        if max_payload_bytes is not None and payload_bytes_used + item_payload_bytes > max_payload_bytes:
            break
        output_items.append(serialized_item)
        payload_bytes_used += item_payload_bytes
        if max_items is not None and len(output_items) >= max_items:
            break

    return {
        "agent_id": normalized_current_agent_id,
        "items": output_items,
        "lineage": normalized_current_lineage,
        "session_id": storage.session_id,
    }


__all__ = [
    "VALID_DELIVERIES",
    "VALID_SCOPES",
    "VALID_SENSITIVITIES",
    "JournalContextState",
    "StoredContextItem",
    "context_add",
    "context_read",
    "context_shared",
]
