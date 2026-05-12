"""Unit tests for extracted private helpers in discovery_worker."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_TAGGED,
    STATE_TAGGED,
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
        result = self._call(mock_self, MagicMock(), "library_files/abc", RuntimeError("oops"), 3)
        assert result == 4

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_state_comp.transition_file_state")
    @patch(_PATCH_RELEASE)
    def test_sets_file_state_errored(self, mock_release, mock_transition_file_state):
        """Should mark the file as errored in the database."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, "library_files/xyz", ValueError("bad"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            ["library_files/xyz"],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_releases_claim_on_error(self, mock_release):
        """Should release the file claim regardless of error type."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, "library_files/abc", RuntimeError("x"), 0)

        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(
        "nomarr.components.library.library_file_state_comp.transition_file_state", side_effect=RuntimeError("db down")
    )
    @patch(_PATCH_RELEASE)
    def test_releases_claim_even_when_set_errored_fails(self, mock_release, mock_transition_file_state):
        """Claim must be released even if state transition helper raises."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, "library_files/abc", RuntimeError("x"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            ["library_files/abc"],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )
        mock_release.assert_called_once_with(mock_db, "library_files/abc")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_returns_incremented_count_at_max_threshold(self, mock_release):
        """At MAX_CONSECUTIVE_ERRORS-1 errors in, returns exactly MAX_CONSECUTIVE_ERRORS."""
        from nomarr.services.infrastructure.workers.discovery_worker import MAX_CONSECUTIVE_ERRORS

        mock_self = _make_worker_self()
        result = self._call(mock_self, MagicMock(), "library_files/abc", RuntimeError("x"), MAX_CONSECUTIVE_ERRORS - 1)
        assert result == MAX_CONSECUTIVE_ERRORS


# ---------------------------------------------------------------------------
# _maybe_spawn_idle_promotion
# ---------------------------------------------------------------------------


