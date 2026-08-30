"""Tests for ``nomarr.services.domain.library_svc.admin``."""

from __future__ import annotations

from typing import Literal
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import DuplicateEntityError
from nomarr.services.domain.library_svc.admin import LibraryAdminMixin
from nomarr.services.domain.library_svc.task_ids import library_task_id, write_tags_task_id


class _ConcreteAdminMixin(LibraryAdminMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock, cfg: MagicMock) -> None:
        self.db = db
        self.cfg = cfg
        self.file_watcher_service = None
        self.background_tasks = None


def _make_library(
    *,
    file_write_mode: Literal["none", "minimal", "full"] = "full",
    library_auto_write: bool = False,
) -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(
        name="Rock Library",
        root_path="/music/rock",
        is_enabled=True,
        watch_mode="off",
        file_write_mode=file_write_mode,
        library_auto_write=library_auto_write,
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

        with patch(
            "nomarr.services.domain.library_svc.admin.create_library",
            return_value=_make_library(file_write_mode="minimal"),
        ) as mock_create_library:
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
        assert result == _make_library(file_write_mode="minimal")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_default_file_write_mode_is_full(self) -> None:
        """Omitted file_write_mode should default to ``full``."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mock_cfg.models_dir = "/models"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with patch(
            "nomarr.services.domain.library_svc.admin.create_library",
            return_value=_make_library(),
        ) as mock_create_library:
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
        assert result == _make_library()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_create_library_does_not_provision_vectors(self) -> None:
        """Library creation no longer provisions vector collections (per-backbone is done at schema setup)."""
        mock_db = MagicMock()
        mock_cfg = MagicMock()
        mock_cfg.library_root = "/music"
        mock_cfg.models_dir = "/models"
        mixin = _ConcreteAdminMixin(mock_db, mock_cfg)

        with patch(
            "nomarr.services.domain.library_svc.admin.create_library",
            return_value=_make_library(),
        ):
            result = mixin.create_library(name="Rock Library", root_path="rock")

        assert result == _make_library()


class TestUpdateLibrary:
    """Tests for ``LibraryAdminMixin.update_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_maps_duplicate_name_with_root_path_to_value_error(self) -> None:
        """A combined root/name update should expose a friendly collision error."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        library = _make_library()

        with (
            patch.object(mixin, "_get_library_or_error", return_value=library),
            patch(
                "nomarr.services.domain.library_svc.admin.resolve_library_root",
                return_value="/music/new",
            ),
            patch(
                "nomarr.services.domain.library_svc.admin.update_library_record",
                side_effect=DuplicateEntityError("duplicate"),
            ),
            pytest.raises(ValueError, match="Library name already exists: Existing"),
        ):
            mixin.update_library(library, name="Existing", root_path="new")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_passes_file_write_mode_to_metadata(self) -> None:
        """Explicit file_write_mode should be forwarded to metadata updates."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        library = _make_library()
        expected_result = _make_library(file_write_mode="none")

        with (
            patch.object(mixin, "_get_library_or_error", return_value=library) as mock_get_library_or_error,
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library(library, file_write_mode="none")

        mock_get_library_or_error.assert_called_once_with(library)
        mock_update_library_metadata.assert_called_once_with(
            library,
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode="none",
            library_auto_write=None,
        )
        mock_get_library.assert_called_once_with(library)
        assert result == expected_result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_skips_metadata_when_only_none_values(self) -> None:
        """Metadata update should be skipped when every optional field is ``None``."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        library = _make_library()
        expected_result = _make_library()

        with (
            patch.object(mixin, "_get_library_or_error", return_value=library) as mock_get_library_or_error,
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library(
                library,
                name=None,
                root_path=None,
                is_enabled=None,
                watch_mode=None,
                file_write_mode=None,
                library_auto_write=None,
            )

        mock_get_library_or_error.assert_called_once_with(library)
        mock_update_library_metadata.assert_not_called()
        mock_get_library.assert_called_once_with(library)
        assert result == expected_result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_update_library_passes_library_auto_write_to_metadata(self) -> None:
        """Explicit library_auto_write should be forwarded to metadata updates."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        library = _make_library()
        expected_result = _make_library(library_auto_write=True)

        with (
            patch.object(mixin, "_get_library_or_error", return_value=library) as mock_get_library_or_error,
            patch.object(mixin, "update_library_metadata") as mock_update_library_metadata,
            patch.object(mixin, "get_library", return_value=expected_result) as mock_get_library,
        ):
            result = mixin.update_library(library, library_auto_write=True)

        mock_get_library_or_error.assert_called_once_with(library)
        mock_update_library_metadata.assert_called_once_with(
            library,
            name=None,
            is_enabled=None,
            watch_mode=None,
            file_write_mode=None,
            library_auto_write=True,
        )
        mock_get_library.assert_called_once_with(library)
        assert result == expected_result


class TestDeleteLibrary:
    """Tests for ``LibraryAdminMixin.delete_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_without_watcher_service(self) -> None:
        """Delete should still delegate when no watcher service is configured."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        library = _make_library()

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            return_value=True,
        ) as mock_delete_library:
            result = mixin.delete_library(library)

        assert result is True
        mock_delete_library.assert_called_once_with(db=mixin.db, library=library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_does_not_stop_watcher_when_library_not_observed(self) -> None:
        """Watcher stop should be skipped when the library is not being observed."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.file_watcher_service = MagicMock()
        mixin.file_watcher_service.observers = {"Other Library": object()}
        library = _make_library()

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            return_value=False,
        ) as mock_delete_library:
            result = mixin.delete_library(library)

        assert result is False
        mixin.file_watcher_service.stop_watching_library.assert_not_called()
        mock_delete_library.assert_called_once_with(db=mixin.db, library=library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_stops_watcher_before_deleting_observed_library(self) -> None:
        """Observed libraries should stop watching before persistence delete runs."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.file_watcher_service = MagicMock()
        mixin.file_watcher_service.observers = {"Rock Library": object()}
        library = _make_library()
        call_order: list[str] = []

        def _delete_library(*, db: MagicMock, library: Library) -> bool:
            call_order.append("delete")
            return True

        def _stop_watching_library(library_name: str) -> None:
            call_order.append("stop")

        mixin.file_watcher_service.stop_watching_library.side_effect = _stop_watching_library

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            side_effect=_delete_library,
        ) as mock_delete_library:
            result = mixin.delete_library(library)

        assert result is True
        assert call_order == ["stop", "delete"]
        mixin.file_watcher_service.stop_watching_library.assert_called_once_with("Rock Library")
        mock_delete_library.assert_called_once_with(db=mixin.db, library=library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_quiesces_scan_and_write_tasks_before_delete(self) -> None:
        """Delete should cancel+join the scan and write tasks before removing the library."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.background_tasks = MagicMock()
        mixin.background_tasks.cancel_and_join.return_value = True
        library = _make_library()

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            return_value=True,
        ) as mock_delete_library:
            result = mixin.delete_library(library)

        assert result is True
        scan_id = library_task_id(library, "scan")
        write_id = write_tags_task_id(library)
        called_task_ids = [call.args[0] for call in mixin.background_tasks.cancel_and_join.call_args_list]
        assert called_task_ids == [scan_id, write_id]
        mock_delete_library.assert_called_once_with(db=mixin.db, library=library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rejects_deletion_when_scan_task_does_not_quiesce(self) -> None:
        """Delete should raise when the scan task refuses to stop."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.background_tasks = MagicMock()
        mixin.background_tasks.cancel_and_join.side_effect = [False, True]
        library = _make_library()

        with (
            patch("nomarr.services.domain.library_svc.admin.delete_library") as mock_delete_library,
            pytest.raises(RuntimeError, match="scan task is still running"),
        ):
            mixin.delete_library(library)

        mock_delete_library.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_rejects_deletion_when_write_task_does_not_quiesce(self) -> None:
        """Delete should raise when the write task refuses to stop."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.background_tasks = MagicMock()
        mixin.background_tasks.cancel_and_join.side_effect = [True, False]
        library = _make_library()

        with (
            patch("nomarr.services.domain.library_svc.admin.delete_library") as mock_delete_library,
            pytest.raises(RuntimeError, match="tag-write task is still running"),
        ):
            mixin.delete_library(library)

        mock_delete_library.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_full_ordered_delete_stops_watcher_then_quiesces_then_deletes(self) -> None:
        """Delete must run watcher-stop → quiesce (scan, write) → delete in order."""
        mixin = _ConcreteAdminMixin(MagicMock(), MagicMock())
        mixin.file_watcher_service = MagicMock()
        mixin.file_watcher_service.observers = {"Rock Library": object()}
        mixin.background_tasks = MagicMock()
        library = _make_library()
        call_order: list[str] = []

        def _stop_watching_library(library_name: str) -> None:
            call_order.append("stop")

        def _cancel_and_join(task_id: str, timeout: float | None = None) -> bool:
            call_order.append(f"quiesce:{task_id}")
            return True

        def _delete_library(*, db: MagicMock, library: Library) -> bool:
            call_order.append("delete")
            return True

        mixin.file_watcher_service.stop_watching_library.side_effect = _stop_watching_library
        mixin.background_tasks.cancel_and_join.side_effect = _cancel_and_join

        with patch(
            "nomarr.services.domain.library_svc.admin.delete_library",
            side_effect=_delete_library,
        ):
            result = mixin.delete_library(library)

        assert result is True
        scan_id = library_task_id(library, "scan")
        write_id = write_tags_task_id(library)
        assert call_order == ["stop", f"quiesce:{scan_id}", f"quiesce:{write_id}", "delete"]
