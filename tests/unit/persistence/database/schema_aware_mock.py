"""Schema-aware mock database for persistence AQL unit tests."""

from __future__ import annotations

import re
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

_AQL_SAFETY_CONFTEST_PATH = Path(__file__).resolve().parents[2] / "aql_safety" / "conftest.py"
_AQL_SAFETY_SPEC = spec_from_file_location(
    "tests.unit.aql_safety.conftest",
    _AQL_SAFETY_CONFTEST_PATH,
)
assert _AQL_SAFETY_SPEC is not None and _AQL_SAFETY_SPEC.loader is not None
_AQL_SAFETY_MODULE = module_from_spec(_AQL_SAFETY_SPEC)
_AQL_SAFETY_SPEC.loader.exec_module(_AQL_SAFETY_MODULE)

DOCUMENT_COLLECTIONS = set(_AQL_SAFETY_MODULE.DOCUMENT_COLLECTIONS)
EDGE_COLLECTIONS = set(_AQL_SAFETY_MODULE.EDGE_COLLECTIONS)

_RE_COLLECTIONS = re.compile(
    r"(?:FOR\s+\w+\s+IN\s+(?!OUTBOUND|INBOUND|ANY|@)"
    r"|INSERT\s+.*?\bIN(?:TO)?\s+"
    r"|UPSERT\s+.*?\bIN(?:TO)?\s+"
    r"|REMOVE\s+.*?\bIN\s+"
    r"|(?:OUTBOUND|INBOUND|ANY)\s+(?:@\w+\s+)?)"
    r"(?!@)(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_INSERT_EDGE = re.compile(
    r"INSERT\s+\{([^}]+)\}(?:\s+UPDATE\s+\{.*?\})?\s+IN(?:TO)?\s+(\w+)",
    re.IGNORECASE | re.DOTALL,
)
_RE_AQL_LOCAL_SYMBOLS = re.compile(
    r"(?:FOR\s+(\w+)(?:\s*,\s*(\w+))?\s+IN|LET\s+(\w+)\s*=|COLLECT\s+(\w+)\s*=)",
    re.IGNORECASE,
)
_RE_AQL_LINE_COMMENT = re.compile(r"//.*$", re.MULTILINE)
_DYNAMIC_COLLECTION = re.compile(r"^vectors_track_(hot|cold)__")

VALID_COLLECTIONS = DOCUMENT_COLLECTIONS | EDGE_COLLECTIONS

EDGE_DEFINITIONS: dict[str, dict[str, list[str]]] = {
    "file_has_state": {"from": ["library_files"], "to": ["file_states"]},
    "file_has_vectors": {"from": ["library_files"], "to": ["vectors_track_hot", "vectors_track_cold"]},
    "file_has_segment_stats": {"from": ["library_files"], "to": ["segment_scores_stats"]},
    "library_contains_file": {"from": ["libraries"], "to": ["library_files"]},
    "library_contains_folder": {"from": ["libraries"], "to": ["library_folders"]},
    "library_has_scan": {"from": ["libraries"], "to": ["library_scans"]},
    "library_has_pipeline_state": {"from": ["libraries"], "to": ["library_pipeline_states"]},
    "has_nd_id": {"from": ["navidrome_tracks"], "to": ["library_files"]},
    "has_plays": {"from": ["navidrome_tracks"], "to": ["navidrome_playcounts"]},
    "song_has_tags": {"from": ["library_files"], "to": ["tags"]},
    "model_has_output": {"from": ["ml_models"], "to": ["ml_model_outputs"]},
    "model_has_calibration": {"from": ["ml_models"], "to": ["calibration_state"]},
}


def _strip_aql_comments(query: str) -> str:
    """Remove line comments so regex scans only executable AQL."""
    return _RE_AQL_LINE_COMMENT.sub("", query)


def _extract_aql_local_symbols(query: str) -> set[str]:
    """Return local variable symbols introduced by FOR/LET/COLLECT clauses."""
    symbols: set[str] = set()
    for match in _RE_AQL_LOCAL_SYMBOLS.finditer(query):
        symbols.update(group.lower() for group in match.groups() if group is not None)
    return symbols


def _extract_traversal_collection_name(query: str, match: re.Match[str]) -> str | None:
    """Return the edge collection token following a traversal vertex expression."""
    if not any(keyword in match.group(0).upper() for keyword in ("OUTBOUND", "INBOUND", "ANY")):
        return None

    remainder = query[match.end() :]
    next_token_match = re.match(r"(?:\.\w+)?\s+(@@?\w+|\w+)", remainder)
    if next_token_match is None:
        return None

    return next_token_match.group(1)


