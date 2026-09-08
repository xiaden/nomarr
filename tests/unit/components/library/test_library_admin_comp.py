"""Tests for ``nomarr.components.library.library_admin_comp``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.library.library_admin_comp import clear_library_data, create_library, delete_library
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.exceptions import DuplicateEntityError


@pytest.fixture(autouse=True)
def pipeline_state_shims(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep tests focused on admin behavior while production code uses helper seams."""
    # No shims needed - pipeline state is now handled via PIPELINE_DEFAULTS passed to create_library_record


class TestCreateLibrary:
    """Tests for ``create_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_file_write_mode_to_db(self) -> None:
        """Explicit file_write_mode should be forwarded to persistence."""
        mock_db = MagicMock()
        mock_db.library.get_scan.return_value = None

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                return_value="libraries/1",
            ) as create_record,
        ):
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
                file_write_mode="minimal",
            )

        assert result == "libraries/1"
        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="minimal",
            library_auto_write=False,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_default_file_write_mode_is_full(self) -> None:
        """Default file_write_mode should remain ``full`` when omitted."""
        mock_db = MagicMock()
        mock_db.library.get_scan.return_value = None

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                return_value="libraries/1",
            ) as create_record,
        ):
            result = create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )

        assert result == "libraries/1"
        create_record.assert_called_once_with(
            mock_db,
            name="Rock Library",
            root_path="/music/rock",
            is_enabled=True,
            watch_mode="off",
            file_write_mode="full",
            library_auto_write=False,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_concurrent_duplicate_name_raises_value_error(self) -> None:
        """A DB-enforced duplicate-name race surfaces as ValueError, not a leak."""
        mock_db = MagicMock()

        with (
            patch(
                "nomarr.components.library.library_admin_comp.get_base_library_root",
                return_value="/music",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.normalize_library_root",
                return_value="/music/rock",
            ),
            patch("nomarr.components.library.library_admin_comp.ensure_no_overlapping_library_root"),
            patch(
                "nomarr.components.library.library_admin_comp._resolve_library_name",
                return_value="Rock Library",
            ),
            patch(
                "nomarr.components.library.library_admin_comp.create_library_record",
                side_effect=DuplicateEntityError("duplicate"),
            ),
            pytest.raises(ValueError, match="Library name already exists"),
        ):
            create_library(
                db=mock_db,
                base_library_root="/configured-music",
                name=None,
                root_path="rock",
            )


class TestDeleteLibrary:
    """Tests for ``delete_library``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_false_when_library_not_found(self) -> None:
        """Missing libraries should short-circuit without any deletion."""
        mock_db = MagicMock()
        library = Library(name="Missing", root_path="/missing")

        with patch(
            "nomarr.components.library.library_admin_comp.get_library_record",
            return_value=None,
        ) as get_library_record_mock:
            result = delete_library(mock_db, library)

        assert result is False
        get_library_record_mock.assert_called_once_with(mock_db, library)
        mock_db.library.delete_library.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_deletes_library_and_returns_true(self) -> None:
        """Existing libraries should delegate cascade to db.library.remove_library and return True."""
        mock_db = MagicMock()
        library = Library(name="Main Library", root_path="/music")

        with patch(
            "nomarr.components.library.library_admin_comp.get_library_record",
            return_value=library,
        ) as get_library_record_mock:
            result = delete_library(mock_db, library)

        assert result is True
        get_library_record_mock.assert_called_once_with(mock_db, library)
        mock_db.library.remove_library.assert_called_once_with(library)


class TestClearLibraryData:
    """Tests for the ``clear_library_data`` admin guard wrapper.

    Proves the two guards (missing ``library_root`` -> ValueError; active scan
    -> RuntimeError) fire BEFORE any reset work and that neither guard invokes
    the reset. Also proves the concurrency/partial-failure contract: the scan
    guard blocks admission to persistence, the success path reaches exactly one
    persistence-owned maintenance intent with no lock API, and a raised
    aggregate reset propagates rather than returning a partial success.
    """

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_missing_library_root_raises_value_error_before_any_reset(self) -> None:
        """An unset library_root must raise ValueError before any reset work runs."""
        mock_db = MagicMock()
        with (
            patch("nomarr.components.library.library_admin_comp._is_scan_running") as mock_is_scan_running,
            patch("nomarr.components.library.library_admin_comp.clear_library_song_data") as mock_reset,
            pytest.raises(ValueError) as excinfo,
        ):
            clear_library_data(db=mock_db, library_root=None)

        assert str(excinfo.value) == "Library root not configured"
        # Neither the scan check nor the reset runs when the root guard fires.
        mock_is_scan_running.assert_not_called()
        mock_reset.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_active_scan_raises_runtime_error_before_any_reset(self) -> None:
        """An active scan must raise the existing RuntimeError before any reset runs."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.library.library_admin_comp._is_scan_running",
                return_value=True,
            ),
            patch("nomarr.components.library.library_admin_comp.clear_library_song_data") as mock_reset,
            pytest.raises(RuntimeError) as excinfo,
        ):
            clear_library_data(db=mock_db, library_root="/music")

        assert str(excinfo.value) == ("Cannot clear library while scan jobs are running. Cancel scans first.")
        mock_reset.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_scan_guard_blocks_reset_from_reaching_persistence(self) -> None:
        """An active-scan guard must prevent the persistence reset intent from running."""
        mock_db = MagicMock()
        with (
            patch(
                "nomarr.components.library.library_admin_comp._is_scan_running",
                return_value=True,
            ),
            pytest.raises(RuntimeError),
        ):
            clear_library_data(db=mock_db, library_root="/music")

        # No reset call may reach the persistence-owned maintenance intent.
        mock_db.library.maintenance.reset_library_data.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_success_path_reaches_single_persistence_intent_without_lock_api(self) -> None:
        """With no guard firing, exactly one maintenance intent runs and no lock API is used."""
        mock_db = MagicMock()
        with patch(
            "nomarr.components.library.library_admin_comp._is_scan_running",
            return_value=False,
        ):
            clear_library_data(db=mock_db, library_root="/music")

        # The full component -> song-query delegation reaches exactly the one
        # persistence-owned maintenance intent (single-call component migration).
        mock_db.library.maintenance.reset_library_data.assert_called_once_with()
        assert mock_db.library.maintenance.method_calls == [call.reset_library_data()]
        # The concurrency contract is the scan guard + the repository transaction
        # boundary; no speculative application lock is created or advertised on the
        # reset path.
        lock_calls = [c for c in mock_db.method_calls if "lock" in str(c).lower()]
        assert lock_calls == []

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_aggregate_failure_propagates_not_partial_success(self) -> None:
        """A raised persistence reset must propagate (no swallowed partial-success return)."""
        mock_db = MagicMock()
        mock_db.library.maintenance.reset_library_data.side_effect = RuntimeError("reset aborted mid-way")
        with (
            patch(
                "nomarr.components.library.library_admin_comp._is_scan_running",
                return_value=False,
            ),
            pytest.raises(RuntimeError, match="reset aborted mid-way"),
        ):
            clear_library_data(db=mock_db, library_root="/music")
