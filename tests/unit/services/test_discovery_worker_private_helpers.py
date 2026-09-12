"""Unit tests for extracted private helpers in discovery_worker."""

from __future__ import annotations

import pickle
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from nomarr.helpers.constants.file_states import (
    STATE_ERRORED,
    STATE_NOT_ERRORED,
    STATE_NOT_PROCESSED,
    STATE_PROCESSED,
    STATE_VECTORS_EXTRACTED,
)
from nomarr.helpers.dataclasses.ml_output_stream_dataclass import OutputStreamWrite
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
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


def _song(normalized_path: str = "song.flac") -> SongIdentity:
    """Semantic identity the worker resolves a claimed handle to before ML writes."""
    return SongIdentity(
        library=LibraryIdentity(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="music", root_path="/music"),
        normalized_path=normalized_path,
    )


def _vector_command(*, vector=(0.25, 0.25), suite="suite-hash", num_segments=3) -> BackboneVectorWrite:
    """Typed backbone write command used to build deferred payloads."""
    return BackboneVectorWrite(
        vector=tuple(vector),
        model_suite_hash=suite,
        num_segments=num_segments,
    )


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

    def _call(self, mock_self, db, song, error, consecutive_errors):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._handle_process_error(mock_self, db, song, error, consecutive_errors)

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_returns_incremented_error_count(self, mock_release):
        """Error count should be incremented by 1."""
        mock_self = _make_worker_self()
        result = self._call(mock_self, MagicMock(), _song(), RuntimeError("oops"), 3)
        assert result == 4

    @pytest.mark.unit
    @patch("nomarr.components.library.library_song_state_comp.transition_song_state")
    @patch(_PATCH_RELEASE)
    def test_sets_file_state_errored(self, mock_release, mock_transition_file_state):
        """Should mark the file as errored in the database."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, _song(), ValueError("bad"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [_song()],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_releases_claim_on_error(self, mock_release):
        """Should release the file claim regardless of error type."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()

        self._call(mock_self, mock_db, _song(), RuntimeError("x"), 0)

        mock_release.assert_called_once_with(mock_db, _song(), "worker:tag:0")

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

        self._call(mock_self, mock_db, _song(), RuntimeError("x"), 0)

        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [_song()],
            STATE_NOT_ERRORED,
            STATE_ERRORED,
        )
        mock_release.assert_called_once_with(mock_db, _song(), "worker:tag:0")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_returns_incremented_count_at_max_threshold(self, mock_release):
        """At MAX_CONSECUTIVE_ERRORS-1 errors in, returns exactly MAX_CONSECUTIVE_ERRORS."""
        from nomarr.services.infrastructure.workers.discovery_worker import MAX_CONSECUTIVE_ERRORS

        mock_self = _make_worker_self()
        result = self._call(
            mock_self,
            MagicMock(),
            _song(),
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

    def _call(self, mock_self, db, song, rm_config):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._check_resource_headroom(mock_self, db, song, rm_config)

    @pytest.mark.unit
    def test_returns_none_when_resource_management_config_is_none(self):
        mock_self = _make_worker_self()

        result = self._call(mock_self, MagicMock(), _song(), None)

        assert result is None

    @pytest.mark.unit
    def test_returns_none_when_resource_management_disabled(self):
        mock_self = _make_worker_self()
        mock_rm = MagicMock()
        mock_rm.enabled = False

        result = self._call(mock_self, MagicMock(), _song(), mock_rm)

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

        result = self._call(mock_self, mock_db, _song(), mock_rm)

        assert result == 130.0
        assert mock_self._current_status == "recovering"
        mock_check_headroom.assert_called_once_with(
            vram_budget_mb=8192,
            ram_budget_mb=16384,
            vram_estimate_mb=8192,
            ram_estimate_mb=2048,
            ram_detection_mode="rss",
        )
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")

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

        result = self._call(mock_self, mock_db, _song(), mock_rm)

        assert result is None
        mock_release_claim.assert_not_called()


# ---------------------------------------------------------------------------
# _process_claimed_file
# ---------------------------------------------------------------------------


class TestProcessClaimedFile:
    """Tests for DiscoveryWorker._process_claimed_file.

    The worker addresses the claimed song by its semantic ``SongIdentity``
    locator end-to-end: it loads the located song via ``db.library.get_song``,
    passes that same identity to the workflow as ``song=``, and uses the locator
    for the claim/state lifecycle. No integer handle or resolver is involved.
    """

    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"
    _PATCH_PROCESS = "nomarr.workflows.processing.process_file_wf.process_file_workflow"
    _PATCH_TRANSITION = "nomarr.components.library.library_song_state_comp.transition_song_state"
    _PATCH_UPDATE_TAGGED = f"{_MODULE}.update_last_tagged_at"
    _PATCH_GETSIZE = f"{_MODULE}.os.path.getsize"
    _PATCH_MALLOC_TRIM = f"{_MODULE}._malloc_trim"

    def _call(self, mock_self, db, song, config, onnx_cache, pending_write, write_executor):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        return DiscoveryWorker._process_claimed_file(
            mock_self, db, song, config, onnx_cache, pending_write, write_executor
        )

    def _deferred_writes(self) -> DeferredFileWrites:
        return DeferredFileWrites(
            song=_song(),
            path="D:/music/song.mp3",
            db_tags={"nom:genre": ["rock"]},
            namespace="nom",
            tagger_version="v-test",
            chromaprint="fp",
            raw_output_streams=[DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
            backbone_vectors=[DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command()])],
        )

    def _located_song(self) -> SimpleNamespace:
        return SimpleNamespace(path="D:/music/song.mp3")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    def test_releases_claim_and_returns_false_when_file_not_found(self, mock_release_claim):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = None
        pending_write = MagicMock()

        result = self._call(
            mock_self,
            mock_db,
            _song(),
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (pending_write, False)
        mock_db.library.get_song.assert_called_once_with(_song())
        # The locator itself addresses the release; no resolver/int handle.
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_PROCESS)
    @patch(_PATCH_TRANSITION)
    def test_missing_locator_releases_claim_without_workflow(
        self, mock_transition_file_state, mock_process_file_workflow, mock_release_claim
    ):
        """A locator with no persisted song is the negative path: no ML write and
        no state transition, just the locator-addressed claim release."""
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = None
        pending_write = MagicMock()

        result = self._call(
            mock_self,
            mock_db,
            _song(),
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (pending_write, False)
        mock_process_file_workflow.assert_not_called()
        mock_transition_file_state.assert_not_called()
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")

    @pytest.mark.unit
    @patch(_PATCH_TRANSITION)
    @patch(_PATCH_UPDATE_TAGGED)
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
        mock_update_tagged,
        mock_transition_file_state,
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = self._located_song()
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
            _song(),
            MagicMock(),
            MagicMock(),
            pending_write,
            MagicMock(),
        )

        assert result == (None, True)
        pending_write.result.assert_called_once_with()
        mock_process_file_workflow.assert_called_once()
        assert mock_process_file_workflow.call_args.kwargs["song"] == _song()
        mock_transition_file_state.assert_called_once_with(
            mock_db,
            [_song()],
            STATE_NOT_PROCESSED,
            STATE_PROCESSED,
        )
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")
        mock_malloc_trim.assert_called_once_with()

    @pytest.mark.unit
    @patch(_PATCH_RELEASE)
    @patch(_PATCH_MALLOC_TRIM)
    @patch(_PATCH_GETSIZE)
    @patch(_PATCH_PROCESS)
    def test_releases_decoder_crash_for_retry(
        self, mock_process_file_workflow, mock_getsize, mock_malloc_trim, mock_release_claim
    ):
        mock_self = _make_worker_self()
        mock_db = MagicMock()
        mock_db.library.get_song.return_value = self._located_song()
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
            _song(),
            MagicMock(),
            MagicMock(),
            None,
            MagicMock(),
        )

        assert result == (None, False)
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")
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
        mock_db.library.get_song.return_value = self._located_song()
        mock_getsize.return_value = 4321
        write_executor = MagicMock()
        new_future = MagicMock()
        write_executor.submit.return_value = new_future
        deferred_writes = self._deferred_writes()
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
            _song(),
            MagicMock(),
            MagicMock(),
            None,
            write_executor,
        )

        assert result == (new_future, True)
        mock_process_file_workflow.assert_called_once()
        assert mock_process_file_workflow.call_args.kwargs["song"] == _song()
        # The semantic payload and worker id are submitted — no integer handle.
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
        mock_db.library.get_song.return_value = self._located_song()
        mock_getsize.return_value = 9876
        mock_process_file_workflow.return_value = MagicMock(
            heads_processed=1,
            tags_written=2,
            deferred_writes=None,
        )

        result = self._call(
            mock_self,
            mock_db,
            _song(),
            MagicMock(),
            MagicMock(),
            None,
            MagicMock(),
        )

        assert result == (None, True)
        mock_release_claim.assert_called_once_with(mock_db, _song(), "worker:tag:0")
        mock_malloc_trim.assert_called_once_with()