def _extract_collection_names(query: str) -> list[str]:
    """Extract real collection names while skipping AQL locals and comments."""
    stripped_query = _strip_aql_comments(query)
    local_symbols = _extract_aql_local_symbols(stripped_query)
    collection_names: list[str] = []

    for match in _RE_COLLECTIONS.finditer(stripped_query):
        candidate = match.group(1)
        normalized_candidate = candidate.lower()

        if candidate.startswith("@"):
            continue

        if normalized_candidate in local_symbols:
            traversal_candidate = _extract_traversal_collection_name(stripped_query, match)
            if traversal_candidate is None:
                continue
            candidate = traversal_candidate
            normalized_candidate = candidate.lower()

        if candidate.startswith("@") or normalized_candidate in local_symbols:
            continue

        collection_names.append(candidate)

    return collection_names


def _resolve_edge_field_value(
    fields_str: str,
    collection: str,
    field_name: str,
    bind_vars: dict[str, Any],
) -> str:
    """Resolve an edge document field to its concrete document ID string."""
    field_match = re.search(
        rf"(?<!\w){re.escape(field_name)}\s*:\s*(@\w+|'[^']*'|\"[^\"]*\")",
        fields_str,
        re.IGNORECASE,
    )
    assert field_match is not None, f"Edge INSERT into '{collection}' missing '{field_name}' field in document"

    raw_value = field_match.group(1)
    if raw_value.startswith("@"):
        bind_key = raw_value[1:]
        assert bind_key in bind_vars, (
            f"Edge INSERT into '{collection}' missing bind_vars['{bind_key}'] for '{field_name}'"
        )
        value = bind_vars[bind_key]
    else:
        value = raw_value.strip("\"'")

    assert isinstance(value, str), (
        f"Edge INSERT into '{collection}' expects string value for '{field_name}', got {type(value).__name__}"
    )
    return value


def _matches_allowed_collection_prefix(collection_name: str, allowed_names: list[str]) -> bool:
    """Return True when a collection name matches an allowed exact or prefixed name."""
    return any(
        collection_name == allowed_name or collection_name.startswith(f"{allowed_name}__")
        for allowed_name in allowed_names
    )


class SchemaAwareMockDB:
    """MagicMock wrapper that validates AQL against schema constraints at test runtime."""

    def __init__(self) -> None:
        self._mock = MagicMock()
        self._mock.name = "test_db"
        self._mock.aql.execute.side_effect = self._validate_and_execute

    def _validate_and_execute(self, query: str, *args: Any, **kwargs: Any) -> MagicMock:
        bind_vars = kwargs.get("bind_vars") or {}
        assert isinstance(bind_vars, dict), "bind_vars must be a dict when provided"
        self._validate_collections(query)
        self._validate_edge_inserts(query, bind_vars)
        return MagicMock()

    def _validate_collections(self, query: str) -> None:
        for name in _extract_collection_names(query):
            if _DYNAMIC_COLLECTION.match(name):
                continue
            assert name in VALID_COLLECTIONS, (
                f"Unknown collection '{name}' referenced in AQL. Add it to migrations and update the whitelist."
            )

    def _validate_edge_inserts(self, query: str, bind_vars: dict[str, Any]) -> None:
        for match in _RE_INSERT_EDGE.finditer(_strip_aql_comments(query)):
            fields_str = match.group(1)
            collection = match.group(2)
            if collection not in EDGE_COLLECTIONS:
                continue

            from_val = _resolve_edge_field_value(fields_str, collection, "_from", bind_vars)
            to_val = _resolve_edge_field_value(fields_str, collection, "_to", bind_vars)

            if collection not in EDGE_DEFINITIONS:
                continue

            definition = EDGE_DEFINITIONS[collection]
            from_coll = from_val.split("/", 1)[0]
            to_coll = to_val.split("/", 1)[0]
            assert _matches_allowed_collection_prefix(from_coll, definition["from"]), (
                f"Edge '{collection}' _from collection '{from_coll}' not in valid sources {definition['from']}"
            )
            assert _matches_allowed_collection_prefix(to_coll, definition["to"]), (
                f"Edge '{collection}' _to collection '{to_coll}' not in valid targets {definition['to']}"
            )

    def __getattr__(self, name: str) -> Any:
        return getattr(self._mock, name)
