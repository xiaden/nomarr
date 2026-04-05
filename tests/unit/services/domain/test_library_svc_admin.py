"""Tests for ``nomarr.services.domain.library_svc.admin``."""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dto.library_dto import LibraryDict
from nomarr.services.domain.library_svc.admin import LibraryAdminMixin


class _ConcreteAdminMixin(LibraryAdminMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock, cfg: MagicMock) -> None:
        self.db = db
        self.cfg = cfg


def _library_record(*, file_write_mode: str = "full") -> dict[str, Any]:
    """Build a valid library record for ``LibraryDict`` construction."""
    return {
        "_id": "libraries/1",
        "_key": "1",
        "_rev": "_rev1",
        "name": "Rock Library",
        "root_path": "/music/rock",
        "is_enabled": True,
        "created_at": 1,
        "updated_at": 2,
        "watch_mode": "off",
        "file_write_mode": file_write_mode,
    }


def _library_dto(*, file_write_mode: str = "full") -> LibraryDict:
    """Build a ``LibraryDict`` instance for assertions."""
    return LibraryDict(**cast("dict[str, Any]", _library_record(file_write_mode=file_write_mode)))


class TestCreateLibrary:
    """Tests for ``LibraryAdminMixin.create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_passes_file_write_mode(self) -> None:
        """Explicit file_write_mode should be forwarded to the component call."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with (
            patch.object(
                mixin,
                "_get_library_or_error",
                return_value=_library_record(file_write_mode="minimal"),
            ),
            patch(
                "nomarr.services.domain.library_svc.admin.create_library",
                return_value="libraries/1",
            ) as mock_create_library,
        ):
            result = mixin.create_library(
                name="Rock Library",
                root_path="rock",
                file_write_mode="minimal",
            )

        mock_create_library.assert_called_once_with(
            db=mock_db,
            base_library_root="/music",
            name="Rock Library",
            root_path="rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="minimal",
        )
        assert result == _library_dto(file_write_mode="minimal")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_default_file_write_mode_is_full(self) -> None:
        """Omitted file_write_mode should default to ``full``."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()),
            patch(
                "nomarr.services.domain.library_svc.admin.create_library",
                return_value="libraries/1",
            ) as mock_create_library,
        ):
            result = mixin.create_library(
                name="Rock Library",
                root_path="rock",
            )

        mock_create_library.assert_called_once_with(
            db=mock_db,
            base_library_root="/music",
            name="Rock Library",
            root_path="rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
        )
        assert result == _library_dto()


class TestUpdateLibrary:
    """Tests for ``LibraryAdminMixin.update_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_passes_file_write_mode_to_metadata(self) -> None:
        """Explicit file_write_mode should be forwarded to metadata updates."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        expected_result = _library_dto(file_write_mode="none")

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()),
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library("libraries/1", file_write_mode="none")

        mock_update_library_metadata.assert_called_once_with(
            "libraries/1",
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode="none",
        )
        mock_get_library.assert_called_once_with("libraries/1")
        assert result == expected_result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_skips_metadata_when_only_none_values(self) -> None:
        """Metadata update should be skipped when every optional field is ``None``."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        expected_result = _library_dto()

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()) as mock_get_library_or_error,
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library(
                "libraries/1",
                name=None,
                root_path=None,
                is_enabled=None,
                watch_mode=None,
                file_write_mode=None,
            )

        mock_get_library_or_error.assert_called_once_with("libraries/1")
        mock_update_library_metadata.assert_not_called()
        mock_get_library.assert_called_once_with("libraries/1")
        assert result == expected_result