class TestMaybeSpawnIdlePromotion:
    """Tests for DiscoveryWorker._maybe_spawn_idle_promotion."""

    _PATCH_WF = "nomarr.workflows.platform.idle_promotion_vectors_wf.idle_promotion_vectors_workflow"

    def _call(self, mock_self, db, models_dir, idle_polls, promotion_running, promotion_state):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._maybe_spawn_idle_promotion(
            mock_self, db, models_dir, idle_polls, promotion_running, promotion_state
        )

    def _state(self, suppressed: bool = False) -> dict:
        return {"suppressed": suppressed}

    @pytest.mark.unit
    def test_returns_unchanged_when_below_poll_threshold(self):
        """When idle_polls < IDLE_POLLS_BEFORE_PROMOTION, returns unchanged."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_self = _make_worker_self()
        sentinel_thread = MagicMock()

        result_thread, result_polls = self._call(
            mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION - 1, sentinel_thread, self._state()
        )

        assert result_thread is sentinel_thread
        assert result_polls == IDLE_POLLS_BEFORE_PROMOTION - 1

    @pytest.mark.unit
    def test_returns_unchanged_when_suppressed(self):
        """When promotion_state["suppressed"] is True, does not spawn."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_self = _make_worker_self()

        result_thread, _ = self._call(
            mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION, None, self._state(suppressed=True)
        )

        assert result_thread is None

    @pytest.mark.unit
    def test_returns_unchanged_when_stop_event_set(self):
        """When stop_event is set, does not spawn a promotion thread."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_self = _make_worker_self()
        mock_self._stop_event.is_set.return_value = True

        result_thread, _ = self._call(
            mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION, None, self._state()
        )

        assert result_thread is None

    @pytest.mark.unit
    def test_returns_unchanged_when_promotion_already_running(self):
        """When an existing promotion thread is alive, does not spawn another."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_self = _make_worker_self()
        running_thread = MagicMock()
        running_thread.is_alive.return_value = True

        result_thread, _result_polls = self._call(
            mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION, running_thread, self._state()
        )

        assert result_thread is running_thread

    @pytest.mark.unit
    @patch(_PATCH_WF)
    def test_spawns_thread_when_all_guards_clear(self, mock_wf):
        """When all guard conditions pass, returns a new thread and resets poll count."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_wf.return_value = 1  # non-zero → do not suppress
        mock_self = _make_worker_self()
        state = self._state()

        result_thread, result_polls = self._call(
            mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION, None, state
        )

        assert result_thread is not None
        assert isinstance(result_thread, threading.Thread)
        assert result_polls == 0

    @pytest.mark.unit
    @patch(_PATCH_WF)
    def test_suppresses_future_promotion_when_workflow_returns_zero(self, mock_wf):
        """When workflow returns 0, sets promotion_state['suppressed'] = True."""
        from nomarr.services.infrastructure.workers.discovery_worker import IDLE_POLLS_BEFORE_PROMOTION

        mock_wf.return_value = 0
        mock_self = _make_worker_self()
        state = self._state()

        result_thread, _ = self._call(mock_self, MagicMock(), "/models", IDLE_POLLS_BEFORE_PROMOTION, None, state)

        # Run the thread synchronously so the wrapper executes
        assert result_thread is not None
        result_thread.join(timeout=5.0)
        assert state["suppressed"] is True


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

        result = self._call(mock_self, MagicMock(), "library_files/abc", None)

        assert result is None

    @pytest.mark.unit
    def test_returns_none_when_resource_management_disabled(self):
        mock_self = _make_worker_self()
        mock_rm = MagicMock()
        mock_rm.enabled = False

        result = self._call(mock_self, MagicMock(), "library_files/abc", mock_rm)

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

        result = self._call(mock_self, mock_db, "library_files/abc", mock_rm)

        assert result == 130.0
        assert mock_self._current_status == "recovering"
        mock_check_headroom.assert_called_once_with(
            vram_budget_mb=8192,
            ram_budget_mb=16384,
            vram_estimate_mb=8192,
            ram_estimate_mb=2048,
            ram_detection_mode="rss",
        )
        mock_release_claim.assert_called_once_with(mock_db, "library_files/abc")

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

        result = self._call(mock_self, mock_db, "library_files/abc", mock_rm)

        assert result is None
        mock_release_claim.assert_not_called()


# ---------------------------------------------------------------------------
# _process_claimed_file
# ---------------------------------------------------------------------------


class TestProcessClaimedFile:
    """Tests for DiscoveryWorker._process_claimed_file."""

    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"
    _PATCH_PROCESS = "nomarr.workflows.processing.process_file_wf.process_file_workflow"
    _PATCH_GETSIZE = f"{_MODULE}.os.path.getsize"
    _PATCH_MALLOC_TRIM = f"{_MODULE}._malloc_trim"

    def _call(self, mock_self, db, file_id, config, onnx_cache, pending_write, write_executor):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._process_claimed_file(
            mock_self, db, file_id, config, onnx_cache, pending_write, write_executor
        )

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_releases_claim_and_returns_false_when_file_not_found(self, mock_release_claim):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_file.return_value = None
        pending_write = MagicMock()

        result = self._call(
            mock_self, mock_db, "library_files/missing", MagicMock(), MagicMock(), pending_write, MagicMock()
        )

        assert result == (pending_write, False)
        mock_release_claim.assert_called_once_with(mock_db, "library_files/missing")

    @pytest.mark.unit
    @patch("nomarr.components.library.library_file_state_comp.transition_file_state")
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    def test_sets_tagged_and_releases_claim_when_all_heads_skipped(
        self,
        mock_process_file_workflow,
        mock_getsize,
        mock_malloc_trim,
        mock_release_claim,
        mock_transition_file_state,
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_file.return_value = {"path": "D:/music/song.mp3"}
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
            "library_files/abc",
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (None, True)
        pending_write.result.assert_called_once_with()
        mock_transition_file_state.assert_called_once_with(
            mock_db,
            ["library_files/abc"],
            STATE_NOT_TAGGED,
            STATE_TAGGED,
        )
        mock_release_claim.assert_called_once_with(mock_db, "library_files/abc")
        mock_malloc_trim.assert_called_once_with()

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    def test_submits_deferred_writes_when_workflow_returns_them(
        self, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_file.return_value = {"path": "D:/music/song.mp3"}
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
            "library_files/abc",
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
    def test_releases_claim_and_returns_pending_write_when_no_deferred_writes(
        self, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_file.return_value = {"path": "D:/music/song.mp3"}
        mock_getsize.return_value = 9876
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=1,
            tags_written=2,
            deferred_writes=None,
        )

        result = self._call(
            mock_self,
            mock_db,
            "library_files/abc",
            MagicMock(),
            MagicMock(),
            None,
            MagicMock(),
        )

        assert result == (None, True)
        mock_release_claim.assert_called_once_with(mock_db, "library_files/abc")
        mock_malloc_trim.assert_called_once_with()
