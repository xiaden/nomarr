"""Tests for ``nomarr.workflows.library.reconcile_paths_wf``."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.library.song_query_types import HydratedSong
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_dataclass import Song
from nomarr.workflows.library.reconcile_paths_wf import reconcile_library_paths_workflow


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name="Rock Library", root_path="/music")


def _hydrated(path: str) -> HydratedSong:
    """Build the semantic ``HydratedSong`` a paged library read returns."""
    return HydratedSong(
        song=Song(
            path=path,
            normalized_path=path.lstrip("/"),
            file_size=0,
            modified_time=0,
            duration_seconds=None,
            chromaprint=None,
            needs_tagging=False,
            is_valid=True,
            tagged=False,
            calibration_hash=None,
            write_claimed_by=None,
            last_tagged_at=None,
            scanned_at=None,
            created_at=0,
        ),
        metadata={},
    )


class TestRealReconcileLibraryPathsWorkflow:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_real_component_delete_invalid_is_config_semantic_only(self) -> None:
        """The workflow/component path deletes only config-invalid rows."""
        from nomarr.helpers.dto.path_dto import LibraryPath
        from nomarr.helpers.fs_contract import FsFact

        db = MagicMock()
        library = _make_library()
        rows = [
            HydratedSong(
                song=Song(
                    path="/config",
                    normalized_path="config",
                    file_size=0,
                    modified_time=0,
                    duration_seconds=None,
                    chromaprint=None,
                    needs_tagging=False,
                    is_valid=True,
                    tagged=False,
                    calibration_hash=None,
                    write_claimed_by=None,
                    last_tagged_at=None,
                    scanned_at=None,
                    created_at=0,
                ),
                metadata={},
            ),
            HydratedSong(
                song=Song(
                    path="/missing",
                    normalized_path="missing",
                    file_size=0,
                    modified_time=0,
                    duration_seconds=None,
                    chromaprint=None,
                    needs_tagging=False,
                    is_valid=True,
                    tagged=False,
                    calibration_hash=None,
                    write_claimed_by=None,
                    last_tagged_at=None,
                    scanned_at=None,
                    created_at=0,
                ),
                metadata={},
            ),
        ]
        db.library.remove_song_by_path.side_effect = lambda _path, _lib: rows.__setitem__(0, rows[1])
        list_calls = 0

        def list_rows(*_args: object, **_kwargs: object) -> tuple[list[HydratedSong], int]:
            nonlocal list_calls
            list_calls += 1
            return (rows, len(rows)) if list_calls == 1 else ([], 0)

        paths = {
            "/config": LibraryPath("config", Path("/music/config"), "Rock Library", "invalid_config", "bad config"),
            "/missing": LibraryPath("missing", Path("/music/missing"), "Rock Library", "not_found", "missing"),
            "/storage": LibraryPath(
                "storage",
                Path("/music/storage"),
                "Rock Library",
                "unknown",
                "unavailable",
                FsFact(kind="storage_unavailable", presence="unknown", errno=None),
            ),
        }
        with (
            patch("nomarr.components.library.reconcile_paths_comp.get_library_stats", return_value={"total_files": 2}),
            patch(
                "nomarr.components.library.reconcile_paths_comp.list_songs",
                side_effect=list_rows,
            ),
            patch(
                "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
                side_effect=lambda **kwargs: paths[kwargs["stored_path"]],
            ),
        ):
            result = reconcile_library_paths_workflow(db, library, "/music", policy="delete_invalid")

        assert result["deleted_files"] == 1
        assert result["not_found"] == 1
        db.library.remove_song_by_path.assert_called_once_with("/config", library)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_real_component_delete_invalid_preserves_filesystem_derived_row(self) -> None:
        """A storage-unavailable row is reported and preserved, never deleted.

        The real workflow calls the real component; only the DB boundary, the
        paged read, and path resolution are stubbed. ``remove_song_by_path`` must
        fire only for the genuine config/semantic row, even when a
        filesystem-derived row and a legacy ``not_found`` row share the batch.
        """
        from nomarr.helpers.dto.path_dto import LibraryPath
        from nomarr.helpers.fs_contract import FsFact

        db = MagicMock()
        library = _make_library()
        rows = [_hydrated("/config"), _hydrated("/missing"), _hydrated("/storage")]
        list_calls = 0

        def list_rows(*_args: object, **_kwargs: object) -> tuple[list[HydratedSong], int]:
            nonlocal list_calls
            list_calls += 1
            return (list(rows), len(rows)) if list_calls == 1 else ([], 0)

        def remove_song(path: str, _library: Library) -> None:
            rows[:] = [row for row in rows if row.song.path != path]

        db.library.remove_song_by_path.side_effect = remove_song

        paths = {
            "/config": LibraryPath("config", Path("/music/config"), "Rock Library", "invalid_config", "bad config"),
            "/missing": LibraryPath("missing", Path("/music/missing"), "Rock Library", "not_found", "missing"),
            "/storage": LibraryPath(
                "storage",
                Path("/music/storage"),
                "Rock Library",
                "unknown",
                "unavailable",
                FsFact(kind="storage_unavailable", presence="unknown", errno=None),
            ),
        }
        with (
            patch("nomarr.components.library.reconcile_paths_comp.get_library_stats", return_value={"total_files": 3}),
            patch("nomarr.components.library.reconcile_paths_comp.list_songs", side_effect=list_rows),
            patch(
                "nomarr.components.library.reconcile_paths_comp.build_library_path_from_db",
                side_effect=lambda **kwargs: paths[kwargs["stored_path"]],
            ),
        ):
            result = reconcile_library_paths_workflow(db, library, "/music", policy="delete_invalid")

        assert result["deleted_files"] == 1
        assert result["invalid_config"] == 1
        assert result["not_found"] == 1
        assert result["unknown_status"] == 1
        db.library.remove_song_by_path.assert_called_once_with("/config", library)
        assert [row.song.path for row in rows] == ["/missing", "/storage"]


class TestReconcileLibraryPathsWorkflow:
    """Tests for ``reconcile_library_paths_workflow``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize("library_root", [None, ""])
    def test_raises_when_library_root_missing(self, library_root: str | None) -> None:
        """Missing library root should raise ValueError before delegation."""
        with pytest.raises(ValueError, match="Library root not configured"):
            reconcile_library_paths_workflow(
                db=MagicMock(),
                library=_make_library(),
                library_root=library_root,
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_when_policy_invalid(self) -> None:
        """Unknown reconciliation policy should raise ValueError."""
        with pytest.raises(ValueError, match="Invalid policy 'bad_policy'"):
            reconcile_library_paths_workflow(
                db=MagicMock(),
                library=_make_library(),
                library_root="/music",
                policy="bad_policy",  # type: ignore[arg-type]
            )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_component_with_expected_arguments(self) -> None:
        """Valid calls should forward the Library, policy, and batch_size unchanged."""
        mock_db = MagicMock()
        library = _make_library()
        expected_result = {
            "total_files": 10,
            "valid_files": 8,
            "invalid_config": 1,
            "not_found": 1,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        with patch(
            "nomarr.workflows.library.reconcile_paths_wf.reconcile_library_paths",
            return_value=expected_result,
        ) as mock_reconcile_library_paths:
            result = reconcile_library_paths_workflow(
                db=mock_db,
                library=library,
                library_root="/music",
                policy="delete_invalid",
                batch_size=250,
            )

        assert result is expected_result
        mock_reconcile_library_paths.assert_called_once_with(
            db=mock_db,
            library=library,
            policy="delete_invalid",
            batch_size=250,
        )
