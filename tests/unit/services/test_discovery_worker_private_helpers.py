"""Unit tests for extracted private helpers in discovery_worker."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_PROCESSED,
    STATE_PROCESSED,
)
from nomarr.helpers.dto.processing_dto import (
    DeferredBackboneVectorWrite,
    DeferredFileWrites,
    DeferredOutputStreamWrite,
)

pytestmark = [pytest.mark.unit, pytest.mark.mocked]

_MODULE = "nomarr.services.infrastructure.workers.discovery_worker"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_worker_self(worker_id: str = "worker:tag:0") -> MagicMock:
    """Build a minimal mock that satisfies DiscoveryWorker private-method self."""
    mock_self = MagicMock()
    mock_self.worker_id = worker_id
    mock_self._stop_event = MagicMock()
    mock_self._stop_event.is_set.return_value = False
    return mock_self


class TestDatabaseUrlValidation:
    """Invalid inherited configuration must not reach SQLAlchemy engine setup."""

    @pytest.mark.parametrize("database_url", ["", "sqlite:///worker.db", "postgresql://user@host"])
    def test_rejects_invalid_database_url(self, database_url: str):
        from nomarr.services.infrastructure.workers.discovery_worker import _validate_database_url

        with pytest.raises(ValueError):
            _validate_database_url(database_url)

    def test_rejects_malformed_database_url(self):
        from sqlalchemy.exc import ArgumentError

        from nomarr.services.infrastructure.workers.discovery_worker import _validate_database_url

        with pytest.raises(ArgumentError):
            _validate_database_url("not-a-url")

    def test_accepts_postgresql_url_with_database_name(self):
        from nomarr.services.infrastructure.workers.discovery_worker import _validate_database_url

        _validate_database_url("postgresql+psycopg2://user:password@host:5432/nomarr")


# ---------------------------------------------------------------------------
# _evict_idle_cache
# ---------------------------------------------------------------------------


class TestEvictIdleCache:
    """Tests for DiscoveryWorker._evict_idle_cache."""

    def _call(self, mock_self: MagicMock, onnx_cache, last_work_time, cache_warmed):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._evict_idle_cache(mock_self, onnx_cache, last_work_time, cache_warmed)

    @pytest.mark.unit
    def test_returns_cache_unchanged_when_cache_is_none(self):
        """None cache returns immediately with original cache_warmed value."""
        mock_self = _make_worker_self()
        result = self._call(mock_self, None, 50.0, True)
        assert result == (None, True)

    @pytest.mark.unit
    def test_returns_cache_unchanged_when_last_work_time_is_none(self):
        """None last_work_time means no idle tracking yet — do not evict."""
        mock_self = _make_worker_self()
        mock_cache = MagicMock()
        result = self._call(mock_self, mock_cache, None, True)
        assert result == (mock_cache, True)

    @pytest.mark.unit
    @patch(f"{_MODULE}.internal_s")
    def test_returns_cache_unchanged_when_not_idle_long_enough(self, mock_time):
        """When idle duration <= CACHE_IDLE_TIMEOUT_S (40), cache is kept."""
        from nomarr.helpers.time_helper import InternalSeconds

        mock_time.return_value = InternalSeconds(100)
        mock_self = _make_worker_self()
        mock_cache = MagicMock()

        # diff = 100 - 80 = 20, which is <= 40
        result = self._call(mock_self, mock_cache, 80.0, True)

        assert result == (mock_cache, True)

    @pytest.mark.unit
    @patch(f"{_MODULE}._malloc_trim")
    @patch(f"{_MODULE}.internal_s")
    def test_evicts_cache_when_idle_timeout_exceeded(self, mock_time, mock_trim):
        """When idle duration > CACHE_IDLE_TIMEOUT_S, cache is cleared."""
        from nomarr.helpers.time_helper import InternalSeconds

        mock_time.return_value = InternalSeconds(100)
        mock_self = _make_worker_self()
        mock_cache = MagicMock()

        # diff = 100 - 50 = 50 > 40  → evict
        result = self._call(mock_self, mock_cache, 50.0, True)

        assert result == (None, False)
        assert mock_cache.warm is False
        mock_trim.assert_called_once()


# ---------------------------------------------------------------------------
# _handle_process_error
# ---------------------------------------------------------------------------


class TestHandleProcessError:
    """Tests for DiscoveryWorker._handle_process_error."""

    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"

    def _call(self, mock_self, db, file_id, error, consecutive_errors):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._handle_process_error(mock_self, db, file_id, error, consecutive_errors)

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_returns_incremented_error_count(self, mock_release):
        """Error count should be incremented by 1."""
        mock_self = _make_worker_self()
        result = self._call(mock_self, MagicMock(), f"{'songs'}/abc", RuntimeError("oops"), 3)
        assert result == 4

    @pytest.mark.unit
    @patch("nomarr.components.library.library_song_state_comp.transition_song_state")
    @patch(_PATCH_RELEASE)
    def test_sets_file_state_errored(self, mock_release, mock_transition_file_state):
        """Should mark the file as errored in the database."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, f"{'songs'}/xyz", ValueError("bad"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [f"{'songs'}/xyz"],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_releases_claim_on_error(self, mock_release):
        """Should release the file claim regardless of error type."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, f"{'songs'}/abc", RuntimeError("x"), 0)

        mock_release.assert_called_once_with(mock_db, f"{'songs'}/abc", "worker:tag:0")

    @pytest.mark.unit
    @patch(
        "nomarr.components.library.library_song_state_comp.transition_song_state",
        side_effect=RuntimeError("db down"),
    )
    @patch(_PATCH_RELEASE)
    def test_releases_claim_even_when_set_errored_fails(self, mock_release, mock_transition_file_state):
        """Claim must be released even if state transition helper raises."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, f"{'songs'}/abc", RuntimeError("x"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [f"{'songs'}/abc"],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )
        mock_release.assert_called_once_with(mock_db, f"{'songs'}/abc", "worker:tag:0")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_returns_incremented_count_at_max_threshold(self, mock_release):
        """At MAX_CONSECUTIVE_ERRORS-1 errors in, returns exactly MAX_CONSECUTIVE_ERRORS."""
        from nomarr.services.infrastructure.workers.discovery_worker import MAX_CONSECUTIVE_ERRORS

        mock_self = _make_worker_self()
        result = self._call(
            mock_self,
            MagicMock(),
            f"{'songs'}/abc",
            RuntimeError("x"),
            MAX_CONSECUTIVE_ERRORS - 1,
        )
        assert result == MAX_CONSECUTIVE_ERRORS


