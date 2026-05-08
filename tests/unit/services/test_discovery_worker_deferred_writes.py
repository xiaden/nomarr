"""Tests for _execute_deferred_writes in discovery_worker."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.components.ml.inference.ml_output_stream_store_comp import StreamWrite
from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_NOT_VECTORS_EXTRACTED,
    STATE_TAGGED,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.helpers.dto.ml_edge_dto import MLEdgeWrites
from nomarr.helpers.dto.processing_dto import DeferredFileWrites, DeferredOutputStreamWrite

_PATCH_PREFIX_SYNC = "nomarr.components.library.file_sync_comp"
_PATCH_PREFIX_MUTATION = "nomarr.components.library.library_file_mutation_comp"
_PATCH_PREFIX_STATE = "nomarr.components.library.library_file_state_comp"
_PATCH_PREFIX_PARSE = "nomarr.components.tagging.tag_parsing_comp"
_PATCH_PREFIX_STREAMS = "nomarr.components.ml.inference.ml_output_stream_store_comp"
_PATCH_PREFIX_TAG_WRITE = "nomarr.components.tagging.tag_write_comp"
_PATCH_PREFIX_TAG_MODEL_OUTPUT = "nomarr.components.ml.onnx.tag_model_output_comp"
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
        raw_output_streams=[],
        ml_edges=None,
    )


@pytest.fixture()
def rich_writes() -> DeferredFileWrites:
    return DeferredFileWrites(
        file_id="library_files/abc",
        path="/music/test.flac",
        db_tags={"genre": "rock"},
        namespace="nom",
        tagger_version="v1",
        chromaprint="abc123",
        raw_output_streams=[
            DeferredOutputStreamWrite(output_id="ml_model_outputs/out-2", values=[0.2, 0.4]),
            DeferredOutputStreamWrite(output_id="ml_model_outputs/out-1", values=[0.1, 0.3]),
        ],
        ml_edges=MLEdgeWrites(
            output_edges={
                "nom:genre-rock": ("ml_model_outputs/out-1", 0.91),
                "nom:genre-pop": ("ml_model_outputs/out-2", 0.42),
            }
        ),
    )


class TestExecuteDeferredWritesSuccess:
    """Tests for successful _execute_deferred_writes execution."""

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_TAG_MODEL_OUTPUT}.write_tag_model_output_edges_batch")
    @patch(f"{_PATCH_PREFIX_TAG_WRITE}.resolve_tag_ids")
    @patch(f"{_PATCH_PREFIX_STREAMS}.upsert_output_streams")
    @patch(f"{_PATCH_PREFIX_STATE}.transition_file_state")
    @patch(f"{_PATCH_PREFIX_MUTATION}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    @patch("nomarr.services.infrastructure.workers.discovery_worker.update_last_tagged_at")
    def test_writes_tags_edges_chromaprint_and_canonical_streams(
        self,
        mock_update_last_tagged_at: MagicMock,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_transition_state: MagicMock,
        mock_upsert_output_streams: MagicMock,
        mock_resolve_tag_ids: MagicMock,
        mock_write_tag_model_output_edges_batch: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        rich_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_parse.return_value = {"genre": ["rock"]}
        mock_resolve_tag_ids.return_value = {
            ("nom:genre-rock", 0.91): "tags/rock",
            ("nom:genre-pop", 0.42): "tags/pop",
        }

        _execute_deferred_writes(mock_db, rich_writes, "worker:tag:0")

        mock_save_tags.assert_called_once_with(mock_db, "library_files/abc", {"nom:genre": ["rock"]})
        mock_resolve_tag_ids.assert_called_once_with(
            mock_db,
            [("nom:genre-rock", 0.91), ("nom:genre-pop", 0.42)],
        )
        mock_write_tag_model_output_edges_batch.assert_called_once_with(
            mock_db,
            [
                ("tags/rock", "ml_model_outputs/out-1", 0.91),
                ("tags/pop", "ml_model_outputs/out-2", 0.42),
            ],
        )
        mock_set_chromaprint.assert_called_once_with(mock_db, "library_files/abc", "abc123")
        mock_upsert_output_streams.assert_called_once()
        assert mock_upsert_output_streams.call_args.kwargs == {
            "file_id": "library_files/abc",
            "streams": [
                StreamWrite(output_id="ml_model_outputs/out-2", values=[0.2, 0.4]),
                StreamWrite(output_id="ml_model_outputs/out-1", values=[0.1, 0.3]),
            ],
        }
        mock_transition_state.assert_has_calls(
            [
                call(mock_db, ["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED),
                call(
                    mock_db,
                    ["library_files/abc"],
                    STATE_NOT_VECTORS_EXTRACTED,
                    STATE_VECTORS_EXTRACTED,
                ),
            ]
        )
        mock_update_last_tagged_at.assert_called_once_with(mock_db, "library_files/abc")
        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STREAMS}.upsert_output_streams")
    @patch(f"{_PATCH_PREFIX_STATE}.transition_file_state")
    @patch(f"{_PATCH_PREFIX_MUTATION}.set_chromaprint")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    @patch("nomarr.services.infrastructure.workers.discovery_worker.update_last_tagged_at")
    def test_skips_optional_writes_when_payloads_are_missing(
        self,
        mock_update_last_tagged_at: MagicMock,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_set_chromaprint: MagicMock,
        mock_transition_state: MagicMock,
        mock_upsert_output_streams: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_parse.return_value = {}

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_save_tags.assert_called_once_with(mock_db, "library_files/abc", {})
        mock_set_chromaprint.assert_not_called()
        mock_upsert_output_streams.assert_not_called()
        mock_transition_state.assert_has_calls(
            [
                call(mock_db, ["library_files/abc"], STATE_NOT_TAGGED, STATE_TAGGED),
                call(
                    mock_db,
                    ["library_files/abc"],
                    STATE_NOT_VECTORS_EXTRACTED,
                    STATE_VECTORS_EXTRACTED,
                ),
            ]
        )
        mock_update_last_tagged_at.assert_called_once_with(mock_db, "library_files/abc")
        mock_release.assert_called_once_with(mock_db, "library_files/abc")


class TestExecuteDeferredWritesFailure:
    """Tests for _execute_deferred_writes when writes fail."""

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATE}.transition_file_state")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_sets_errored_on_exception(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_transition_state: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_parse.side_effect = RuntimeError("parse failed")

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_transition_state.assert_called_once_with(
            mock_db,
            ["library_files/abc"],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )
        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(f"{_PATCH_PREFIX_WORKER}.release_claim")
    @patch(f"{_PATCH_PREFIX_STATE}.transition_file_state")
    @patch(f"{_PATCH_PREFIX_PARSE}.parse_tag_values")
    @patch(f"{_PATCH_PREFIX_SYNC}.save_file_tags")
    def test_releases_claim_even_when_set_errored_fails(
        self,
        mock_save_tags: MagicMock,
        mock_parse: MagicMock,
        mock_transition_state: MagicMock,
        mock_release: MagicMock,
        mock_db: MagicMock,
        minimal_writes: DeferredFileWrites,
    ) -> None:
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_parse.side_effect = RuntimeError("parse failed")
        mock_transition_state.side_effect = RuntimeError("db error")

        _execute_deferred_writes(mock_db, minimal_writes, "worker:tag:0")

        mock_release.assert_called_once_with(mock_db, "library_files/abc")