class TestExecuteDeferredWrites:
    """Focused tests for ``_execute_deferred_writes`` routing typed commands
    through the semantic aggregate.

    The deferred payload carries ``song: SongIdentity`` plus typed
    ``BackboneVectorWrite``/``OutputStreamWrite`` commands. The worker addresses
    the ML aggregate and every lifecycle intent (tags / chromaprint / state /
    claim release) by the same semantic locator — no integer claim handle or
    storage key crosses this boundary.
    """

    _PATCH_PARSE = "nomarr.components.tagging.tag_parsing_comp.parse_tag_values"
    _PATCH_SAVE_TAGS = "nomarr.components.library.song_sync_comp.save_song_tags"
    _PATCH_CHROMAPRINT = "nomarr.components.library.library_song_mutation_comp.set_chromaprint"
    _PATCH_TRANSITION = "nomarr.components.library.library_song_state_comp.transition_song_state"
    _PATCH_RELEASE = "nomarr.components.workers.worker_discovery_comp.release_claim"
    _PATCH_UPDATE_TAGGED = f"{_MODULE}.update_last_tagged_at"

    def _call(self, db, writes, *, chromaprint_side_effect=None, transition_side_effect=None):
        """Invoke ``_execute_deferred_writes`` with component deps mocked."""
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        with (
            patch(self._PATCH_PARSE, return_value={}),
            patch(self._PATCH_SAVE_TAGS),
            patch(self._PATCH_CHROMAPRINT, side_effect=chromaprint_side_effect),
            patch(self._PATCH_TRANSITION, side_effect=transition_side_effect) as mock_transition,
            patch(self._PATCH_RELEASE) as mock_release,
            patch(self._PATCH_UPDATE_TAGGED),
        ):
            _execute_deferred_writes(db, writes, "worker:tag:0")
        return mock_transition, mock_release

    def test_full_stage_relative_order_tag_scalar_ml_state(self) -> None:
        """The deferred executor runs the tag -> chromaprint scalar -> per-backbone
        ML aggregate -> PROCESSED/state -> update_last_tagged_at -> VECTORS_EXTRACTED
        stages in exactly that relative order.

        Each stage is instrumented to append a marker to one shared list, so the
        assertion is call-ordering based (no sleeps or timing)."""
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        db = MagicMock()
        writes = self._writes(with_vectors=True, with_streams=True)
        order: list[str] = []

        def _record_save_tags(_db, _song, _tags):
            order.append("tags")

        def _record_chromaprint(_db, _song, _chromaprint):
            order.append("chromaprint")

        def _record_aggregate(song, backbone, *, vectors, output_streams):
            order.append(f"ml:{backbone}")

        def _record_transition(_db, _songs, _from_state, to_state):
            order.append(f"state:{to_state}")

        def _record_update_tagged(_db, _song):
            order.append("update_last_tagged_at")

        db.ml.replace_song_inference_results.side_effect = _record_aggregate
        with (
            patch(self._PATCH_PARSE, return_value={"genre": ["rock"]}),
            patch(self._PATCH_SAVE_TAGS, side_effect=_record_save_tags),
            patch(self._PATCH_CHROMAPRINT, side_effect=_record_chromaprint),
            patch(self._PATCH_TRANSITION, side_effect=_record_transition),
            patch(self._PATCH_RELEASE),
            patch(self._PATCH_UPDATE_TAGGED, side_effect=_record_update_tagged),
        ):
            _execute_deferred_writes(db, writes, "worker:tag:0")

        assert order == [
            "tags",
            "chromaprint",
            "ml:bb1",
            f"state:{STATE_PROCESSED}",
            "update_last_tagged_at",
            f"state:{STATE_VECTORS_EXTRACTED}",
        ]

    def _writes(self, *, with_vectors: bool = True, with_streams: bool = True) -> DeferredFileWrites:
        return DeferredFileWrites(
            song=_song(),
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
                [DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command()])] if with_vectors else []
            ),
        )

    def test_routes_typed_vectors_and_streams_through_aggregate_single_call(self) -> None:
        db = MagicMock()
        writes = self._writes()
        _, mock_release = self._call(db, writes)

        # The aggregate is addressed by the semantic identity and typed commands;
        # the integer claim handle is used only for the non-ML claim release.
        db.ml.replace_song_inference_results.assert_called_once_with(
            song=_song(),
            backbone="bb1",
            vectors=[_vector_command()],
            output_streams=[OutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
        )
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_no_integer_song_key_or_raw_storage_dict_reaches_ml_facade(self) -> None:
        db = MagicMock()
        writes = self._writes()
        self._call(db, writes)

        call = db.ml.replace_song_inference_results.call_args
        assert call.kwargs.get("song") == _song()
        assert isinstance(call.kwargs["song"], SongIdentity)
        assert "song_id" not in call.kwargs
        assert "file_id" not in call.kwargs
        assert all(isinstance(v, BackboneVectorWrite) for v in call.kwargs["vectors"])
        assert all(isinstance(s, OutputStreamWrite) for s in call.kwargs["output_streams"])
        assert not any(hasattr(v, "embed_dim") for v in call.kwargs["vectors"])

    def test_routes_streams_only_sentinel_when_no_backbone_vectors(self) -> None:
        db = MagicMock()
        writes = self._writes(with_vectors=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_called_once_with(
            song=_song(),
            backbone="",
            vectors=[],
            output_streams=[OutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
        )
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_multiple_backbones_never_erase_each_other(self) -> None:
        db = MagicMock()
        writes = DeferredFileWrites(
            song=_song(),
            path="/music/a.flac",
            db_tags={},
            namespace="nom",
            tagger_version="v-test",
            chromaprint=None,
            raw_output_streams=[DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
            backbone_vectors=[
                DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command(suite="h1")]),
                DeferredBackboneVectorWrite(backbone="openl3", vectors=[_vector_command(suite="h2")]),
            ],
        )
        _, mock_release = self._call(db, writes)

        assert db.ml.replace_song_inference_results.call_count == 2
        bb1_call, openl3_call = db.ml.replace_song_inference_results.call_args_list
        assert bb1_call.kwargs["backbone"] == "bb1"
        assert openl3_call.kwargs["backbone"] == "openl3"
        assert bb1_call.kwargs["song"] == _song()
        assert openl3_call.kwargs["song"] == _song()
        # each per-backbone call carries the full stream set (with index)
        expected_streams = [OutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)]
        assert bb1_call.kwargs["output_streams"] == expected_streams
        assert openl3_call.kwargs["output_streams"] == expected_streams
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_backbones_without_streams_replaces_streams_with_none(self) -> None:
        """Backbones present with no streams: aggregate called with vectors and
        output_streams=[], replacing the song's streams per the aggregate replace
        contract."""
        db = MagicMock()
        writes = self._writes(with_vectors=True, with_streams=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_called_once_with(
            song=_song(),
            backbone="bb1",
            vectors=[_vector_command()],
            output_streams=[],
        )
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_duplicate_output_ids_passed_through_verbatim_without_caller_dedup(self) -> None:
        """Duplicate output_ids reach persistence verbatim — persistence owns
        last-wins deduplication, so no caller-side normalization helper runs."""
        db = MagicMock()
        writes = DeferredFileWrites(
            song=_song(),
            path="/music/a.flac",
            db_tags={},
            namespace="nom",
            tagger_version="v-test",
            chromaprint=None,
            raw_output_streams=[
                DeferredOutputStreamWrite(output_id="head_0", values=[0.1, 0.9], output_index=0),
                DeferredOutputStreamWrite(output_id="head_0", values=[0.4, 0.6], output_index=0),
            ],
            backbone_vectors=[DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command()])],
        )
        self._call(db, writes)

        call = db.ml.replace_song_inference_results.call_args
        assert call.kwargs["output_streams"] == [
            OutputStreamWrite(output_id="head_0", values=[0.1, 0.9], output_index=0),
            OutputStreamWrite(output_id="head_0", values=[0.4, 0.6], output_index=0),
        ]

    def test_chromaprint_failure_sets_errored_and_releases_claim(self) -> None:
        db = MagicMock()
        writes = self._writes()
        mock_transition, mock_release = self._call(db, writes, chromaprint_side_effect=RuntimeError("chromaprint down"))

        mock_transition.assert_called_once_with(db, [_song()], STATE_NOT_ERRORED, STATE_ERRORED)
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_state_failure_sets_errored_and_releases_claim(self) -> None:
        db = MagicMock()
        writes = self._writes()
        mock_transition, mock_release = self._call(
            db, writes, transition_side_effect=[RuntimeError("state down"), None]
        )

        assert mock_transition.call_args_list[0].args == (db, [_song()], STATE_NOT_PROCESSED, STATE_PROCESSED)
        mock_transition.assert_any_call(db, [_song()], STATE_NOT_ERRORED, STATE_ERRORED)
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_aggregate_failure_sets_errored_and_releases_claim(self) -> None:
        db = MagicMock()
        db.ml.replace_song_inference_results.side_effect = RuntimeError("db down")
        writes = self._writes()
        mock_transition, mock_release = self._call(db, writes)

        mock_transition.assert_any_call(db, [_song()], STATE_NOT_ERRORED, STATE_ERRORED)
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_multi_backbone_partial_failure_keeps_earlier_commits_and_releases(self) -> None:
        """Injected failure on a later backbone leaves the earlier backbone call
        committed and prevents the processed transitions; song is marked errored
        (retry-eligible) and the claim is released."""
        db = MagicMock()
        received: list[tuple[str, SongIdentity, list[BackboneVectorWrite], list[OutputStreamWrite]]] = []

        def _flaky(song, backbone, *, vectors, output_streams):
            received.append((backbone, song, list(vectors), list(output_streams)))
            if backbone == "openl3":
                raise RuntimeError("injected second-backbone failure")

        db.ml.replace_song_inference_results.side_effect = _flaky
        writes = DeferredFileWrites(
            song=_song(),
            path="/music/a.flac",
            db_tags={},
            namespace="nom",
            tagger_version="v-test",
            chromaprint=None,
            raw_output_streams=[DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
            backbone_vectors=[
                DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command(suite="h1")]),
                DeferredBackboneVectorWrite(backbone="openl3", vectors=[_vector_command(suite="h2")]),
            ],
        )
        mock_transition, mock_release = self._call(db, writes)

        # bb1 was dispatched (committed), then the later backbone failed.
        assert [r[0] for r in received] == ["bb1", "openl3"]
        assert received[0][1] == _song()
        assert isinstance(received[0][1], SongIdentity)
        assert all(isinstance(v, BackboneVectorWrite) for v in received[0][2])
        assert all(isinstance(s, OutputStreamWrite) for s in received[0][3])
        # success-path processed transition never runs; errored marking did.
        mock_transition.assert_any_call(db, [_song()], STATE_NOT_ERRORED, STATE_ERRORED)
        assert STATE_PROCESSED not in [a.args[-1] for a in mock_transition.call_args_list]
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_no_write_when_no_streams_and_no_vectors(self) -> None:
        db = MagicMock()
        writes = self._writes(with_vectors=False, with_streams=False)
        _, mock_release = self._call(db, writes)

        db.ml.replace_song_inference_results.assert_not_called()
        mock_release.assert_called_once_with(db, _song(), "worker:tag:0")

    def test_deferred_semantic_payload_survives_pickle_reload(self) -> None:
        """P4-S4: a deferred semantic DTO round-trips through pickle (the reload
        surrogate for the object-passing ThreadPoolExecutor boundary) with its
        SongIdentity and typed commands intact and no storage handle/dict leak."""
        writes = DeferredFileWrites(
            song=_song(),
            path="/music/a.flac",
            db_tags={"nom:genre": ["rock"]},
            namespace="nom",
            tagger_version="v-test",
            chromaprint="fp",
            raw_output_streams=[DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)],
            backbone_vectors=[DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command()])],
        )
        reloaded = pickle.loads(pickle.dumps(writes))

        assert reloaded == writes
        assert reloaded.song == _song()
        assert isinstance(reloaded.song, SongIdentity)
        assert not hasattr(reloaded, "file_id")
        vector_cmd = reloaded.backbone_vectors[0].vectors[0]
        assert isinstance(vector_cmd, BackboneVectorWrite)

    def test_retry_after_injected_failure_dispatches_fresh_semantic_commands(self) -> None:
        """P4-S4: after a restart-style reload and an injected later-backbone
        failure, a retry re-dispatches fresh semantic commands from the same DTO
        — it never replays partial persistence state or a storage key."""
        from nomarr.services.infrastructure.workers.discovery_worker import _execute_deferred_writes

        writes = pickle.loads(
            pickle.dumps(
                DeferredFileWrites(
                    song=_song(),
                    path="/music/a.flac",
                    db_tags={},
                    namespace="nom",
                    tagger_version="v-test",
                    chromaprint=None,
                    raw_output_streams=[
                        DeferredOutputStreamWrite(output_id="out-0", values=[0.1, 0.9], output_index=0)
                    ],
                    backbone_vectors=[
                        DeferredBackboneVectorWrite(backbone="bb1", vectors=[_vector_command(suite="h1")]),
                        DeferredBackboneVectorWrite(backbone="openl3", vectors=[_vector_command(suite="h2")]),
                    ],
                )
            )
        )
        db = MagicMock()
        received: list[tuple[str, SongIdentity, list[BackboneVectorWrite], list[OutputStreamWrite]]] = []
        failures_left = {"n": 1}

        def flaky(song, backbone, *, vectors, output_streams):
            received.append((backbone, song, list(vectors), list(output_streams)))
            if backbone == "openl3" and failures_left["n"] > 0:
                failures_left["n"] -= 1
                raise RuntimeError("injected failure on later backbone")

        db.ml.replace_song_inference_results.side_effect = flaky
        with (
            patch(self._PATCH_PARSE, return_value={}),
            patch(self._PATCH_SAVE_TAGS),
            patch(self._PATCH_CHROMAPRINT),
            patch(self._PATCH_TRANSITION),
            patch(self._PATCH_RELEASE),
            patch(self._PATCH_UPDATE_TAGGED),
        ):
            # first attempt fails on the later backbone (after bb1 committed)
            _execute_deferred_writes(db, writes, "worker:tag:0")
            # retry after restart — fresh semantic commands from the same DTO
            _execute_deferred_writes(db, writes, "worker:tag:0")

        # dispatched order: bb1 (attempt), openl3 (failed attempt), then the
        # retry re-dispatches fresh semantic commands bb1 then openl3 — never a
        # replay of partial persistence state or a storage key.
        assert [r[0] for r in received] == ["bb1", "openl3", "bb1", "openl3"]
        for _backbone, song, vectors, streams in received:
            assert song == _song()
            assert isinstance(song, SongIdentity)
            assert all(isinstance(v, BackboneVectorWrite) for v in vectors)
            assert all(isinstance(s, OutputStreamWrite) for s in streams)


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


