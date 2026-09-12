"""Tests for nomarr.services.domain.library_svc.songs module."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_PROCESSED,
    STATE_PROCESSED,
)
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dto.library_dto import FileTag, FileTagsResult, RetryErroredResult
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.services.domain.library_svc.songs import LibrarySongsMixin

_LIBRARY = LibraryIdentity(library_uuid="6313b0d3-d270-47a8-9e0d-21e8255107e3")
_STATE_A = SongIdentity(library=_LIBRARY, normalized_path="songs/a.flac")
_STATE_B = SongIdentity(library=_LIBRARY, normalized_path="songs/b.flac")
_STATE_C = SongIdentity(library=_LIBRARY, normalized_path="songs/c.flac")


class _ConcreteSongsMixin(LibrarySongsMixin):
    """Minimal concrete class for testing the mixin."""

    def __init__(self, db: MagicMock) -> None:
        self.db = db
        self.cfg = MagicMock()


def _make_library() -> Library:
    """Build a domain ``Library`` (natural identity) fixture."""
    return Library(name="Rock Library", root_path="/music")


class TestRetryErroredSongs:
    """Tests for retry_errored_songs."""

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.songs.transition_song_state")
    @patch(
        "nomarr.services.domain.library_svc.songs.get_errored_song_ids",
        return_value=[_STATE_A, _STATE_B],
    )
    def test_retries_all_errored_when_no_song_ids(
        self,
        mock_get_errored_song_ids: MagicMock,
        mock_transition_song_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        library = _make_library()

        result = mixin.retry_errored_songs(library)

        assert result == RetryErroredResult(retried=2)
        mock_get_errored_song_ids.assert_called_once_with(mock_db, library)
        assert mock_transition_song_state.call_args_list == [
            call(
                mock_db,
                [_STATE_A, _STATE_B],
                STATE_ERRORED,
                STATE_NOT_ERRORED,
            ),
            call(
                mock_db,
                [_STATE_A, _STATE_B],
                STATE_PROCESSED,
                STATE_NOT_PROCESSED,
            ),
        ]

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.songs.transition_song_state")
    @patch(
        "nomarr.services.domain.library_svc.songs.get_errored_song_ids",
        return_value=[_STATE_A, _STATE_B, _STATE_C],
    )
    def test_filters_to_specified_song_ids(
        self,
        mock_get_errored_song_ids: MagicMock,
        mock_transition_song_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        library = _make_library()

        mixin.retry_errored_songs(
            library,
            songs=[_STATE_A, _STATE_C],
        )

        mock_get_errored_song_ids.assert_called_once_with(mock_db, library)
        assert mock_transition_song_state.call_args_list == [
            call(
                mock_db,
                [_STATE_A, _STATE_C],
                STATE_ERRORED,
                STATE_NOT_ERRORED,
            ),
            call(
                mock_db,
                [_STATE_A, _STATE_C],
                STATE_PROCESSED,
                STATE_NOT_PROCESSED,
            ),
        ]

    @pytest.mark.unit
    @patch("nomarr.services.domain.library_svc.songs.transition_song_state")
    @patch(
        "nomarr.services.domain.library_svc.songs.get_errored_song_ids",
        return_value=[_STATE_A],
    )
    def test_calls_transition_helper_twice_for_errored_songs(
        self,
        _mock_get_errored_song_ids: MagicMock,
        mock_transition_song_state: MagicMock,
    ) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        library = _make_library()

        mixin.retry_errored_songs(library)

        assert mock_transition_song_state.call_count == 2

    @pytest.mark.unit
    def test_raises_on_invalid_library(self) -> None:
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        with (
            patch.object(mixin, "_get_library_or_error", side_effect=ValueError("not found")),
            pytest.raises(
                ValueError,
                match="not found",
            ),
        ):
            mixin.retry_errored_songs(_make_library())


class TestGetSongTags:
    """Tests for ``LibrarySongsMixin.get_song_tags``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_opaque_locator_for_semantic_identity(self) -> None:
        """A found song returns ``FileTagsResult`` whose file_id is the opaque locator token."""
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        tag = FileTag(key="genre", value="rock", tag_type="string", is_nomarr=False)

        with patch(
            "nomarr.services.domain.library_svc.songs.get_song_tags_with_path",
            return_value={"path": "/music/songs/a.flac", "tags": [tag]},
        ) as mock_get_song_tags_with_path:
            result = mixin.get_song_tags(_STATE_A, nomarr_only=True)

        assert result == FileTagsResult(
            file_id=encode_song_locator(_STATE_A),
            path="/music/songs/a.flac",
            tags=[tag],
        )
        assert result.file_id == encode_song_locator(_STATE_A)
        mock_get_song_tags_with_path.assert_called_once_with(mock_db, _STATE_A, nomarr_only=True)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_raises_value_error_when_component_result_is_falsy(self) -> None:
        """A falsy component result (missing song) raises ``ValueError``."""
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)

        with (
            patch(
                "nomarr.services.domain.library_svc.songs.get_song_tags_with_path",
                return_value={},
            ),
            pytest.raises(ValueError, match="Song not found"),
        ):
            mixin.get_song_tags(_STATE_A)


class TestReconcileLibraryPaths:
    """Tests for ``LibrarySongsMixin.reconcile_library_paths``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_delegates_to_workflow_with_expected_arguments(self) -> None:
        """Explicit policy and batch size should be forwarded unchanged."""
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        mixin.cfg.library_root = "/music"
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
            "nomarr.services.domain.library_svc.songs.reconcile_library_paths_workflow",
            return_value=expected_result,
        ) as mock_reconcile_library_paths_workflow:
            result = mixin.reconcile_library_paths(
                library,
                policy="delete_invalid",
                batch_size=250,
            )

        assert result is expected_result
        mock_reconcile_library_paths_workflow.assert_called_once_with(
            db=mock_db,
            library=library,
            library_root="/music",
            policy="delete_invalid",
            batch_size=250,
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_uses_default_policy_and_batch_size(self) -> None:
        """Omitted args should default to mark_invalid and batch size 1000."""
        mock_db = MagicMock()
        mixin = _ConcreteSongsMixin(mock_db)
        mixin.cfg.library_root = "/music"
        library = _make_library()
        expected_result = {
            "total_files": 0,
            "valid_files": 0,
            "invalid_config": 0,
            "not_found": 0,
            "unknown_status": 0,
            "deleted_files": 0,
            "errors": 0,
        }

        with patch(
            "nomarr.services.domain.library_svc.songs.reconcile_library_paths_workflow",
            return_value=expected_result,
        ) as mock_reconcile_library_paths_workflow:
            result = mixin.reconcile_library_paths(library)

        assert result is expected_result
        mock_reconcile_library_paths_workflow.assert_called_once_with(
            db=mock_db,
            library=library,
            library_root="/music",
            policy="mark_invalid",
            batch_size=1000,
        )