# ---------------------------------------------------------------------------
# _check_resource_headroom
# ---------------------------------------------------------------------------


class TestCheckResourceHeadroom:
    """Tests for DiscoveryWorker._check_resource_headroom."""

    _PATCH_CHECK = "nomarr.components.platform.resource_monitor_comp.check_resource_headroom"
    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"

    def _call(self, mock_self, db, file_id, rm_config):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._check_resource_headroom(mock_self, db, file_id, rm_config)

    @pytest.mark.unit
    def test_returns_none_when_resource_management_config_is_none(self):
        mock_self = _make_worker_self()

        result = self._call(mock_self, MagicMock(), f"{'songs'}/abc", None)

        assert result is None

    @pytest.mark.unit
    def test_returns_none_when_resource_management_disabled(self):
        mock_self = _make_worker_self()
        mock_rm = MagicMock()
        mock_rm.enabled = False

        result = self._call(mock_self, MagicMock(), f"{'songs'}/abc", mock_rm)

        assert result is None

    @pytest.mark.unit
    @patch(f"{_MODULE}.internal_s")
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_CHECK)
    def test_releases_claim_and_enters_recovery_when_vram_and_ram_exhausted(
        self, mock_check_headroom, mock_release_claim, mock_internal_s
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_rm = MagicMock()
        mock_rm.enabled = True
        mock_rm.vram_budget_mb = 8192
        mock_rm.ram_budget_mb = 16384
        mock_rm.ram_detection_mode = "rss"
        mock_check_headroom.return_value = MagicMock(
            vram_ok=False,
            ram_ok=False,
            vram_used_mb=9000,
            ram_used_mb=17000,
        )
        mock_internal_s.return_value = MagicMock(value=100.0)

        result = self._call(mock_self, mock_db, f"{'songs'}/abc", mock_rm)

        assert result == 130.0
        assert mock_self._current_status == "recovering"
        mock_check_headroom.assert_called_once_with(
            vram_budget_mb=8192,
            ram_budget_mb=16384,
            vram_estimate_mb=8192,
            ram_estimate_mb=2048,
            ram_detection_mode="rss",
        )
        mock_release_claim.assert_called_once_with(mock_db, f"{'songs'}/abc", "worker:tag:0")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_CHECK)
    def test_returns_none_without_releasing_claim_when_only_vram_under_pressure(
        self, mock_check_headroom, mock_release_claim
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_rm = MagicMock()
        mock_rm.enabled = True
        mock_rm.vram_budget_mb = 8192
        mock_rm.ram_budget_mb = 16384
        mock_rm.ram_detection_mode = "rss"
        mock_check_headroom.return_value = MagicMock(
            vram_ok=False,
            ram_ok=True,
            vram_used_mb=9000,
            ram_used_mb=12000,
        )

        result = self._call(mock_self, mock_db, f"{'songs'}/abc", mock_rm)

        assert result is None
        mock_release_claim.assert_not_called()


# ---------------------------------------------------------------------------
# _process_claimed_file
# ---------------------------------------------------------------------------


class TestProcessClaimedFile:
    """Tests for DiscoveryWorker._process_claimed_file."""

    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"
    _PATCH_PROCESS = "nomarr.workflows.processing.process_file_wf.process_file_workflow"
    _PATCH_GET_FILE = "nomarr.components.library.library_song_query_comp.get_song_by_id"
    _PATCH_UPDATE_TAGGED = f"{_MODULE}.update_last_tagged_at"
    _PATCH_GETSIZE = f"{_MODULE}.os.path.getsize"
    _PATCH_MALLOC_TRIM = f"{_MODULE}._malloc_trim"

    def _call(self, mock_self, db, file_id, config, onnx_cache, pending_write, write_executor):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._process_claimed_file(
            mock_self, db, file_id, config, onnx_cache, pending_write, write_executor
        )

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_GET_FILE)
    def test_releases_claim_and_returns_false_when_file_not_found(self, mock_get_file_by_id, mock_release_claim):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_get_file_by_id.return_value = None
        pending_write = MagicMock()

        result = self._call(
            mock_self,
            mock_db,
            f"{'songs'}/missing",
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (pending_write, False)
        mock_release_claim.assert_called_once_with(mock_db, f"{'songs'}/missing", "worker:tag:0")

    @pytest.mark.unit
    @patch("nomarr.components.library.library_song_state_comp.transition_song_state")
    @patch(_PATCH_UPDATE_TAGGED)
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_GET_FILE)
    def test_sets_tagged_and_releases_claim_when_all_heads_skipped(
        self,
        mock_get_file_by_id,
        mock_process_file_workflow,
        mock_getsize,
        mock_malloc_trim,
        mock_release_claim,
        mock_update_tagged,
        mock_transition_file_state,
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_get_file_by_id.return_value = {"path": "D:/music/song.mp3"}
        mock_getsize.return_value = 1234
        pending_write = MagicMock()
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=0,
            tags_written=0,
            deferred_writes=None,
        )

        result = self._call(
            mock_self,
            mock_db,
            f"{'songs'}/abc",
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (None, True)
        pending_write.result.assert_called_once_with()
        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [f"{'songs'}/abc"],
            STATE_NOT_PROCESSED,
            STATE_PROCESSED,
        )
        mock_release_claim.assert_called_once_with(mock_db, f"{'songs'}/abc", "worker:tag:0")
        mock_malloc_trim.assert_called_once_with()

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_GET_FILE)
    def test_releases_decoder_crash_for_retry(
        self, mock_get_file_by_id, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_get_file_by_id.return_value = {"path": "D:/music/broken.mp3"}
        mock_getsize.return_value = 1234
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=0,
            tags_written=0,
            head_results={"_crash": {"status": "crash", "reason": "decoder unavailable"}},
            deferred_writes=None,
        )

        result = self._call(
            mock_self,
            mock_db,
            "songs/broken",
            MagicMock(),
            MagicMock(),
            None,
            MagicMock(),
        )

        assert result == (None, False)
        mock_release_claim.assert_called_once_with(mock_db, "songs/broken", "worker:tag:0")
        mock_malloc_trim.assert_called_once_with()

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_GET_FILE)
    def test_submits_deferred_writes_when_workflow_returns_them(
        self, mock_get_file_by_id, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_get_file_by_id.return_value = {"path": "D:/music/song.mp3"}
        mock_getsize.return_value = 4321
        write_executor = MagicMock()
        new_future = MagicMock()
        write_executor.submit.return_value = new_future
        deferred_writes = [MagicMock()]
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=2,
            tags_written=5,
            deferred_writes=deferred_writes,
            timing_summary=None,
            file_path="D:/music/song.mp3",
            elapsed=1.25,
        )

        result = self._call(
            mock_self,
            mock_db,
            f"{'songs'}/abc",
            MagicMock(),
            MagicMock(),
            None,
            write_executor,
        )

        assert result == (new_future, True)
        write_executor.submit.assert_called_once_with(
            _execute_deferred_writes,
            mock_db,
            deferred_writes,
            mock_self.worker_id,
        )
        mock_release_claim.assert_not_called()
        mock_malloc_trim.assert_called_once_with()

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_GET_FILE)
    def test_releases_claim_and_returns_pending_write_when_no_deferred_writes(
        self, mock_get_file_by_id, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_get_file_by_id.return_value = {"path": "D:/music/song.mp3"}
        mock_getsize.return_value = 9876
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=1,
            tags_written=2,
            deferred_writes=None,
        )

        result = self._call(
            mock_self,
            mock_db,
            f"{'songs'}/abc",
            MagicMock(),
            MagicMock(),
            None,
            MagicMock(),
        )

        assert result == (None, True)
        mock_release_claim.assert_called_once_with(mock_db, f"{'songs'}/abc", "worker:tag:0")
        mock_malloc_trim.assert_called_once_with()