# ---------------------------------------------------------------------------
# run() shutdown / cancellation / pending-write drain (Q3-D lifecycle)
# ---------------------------------------------------------------------------


class TestRunShutdownLifecycle:
    """``DiscoveryWorker.run`` lifecycle closure for the Q3-D proof.

    Covers cooperative cancellation before any discovery work and the
    shutdown drain of an in-flight deferred write. Both paths must release the
    worker cleanly, mark health ``stopping``, and shut the write executor down
    without an integer Song/storage handle ever entering the loop.
    """

    _PATCH_DISCOVER = "nomarr.components.workers.worker_discovery_comp.discover_and_claim_file"
    _PATCH_SHUTDOWN_AUDIO = "nomarr.components.ml.audio.ml_audio_comp.shutdown_audio_loader"
    _PATCH_SHUTDOWN_HEADS = "nomarr.components.ml.inference.ml_head_pipeline_comp.shutdown_head_pool"
    _PATCH_RELEASE_PROMISES = "nomarr.components.ml.resources.ml_vram_coordinator_comp.release_worker_promises"

    def _run(self, mock_self, setup, discover_result=None):
        from nomarr.services.infrastructure.workers.discovery_worker import DiscoveryWorker

        mock_self._preflight_and_connect.return_value = setup
        with (
            patch(f"{_MODULE}.ThreadPoolExecutor") as mock_executor_cls,
            patch(self._PATCH_SHUTDOWN_AUDIO) as mock_shutdown_audio,
            patch(self._PATCH_SHUTDOWN_HEADS) as mock_shutdown_heads,
            patch(self._PATCH_RELEASE_PROMISES) as mock_release_promises,
            patch(self._PATCH_DISCOVER, return_value=discover_result) as mock_discover,
        ):
            DiscoveryWorker.run(mock_self)
        return mock_executor_cls, mock_discover, mock_release_promises, mock_shutdown_audio, mock_shutdown_heads

    @pytest.mark.unit
    def test_run_cancellation_exits_without_discovery(self):
        """A pre-set stop event cancels the loop before any claim/discovery."""
        mock_self = _make_worker_self()
        mock_self._stop_event.is_set.return_value = True
        db = MagicMock()

        mock_executor_cls, mock_discover, _release_promises, _shutdown_audio, _shutdown_heads = self._run(
            mock_self, (db, MagicMock(), None)
        )

        mock_discover.assert_not_called()
        db.app.update_health.assert_called_once()
        assert db.app.update_health.call_args.kwargs["status"] == "stopping"
        mock_executor_cls.return_value.shutdown.assert_called_once_with(wait=True)

    @pytest.mark.unit
    def test_run_drains_pending_write_on_shutdown(self):
        """An in-flight deferred write is awaited (bounded) before exit."""
        mock_self = _make_worker_self()
        mock_self._stop_event.is_set.side_effect = [False, True]
        mock_self._check_resource_headroom.return_value = None
        mock_self._warm_onnx_cache.return_value = MagicMock()
        pending_write = MagicMock()
        mock_self._process_claimed_file.return_value = (pending_write, True)
        db = MagicMock()

        mock_executor_cls, mock_discover, _release_promises, _shutdown_audio, _shutdown_heads = self._run(
            mock_self, (db, MagicMock(), None), discover_result=_song()
        )

        mock_discover.assert_called_once_with(db, "worker:tag:0")
        pending_write.result.assert_called_once_with(timeout=30)
        db.app.update_health.assert_called_once()
        assert db.app.update_health.call_args.kwargs["status"] == "stopping"
        mock_executor_cls.return_value.shutdown.assert_called_once_with(wait=True)

    @pytest.mark.unit
    def test_run_suppresses_pending_write_error_and_still_completes_shutdown(self):
        """A deferred write that fails during the finally-path drain is logged and
        suppressed: shutdown still runs the executor drain, health marking, VRAM
        promise release, and audio/head teardown without propagating."""
        mock_self = _make_worker_self()
        mock_self._stop_event.is_set.side_effect = [False, True]
        mock_self._check_resource_headroom.return_value = None
        mock_self._warm_onnx_cache.return_value = MagicMock()
        pending_write = MagicMock()
        pending_write.result.side_effect = RuntimeError("deferred write failed")
        mock_self._process_claimed_file.return_value = (pending_write, True)
        db = MagicMock()

        mock_executor_cls, mock_discover, mock_release_promises, mock_shutdown_audio, mock_shutdown_heads = self._run(
            mock_self, (db, MagicMock(), None), discover_result=_song()
        )

        mock_discover.assert_called_once_with(db, "worker:tag:0")
        pending_write.result.assert_called_once_with(timeout=30)
        # The exception is swallowed; shutdown still completes fully.
        mock_executor_cls.return_value.shutdown.assert_called_once_with(wait=True)
        db.app.update_health.assert_called_once()
        assert db.app.update_health.call_args.kwargs["status"] == "stopping"
        mock_release_promises.assert_called_once_with(db, "worker:tag:0")
        mock_shutdown_audio.assert_called_once_with()
        mock_shutdown_heads.assert_called_once_with()
