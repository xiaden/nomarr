"""Tests for edge INSERT completeness checks."""

from __future__ import annotations

import re

import pytest

from .conftest import (
    _PERSISTENCE_DATABASE_ROOT,
    _RE_INSERT_EDGE,
    EDGE_COLLECTIONS,
    _find_edge_insert_violations,
    _format_edge_insert_violations,
)


class TestEdgeInsertDetection:
    """Unit tests for the core detection logic used by _find_edge_insert_violations.

    _find_edge_insert_violations couples its filesystem scan to _REPO_ROOT, making
    true end-to-end isolation via tmp_path impractical. These tests verify the
    underlying regex + field-presence logic that drives all violation decisions.
    """

    @staticmethod
    def _detect(aql: str) -> list[tuple[str, str]]:
        """Apply the _find_edge_insert_violations detection loop to a raw AQL string."""
        results = []
        for match in _RE_INSERT_EDGE.finditer(aql):
            doc, coll = match.groups()
            if coll.lower() not in EDGE_COLLECTIONS:
                continue
            missing = []
            if re.search(r"(?<!\w)_from\s*:", doc) is None:
                missing.append("_from")
            if re.search(r"(?<!\w)_to\s*:", doc) is None:
                missing.append("_to")
            if missing:
                results.append((coll, ", ".join(missing)))
        return results

    @pytest.mark.unit
    def test_complete_edge_insert_not_flagged(self) -> None:
        """Edge INSERT with both _from and _to produces no violation."""
        assert self._detect("INSERT {_from: @a, _to: @b} INTO song_has_tags") == []

    @pytest.mark.unit
    def test_edge_insert_missing_from_is_flagged(self) -> None:
        """Edge INSERT missing _from is detected as a violation."""
        violations = self._detect("INSERT {_to: @b} INTO song_has_tags")
        assert len(violations) == 1
        assert "_from" in violations[0][1]

    @pytest.mark.unit
    def test_edge_insert_missing_to_is_flagged(self) -> None:
        """Edge INSERT missing _to is detected as a violation."""
        violations = self._detect("INSERT {_from: @a} INTO song_has_tags")
        assert len(violations) == 1
        assert "_to" in violations[0][1]

    @pytest.mark.unit
    def test_non_edge_collection_insert_not_flagged(self) -> None:
        """INSERT into a document collection (not in EDGE_COLLECTIONS) is not flagged."""
        assert self._detect("INSERT {_key: 'x'} INTO tags") == []


@pytest.mark.unit
def test_edge_inserts_have_from_and_to() -> None:
    """Persistence edge INSERT and UPSERT documents should include `_from` and `_to`."""
    violations = _find_edge_insert_violations(_PERSISTENCE_DATABASE_ROOT)
    if violations:
        pytest.fail(_format_edge_insert_violations(violations))
