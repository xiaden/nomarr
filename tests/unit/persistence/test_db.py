"""Unit tests for ``nomarr.persistence.db`` collection-first surface guard."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.db import Database

_ALL_ROOTS = ("get", "insert", "update", "upsert", "delete", "count", "aggregate", "truncate")


def _compliant_mock() -> MagicMock:
    """Return a mock that exposes all required collection-first roots."""
    mock = MagicMock()
    for root in _ALL_ROOTS:
        setattr(mock, root, MagicMock())
    return mock


@pytest.mark.unit
@pytest.mark.mocked
class TestAssertCollectionFirstSurface:
    """Tests for ``Database._assert_collection_first_surface``."""

    def test_passes_when_all_roots_present(self) -> None:
        """Does not raise when a collection exposes all required roots."""
        instance = _compliant_mock()
        # Should not raise
        Database._assert_collection_first_surface("library_files", instance)

    def test_raises_type_error_when_roots_missing(self) -> None:
        """Raises TypeError listing missing roots when a collection is non-compliant."""
        instance = MagicMock(spec=[])  # exposes no attributes

        with pytest.raises(TypeError, match="library_files"):
            Database._assert_collection_first_surface("library_files", instance)

    def test_error_message_names_missing_roots(self) -> None:
        """TypeError message includes each missing root name."""
        instance = MagicMock(spec=["get", "insert"])  # missing most roots

        with pytest.raises(TypeError) as exc_info:
            Database._assert_collection_first_surface("my_col", instance)

        message = str(exc_info.value)
        for root in ("update", "upsert", "delete", "count", "aggregate", "truncate"):
            assert root in message

    def test_passes_for_collection_with_extra_attributes(self) -> None:
        """Extra attributes beyond the required roots do not affect the guard."""
        instance = _compliant_mock()
        instance.extra_method = MagicMock()

        Database._assert_collection_first_surface("tags", instance)

    def test_raises_when_single_root_missing(self) -> None:
        """Raises TypeError even if only one root is absent."""
        instance = MagicMock(spec=list(_ALL_ROOTS[:-1]))  # all but "truncate"

        with pytest.raises(TypeError, match="truncate"):
            Database._assert_collection_first_surface("locks", instance)
