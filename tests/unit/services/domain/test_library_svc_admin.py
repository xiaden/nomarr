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
        self.file_watcher_service = None


def _library_record(*, file_write_mode: str = "full", library_auto_write: bool = False) -> dict[str, Any]:
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
        "library_auto_write": library_auto_write,
    }


def _library_dto(*, file_write_mode: str = "full", library_auto_write: bool = False) -> LibraryDict:
    """Build a ``LibraryDict`` instance for assertions."""
    return LibraryDict(
        **cast(
            "dict[str, Any]",
            _library_record(file_write_mode=file_write_mode, library_auto_write=library_auto_write),
        )
    )


class TestCreateLibrary:
    """Tests for ``LibraryAdminMixin.create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_passes_file_write_mode(self) -> None:
        """Explicit file_write_mode should be forwarded to the component call."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mock_cfg.models_dir = "/models"
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
            patch(
                "nomarr.services.domain.library_svc.admin.provision_vectors_track_for_library",
            ) as mock_provision_vectors_track,
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
            library_auto_write=False,
        )
        mock_provision_vectors_track.assert_called_once_with(mock_db.db, "/models", "1")
        assert result == _library_dto(file_write_mode="minimal")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_default_file_write_mode_is_full(self) -> None:
        """Omitted file_write_mode should default to ``full``."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mock_cfg.models_dir = "/models"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()),
            patch(
                "nomarr.services.domain.library_svc.admin.create_library",
                return_value="libraries/1",
            ) as mock_create_library,
            patch(
                "nomarr.services.domain.library_svc.admin.provision_vectors_track_for_library",
            ) as mock_provision_vectors_track,
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
            library_auto_write=False,
        )
        mock_provision_vectors_track.assert_called_once_with(mock_db.db, "/models", "1")
        assert result == _library_dto()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_calls_provision_vectors_track(self) -> None:
        """Library creation should provision vectors for the new library key."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mock_cfg.models_dir = "/models"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()),
            patch(
                "nomarr.services.domain.library_svc.admin.create_library",
                return_value="libraries/1",
            ),
            patch(
                "nomarr.services.domain.library_svc.admin.provision_vectors_track_for_library",
            ) as mock_provision_vectors_track,
        ):
            result = mixin.create_library(name="Rock Library", root_path="rock")

        mock_provision_vectors_track.assert_called_once_with(mock_db.db, "/models", "1")
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
            library_auto_write=None,
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
                library_auto_write=None,
            )

        mock_get_library_or_error.assert_called_once_with("libraries/1")
        mock_update_library_metadata.assert_not_called()
        mock_get_library.assert_called_once_with("libraries/1")
        assert result == expected_result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_passes_library_auto_write_to_metadata(self) -> None:
        """Explicit library_auto_write should be forwarded to metadata updates."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        expected_result = _library_dto(library_auto_write=True)

        with (
            patch.object(mixin, "_get_library_or_error", return_value=_library_record()),
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library("libraries/1", library_auto_write=True)

        mock_update_library_metadata.assert_called_once_with(
            "libraries/1",
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode=None,
            library_auto_write=True,
        )
        mock_get_library.assert_called_once_with("libraries/1")
        assert result == expected_result


class TestDeleteLibrary:
    """Tests for ``LibraryAdminMixin.delete_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_without_watcher_service(self) -> None:
        """Delete should still delegate when no watcher service is configured."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            return_value=True,
        ) as mock_delete_library:
            result = mixin.delete_library("libraries/1")

        assert result is True
        mock_delete_library.assert_called_once_with(db=mixin.db, library_id="libraries/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_stop_watcher_when_library_not_observed(self) -> None:
        """Watcher stop should be skipped when the library is not being observed."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.file_watcher_service = MagicMock()
        mixin.file_watcher_service.observers = {"libraries/other": object()}

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            return_value=False,
        ) as mock_delete_library:
            result = mixin.delete_library("libraries/1")

        assert result is False
        mixin.file_watcher_service.stop_watching_library.assert_not_called()
        mock_delete_library.assert_called_once_with(db=mixin.db, library_id="libraries/1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_stops_watcher_before_deleting_observed_library(self) -> None:
        """Observed libraries should stop watching before persistence delete runs."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.file_watcher_service = MagicMock()
        mixin.file_watcher_service.observers = {"libraries/1": object()}
        call_order: list[str] = []

        def _delete_library(*, db: MagicMock, library_id: str) -> bool:
            call_order.append("delete")
            return True

        def _stop_watching_library(library_id: str) -> None:
            assert library_id == "libraries/1"
            call_order.append("stop")

        mixin.file_watcher_service.stop_watching_library.side_effect = _stop_watching_library

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            side_effect=_delete_library,
        ) as mock_delete_library:
            result = mixin.delete_library("libraries/1")

        assert result is True
        assert call_order == ["stop", "delete"]
        mixin.file_watcher_service.stop_watching_library.assert_called_once_with("libraries/1")
        mock_delete_library.assert_called_once_with(db=mixin.db, library_id="libraries/1")