class TestExecuteDeferredWrites:
    """Focused tests for ``_execute_deferred_writes`` routing payloads through the aggregate."""

    _PATCH_PARSE = "nomarr.components.tagging.tag_parsing_comp.parse_tag_values"
    _PATCH_SAVE_TAGS = "nomarr.components.library.song_sync_comp.save_song_tags"
    _PATCH_CHROMAPRINT = "nomarr.components.library.library_song_mutation_comp.set_chromaprint"
    _PATCH_TRANSITION = "nomarr.components.library.library_song_state_comp.transition_song_state"
    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"
    _PATCH_UPDATE_TAGGED = f"{_MODULE}.update_last_tagged_at"

    def _call(self, db, writes):
        """Invoke ``_execute_deferred_writes`` with component deps mocked."""
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        with (
            patch(self._PATCH_PARSE, return_value={}),
            patch(self._PATCH_SAVE_TAGS),
            patch(self._PATCH_CHROMAPRINT),
            patch(self._PATCH_TRANSITION) as mock_transition,
            patch(self._PATCH_RELEASE) as mock_release,
            patch(self._PATCH_UPDATE_TAGGED),
        ):
            _execute_deferred_writes(db, writes, "worker:tag:0")
        return mock_transition, mock_release

    def _writes(self, *, with_vectors: bool = True, with_streams: bool = True) -> DeferredFileWrites:
        return DeferredFileWrites(
            file_id="42",
            path="/music/a.flac",
            db_tags={"nom:genre": ["rock"]},
            namespace="nom",
            tagger_version="v-test",
            chromaprint="fp",
            raw_output_streams=(
                [DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)]
                if with_streams
                else []
            ),
            backbone_vectors=(
                [
                    DeferredBackboneVectorWrite(
                        backbone="bb1",
                        vector_payloads=[
                            {
                                "backbone_id": "bb1",
                                "model_id": "suite-hash",
                                "embedding_vector": [0.25, 0.25],
                                "embed_dim": 2,
                                "num_segments": 3,
                            }
                        ],
                    )
                ]
                if with_vectors
                else []
            ),
        )

    def test_routes_streams_and_vectors_through_aggregate_single_call(self) -> None:
        db = MagicMock()
        writes = self._writes()
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_called_once_with(
            song_id=42,
            backbone="bb1",
            vectors=[
                {
                    "backbone_id": "bb1",
                    "model_id": "suite-hash",
                    "embedding_vector": [0.25, 0.25],
                    "embed_dim": 2,
                    "num_segments": 3,
                }
            ],
            output_streams=[{"output_id": "out-0", "values": [0.1, 0.9], "output_index": 0}],
        )
        mock_release.assert_called_once_with(db, 42, "worker:tag:0")

    def test_routes_streams_only_when_no_backbone_vectors(self) -> None:
        db = MagicMock()
        writes = self._writes(with_vectors=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_called_once_with(
            song_id=42,
            backbone="",
            vectors=[],
            output_streams=[{"output_id": "out-0", "values": [0.1, 0.9], "output_index": 0}],
        )
        mock_release.assert_called_once()

    def test_multiple_backbones_never_erase_each_other(self) -> None:
        db = MagicMock()
        writes = DeferredFileWrites(
            file_id="42",
            path="/music/a.flac",
            db_tags={},
            namespace="nom",
            tagger_version="v-test",
            chromaprint=None,
            raw_output_streams=[DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
            backbone_vectors=[
                DeferredBackboneVectorWrite(
                    backbone="bb1",
                    vector_payloads=[{"backbone_id": "bb1", "model_id": "h", "embedding_vector": [0.5, 0.5]}],
                ),
                DeferredBackboneVectorWrite(
                    backbone="openl3",
                    vector_payloads=[{"backbone_id": "openl3", "model_id": "h", "embedding_vector": [0.6, 0.4]}],
                ),
            ],
        )
        _, mock_release = self._call(db, writes)

        assert db.ml.replace_song_inference_results.call_count == 2
        bb1_call, openl3_call = db.ml.replace_song_inference_results.call_args_list
        assert bb1_call.kwargs["backbone"] == "bb1"
        assert openl3_call.kwargs["backbone"] == "openl3"
        # each per-backbone call carries the full canonical stream set (with index)
        expected_streams = [{"output_id": "out-0", "values": [0.1, 0.9], "output_index": 0}]
        assert bb1_call.kwargs["output_streams"] == expected_streams
        assert openl3_call.kwargs["output_streams"] == expected_streams
        mock_release.assert_called_once()

    def test_backbones_without_streams_replaces_streams_with_none(self) -> None:
        """Backbones present with no streams: aggregate called once with vectors and
        output_streams=[], and streams are replaced per the aggregate replace contract."""
        db = MagicMock()
        writes = self._writes(with_vectors=True, with_streams=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_called_once_with(
            song_id=42,
            backbone="bb1",
            vectors=[
                {
                    "backbone_id": "bb1",
                    "model_id": "suite-hash",
                    "embedding_vector": [0.25, 0.25],
                    "embed_dim": 2,
                    "num_segments": 3,
                }
            ],
            output_streams=[],
        )
        mock_release.assert_called_once_with(db, 42, "worker:tag:0")

    def test_aggregate_failure_sets_errored_and_releases_claim(self) -> None:
        db = MagicMock()
        db.ml.replace_song_inference_results.side_effect = RuntimeError("db down")
        writes = self._writes()
        mock_transition, mock_release = self._call(db, writes)

        mock_transition.assert_any_call(db, [42], STATE_NOT_ERRORED, STATE_ERRORED)
        mock_release.assert_called_once_with(db, 42, "worker:tag:0")

    def test_no_write_when_no_streams_and_no_vectors(self) -> None:
        db = MagicMock()
        writes = self._writes(with_vectors=False, with_streams=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_not_called()
        mock_release.assert_called_once()


# ---------------------------------------------------------------------------
# _warm_onnx_cache — typed VramPromise attribute access (P2-S5)
# ---------------------------------------------------------------------------


class TestWarmOnnxCacheVramPromise:
    """``_warm_onnx_cache`` reads VramPromise attributes (not dict ``.get``)
    and formats ``promised_mb`` with ``:.0f``."""

    def _call(self, mock_self, db):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        config = MagicMock()
        config.models_dir = "models"
        return DiscoveryWorker._warm_onnx_cache(mock_self, db, config)

    def test_formats_promise_rows_from_typed_vram_promise_attrs(self) -> None:
        from nomarr.helpers.dataclasses.app_dataclasses import VramPromise

        mock_self = _make_worker_self()
        mock_self.prefer_gpu = False  # skip the VRAM-probe intent branch
        db = MagicMock()
        promise = VramPromise(
            worker_id="worker:tag:0",
            pid=42,
            model_path="/models/backbone.onnx",
            promised_mb=512.0,
            total_mb=1000,
            used_mb=100,
        )
        fleet = {"vram": {"used_mb": 100, "total_mb": 1000}, "promises": [promise]}
        mock_onnx = MagicMock()
        mock_onnx._all_models.return_value = []
        with (
            patch(
                "nomarr.components.ml.resources.ml_vram_coordinator_comp.get_fleet_vram_state",
                return_value=fleet,
            ),
            patch(
                "nomarr.components.ml.onnx.ml_cache.ONNXModelCache.create",
                return_value=mock_onnx,
            ),
            patch(f"{_MODULE}.logger") as mock_logger,
        ):
            cache = self._call(mock_self, db)

        assert cache is mock_onnx
        mock_logger.info.assert_called_once()
        # The promise rows are the final positional arg (joined) of logger.info.
        promise_rows = mock_logger.info.call_args.args[-1]
        # Row must be built from typed attrs + ``:.0f`` formatting of promised_mb.
        assert "worker:tag:0" in promise_rows
        assert "backbone.onnx" in promise_rows
        assert "512 MB" in promise_rows
        assert "UNKNOWN" in promise_rows
