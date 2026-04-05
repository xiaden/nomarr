"""Tests for ``nomarr.interfaces.api.types.library_types`` request models."""

from __future__ import annotations

import pytest

from nomarr.interfaces.api.types.library_types import CreateLibraryRequest, UpdateLibraryRequest


@pytest.mark.unit
class TestCreateLibraryRequest:
    """Tests for ``CreateLibraryRequest`` defaults and overrides."""

    def test_file_write_mode_defaults_to_full(self) -> None:
        """Create requests should default to the full file write mode."""
        request = CreateLibraryRequest(root_path="/music")

        assert request.file_write_mode == "full"

    def test_file_write_mode_can_be_set(self) -> None:
        """Create requests should accept an explicit file write mode."""
        request = CreateLibraryRequest(root_path="/music", file_write_mode="minimal")

        assert request.file_write_mode == "minimal"


@pytest.mark.unit
class TestUpdateLibraryRequest:
    """Tests for ``UpdateLibraryRequest`` defaults and overrides."""

    def test_file_write_mode_defaults_to_none(self) -> None:
        """Update requests should default file_write_mode to ``None``."""
        request = UpdateLibraryRequest()

        assert request.file_write_mode is None

    def test_file_write_mode_can_be_set(self) -> None:
        """Update requests should accept an explicit file write mode."""
        request = UpdateLibraryRequest(file_write_mode="none")

        assert request.file_write_mode == "none"
