"""Tests for _execute_deferred_writes in discovery_worker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_TAGGED,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.helpers.dto.processing_dto import DeferredFileWrites

_PATCH_PREFIX_SYNC = "nomarr.components.library.file_sync_comp"
_PATCH_PREFIX_PARSE = "nomarr.components.tagging.tag_parsing_comp"
_PATCH_PREFIX_STATS = "nomarr.components.ml.inference.ml_segment_stats_comp"
_PATCH_PREFIX_WORKER = "nomarr.components.workers.worker_discovery_comp"


@pytest.fixture()
def mock_db() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def minimal_writes() -> DeferredFileWrites:
    return DeferredFileWrites(
        file_id="library_files/abc",
        path="/music/test.flac",
        db_tags={"genre": "rock"},
        namespace="nom",
        tagger_version="v1",
        chromaprint=None,
        raw_segments={},
        ml_edges=None,
    )


class TestExecuteDeferredWritesSuccess:
    """Tests for successful _execute_deferred_writes execution."""

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATS}.compute_segment_stats")
    @patch(f"{_PATCH_PREFIX_SYNC}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_sets_vectors_extracted_on_success(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_compute_stats: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import (
            _execute_deferred_writes,
        )

        mock_parse.return_value = {"genre": ["rock"]}

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_db.file_states.transition.assert_any_call(["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED)
        mock_db.file_states.transition.assert_any_call(
            ["library_files/abc"],
            STATE_NOT_VECTORS_EXTRACTED,
            STATE_VECTORS_EXTRACTED,
        )
        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATS}.compute_segment_stats")
    @patch(f"{_PATCH_PREFIX_SYNC}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_does_not_set_errored_on_success(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_compute_stats: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import (
            _execute_deferred_writes,
        )

        mock_parse.return_value = {}

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        assert mock_db.file_states.transition.call_count == 2
        mock_db.file_states.transition.assert_any_call(["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED)
        mock_db.file_states.transition.assert_any_call(
            ["library_files/abc"],
            STATE_NOT_VECTORS_EXTRACTED,
            STATE_VECTORS_EXTRACTED,
        )
        mock_db.file_states.transition.assert_has_calls(
            [
                ((["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED),),
                ((["library_files/abc"], STATE_NOT_VECTORS_EXTRACTED, STATE_VECTORS_EXTRACTED),),
            ],
            any_order=True,
        )


class TestExecuteDeferredWritesFailure:
    """Tests for _execute_deferred_writes when writes fail."""

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATS}.compute_segment_stats")
    @patch(f"{_PATCH_PREFIX_SYNC}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_sets_errored_on_exception(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_compute_stats: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import (
            _execute_deferred_writes,
        )

        mock_parse.side_effect = RuntimeError("parse failed")

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_db.file_states.transition.assert_called_once_with(["library_files/abc"], STATE_NOT_ERRORED, STATE_ERRORED)
        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATS}.compute_segment_stats")
    @patch(f"{_PATCH_PREFIX_SYNC}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_releases_claim_even_when_set_errored_fails(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_compute_stats: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import (
            _execute_deferred_writes,
        )

        mock_parse.side_effect = RuntimeError("parse failed")
        mock_db.file_states.transition.side_effect = RuntimeError("db error")

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_release.assert_called_once_with(mock_db, "library_files/abc")
