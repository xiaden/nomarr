"""Tests for raw output stream packaging in process_file_workflow."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.audio.ml_audio_comp import AudioLoadCrashError
from nomarr.components.ml.inference.ml_backbone_embed_comp import BackboneEmbedding, BackboneEmbeddingResult
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import LibraryIdentity, SongIdentity
from nomarr.helpers.dataclasses.vector_dataclass import BackboneVectorWrite
from nomarr.helpers.dto.ml_dto import LoadAudioMonoResult, ProcessHeadPredictionsResult, RawOutputStream
from nomarr.helpers.dto.processing_dto import DeferredBackboneVectorWrite, DeferredOutputStreamWrite, ProcessorConfig
from nomarr.workflows.processing.process_file_wf import process_file_workflow


def _song() -> SongIdentity:
    return SongIdentity(
        library=LibraryIdentity(library_uuid="2621ebfb-71ff-5168-a812-5342ca310e8c", name="music", root_path="/music"),
        normalized_path="song.flac",
    )


@pytest.mark.unit
@pytest.mark.mocked
def test_process_file_workflow_packages_resolved_output_streams_and_skips_missing_indexes(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Registered output-index mappings become deferred writes; missing ones and unregistered paths are skipped.

    Only the single semantic registry association (``model_output_index_map``) is
    performed, and it attaches the registry-provided stable string ``output_id``
    to typed ``DeferredOutputStreamWrite`` commands. Missing output indexes and
    unregistered model paths are skipped with the existing warnings.
    """
    config = ProcessorConfig(
        models_dir="models",
        min_duration_s=30,
        allow_short=False,
        batch_size=4,
        namespace="nom",
        version_tag_key="tagger_version",
        tagger_version="v-test",
    )
    model_path = "models/heads/genre.onnx"
    unregistered_model_path = "models/heads/unregistered.onnx"
    head_model = cast("Any", SimpleNamespace(meta=SimpleNamespace(name="genre-head")))
    cache = cast(
        "Any",
        SimpleNamespace(
            warm=True,
            heads={"bb1": [head_model]},
            backbones={"bb1": SimpleNamespace(preprocess_params=SimpleNamespace(sample_rate=16000))},
        ),
    )
    mock_db = MagicMock()
    mock_db.ml.model_output_index_map.return_value = {
        model_path: {0: "ml_model_outputs/out-0", 2: "ml_model_outputs/out-2"}
    }
    library_path = MagicMock()
    library_path.is_valid.return_value = True
    library_path.absolute = Path("/music/song.flac")
    library_path.library_id = "libraries/lib1"
    embed_result = BackboneEmbeddingResult(
        embeddings=[BackboneEmbedding(backbone="bb1", heads=[head_model], embeddings=MagicMock())],
        errors={},
        timings={},
    )
    head_result = ProcessHeadPredictionsResult(
        heads_succeeded=1,
        head_results={"genre-head": {"status": "success"}},
        regression_heads=[],
        all_head_outputs=[],
        raw_output_streams_by_model_path={
            model_path: [
                RawOutputStream(output_index=0, values=[0.1, 0.9]),
                RawOutputStream(output_index=1, values=[0.4, 0.6]),
                RawOutputStream(output_index=2, values=[0.7, 0.3]),
            ],
            unregistered_model_path: [RawOutputStream(output_index=0, values=[0.5, 0.5])],
        },
        per_head_timings={},
    )

    with (
        caplog.at_level(logging.WARNING, logger="nomarr.workflows.processing.process_file_wf"),
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.compute_model_suite_hash", return_value="suite-hash"),
        patch(
            "nomarr.workflows.processing.process_file_wf.load_audio_mono",
            return_value=LoadAudioMonoResult(waveform=MagicMock(), sample_rate=16000, duration=120.0),
        ),
        patch("nomarr.workflows.processing.process_file_wf.compute_chromaprint", return_value="fp"),
        patch("nomarr.workflows.processing.process_file_wf.compute_backbone_embeddings", return_value=embed_result),
        patch("nomarr.workflows.processing.process_file_wf.run_heads", return_value=head_result),
        patch(
            "nomarr.workflows.processing.process_file_wf.persist_backbone_vector",
            return_value=BackboneVectorWrite(
                vector=(0.25, 0.25),
                model_suite_hash="suite-hash",
                num_segments=3,
            ),
        ) as persist_vector_mock,
        patch("nomarr.workflows.processing.process_file_wf.collect_mood_outputs", return_value={}),
        patch("nomarr.workflows.processing.process_file_wf.build_timing_summary", return_value="timing-summary"),
    ):
        result = process_file_workflow(
            path="song.flac",
            config=config,
            cache=cache,
            db=mock_db,
            song=_song(),
        )

    mock_db.ml.model_output_index_map.assert_called_once_with()
    persist_vector_mock.assert_called_once()
    assert persist_vector_mock.call_args.args[0] == "bb1"
    assert persist_vector_mock.call_args.args[2] == "suite-hash"
    assert result.tags is not None
    assert result.tags.to_dict() == {"tagger_version": ("v-test",)}
    assert result.deferred_writes is not None
    assert result.deferred_writes.song == _song()
    assert result.deferred_writes.backbone_vectors == [
        DeferredBackboneVectorWrite(
            backbone="bb1",
            vectors=[
                BackboneVectorWrite(
                    vector=(0.25, 0.25),
                    model_suite_hash="suite-hash",
                    num_segments=3,
                )
            ],
        )
    ]
    assert result.deferred_writes.raw_output_streams == [
        DeferredOutputStreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9], output_index=0),
        DeferredOutputStreamWrite(output_id="ml_model_outputs/out-2", values=[0.7, 0.3], output_index=2),
    ]
    # No storage-shaped keys / storage ids anywhere on the deferred payloads.
    assert not hasattr(result.deferred_writes, "file_id")
    vector_cmd = result.deferred_writes.backbone_vectors[0].vectors[0]
    assert isinstance(vector_cmd, BackboneVectorWrite)
    # Registry gating warnings are preserved: one for the unregistered model
    # path, one for the missing output index (index 1 on the registered path).
    warning_messages = [record.message for record in caplog.records if record.levelno == logging.WARNING]
    assert any("Missing output registry for models/heads/unregistered.onnx" in m for m in warning_messages)
    assert any(f"Missing output id for {model_path}[1]" in m for m in warning_messages)


@pytest.mark.unit
@pytest.mark.mocked
def test_audio_load_crash_preserves_song_record() -> None:
    """Decoder crashes return a retryable result without deleting song data."""
    config = ProcessorConfig(
        models_dir="models",
        min_duration_s=30,
        allow_short=False,
        batch_size=4,
        namespace="nom",
        version_tag_key="tagger_version",
        tagger_version="v-test",
    )
    head = cast("Any", SimpleNamespace(meta=SimpleNamespace(name="genre-head")))
    cache = cast(
        "Any",
        SimpleNamespace(
            warm=True,
            heads={"bb1": [head]},
            backbones={"bb1": SimpleNamespace(preprocess_params=SimpleNamespace(sample_rate=16000))},
        ),
    )
    db = MagicMock()
    library_path = MagicMock()
    library_path.is_valid.return_value = True
    library_path.absolute = Path("/music/song.flac")

    with (
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.compute_model_suite_hash", return_value="suite-hash"),
        patch(
            "nomarr.workflows.processing.process_file_wf.load_audio_mono",
            side_effect=AudioLoadCrashError("decoder unavailable"),
        ),
        patch("nomarr.workflows.processing.process_file_wf.bulk_delete_songs") as delete_mock,
    ):
        result = process_file_workflow("song.flac", config, cache, db, song=_song())

    delete_mock.assert_not_called()
    assert result.head_results == {"_crash": {"status": "crash", "reason": "decoder unavailable"}}
    assert result.tags is None


@pytest.mark.unit
@pytest.mark.mocked
def test_not_found_path_returns_result_with_tags_none() -> None:
    """A missing file on disk returns a cleanup result with ``tags=None``."""
    config = ProcessorConfig(
        models_dir="models",
        min_duration_s=30,
        allow_short=False,
        batch_size=4,
        namespace="nom",
        version_tag_key="tagger_version",
        tagger_version="v-test",
    )
    cache = cast("Any", SimpleNamespace(warm=False))
    db = MagicMock()
    library = Library(name="music", root_path="C:/music")
    db.library.get_library_by_name.return_value = library
    library_path = MagicMock()
    library_path.is_valid.return_value = False
    library_path.status = "not_found"
    library_path.reason = "file missing on disk"
    library_path.library_id = "music"

    with (
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.bulk_delete_songs") as delete_mock,
    ):
        result = process_file_workflow("song.flac", config, cache, db, song=_song())

    delete_mock.assert_called_once_with(db, ["song.flac"], library)
    assert result.tags is None
    assert result.head_results == {"_not_found": {"status": "not_found", "reason": "file missing on disk"}}


@pytest.mark.unit
@pytest.mark.mocked
def test_not_found_path_skips_delete_when_library_gone() -> None:
    """When the library no longer exists, missing-file cleanup is skipped without error."""
    config = ProcessorConfig(
        models_dir="models",
        min_duration_s=30,
        allow_short=False,
        batch_size=4,
        namespace="nom",
        version_tag_key="tagger_version",
        tagger_version="v-test",
    )
    cache = cast("Any", SimpleNamespace(warm=False))
    db = MagicMock()
    db.library.get_library_by_name.return_value = None
    library_path = MagicMock()
    library_path.is_valid.return_value = False
    library_path.status = "not_found"
    library_path.reason = "file missing on disk"
    library_path.library_id = "music"

    with (
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.bulk_delete_songs") as delete_mock,
    ):
        result = process_file_workflow("song.flac", config, cache, db, song=_song())

    delete_mock.assert_not_called()
    assert result.tags is None
    assert result.head_results == {"_not_found": {"status": "not_found", "reason": "file missing on disk"}}


@pytest.mark.unit
@pytest.mark.mocked
def test_all_heads_skipped_returns_tags_none() -> None:
    """When every head is skipped (e.g. short audio) the result carries ``tags=None``."""
    config = ProcessorConfig(
        models_dir="models",
        min_duration_s=30,
        allow_short=False,
        batch_size=4,
        namespace="nom",
        version_tag_key="tagger_version",
        tagger_version="v-test",
    )
    head = cast("Any", SimpleNamespace(meta=SimpleNamespace(name="genre-head")))
    cache = cast(
        "Any",
        SimpleNamespace(
            warm=True,
            heads={"bb1": [head]},
            backbones={"bb1": SimpleNamespace(preprocess_params=SimpleNamespace(sample_rate=16000))},
        ),
    )
    db = MagicMock()
    library_path = MagicMock()
    library_path.is_valid.return_value = True
    library_path.absolute = Path("/music/song.flac")
    library_path.library_id = "libraries/lib1"
    embed_result = BackboneEmbeddingResult(embeddings=[], errors={"bb1": "audio too short"}, timings={})

    with (
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.compute_model_suite_hash", return_value="suite-hash"),
        patch(
            "nomarr.workflows.processing.process_file_wf.load_audio_mono",
            return_value=LoadAudioMonoResult(waveform=MagicMock(), sample_rate=16000, duration=5.0),
        ),
        patch("nomarr.workflows.processing.process_file_wf.compute_chromaprint", return_value="fp"),
        patch("nomarr.workflows.processing.process_file_wf.compute_backbone_embeddings", return_value=embed_result),
    ):
        result = process_file_workflow("song.flac", config, cache, db, song=_song())

    assert result.tags is None
    assert result.head_results == {"genre-head": {"status": "skipped", "reason": "audio too short"}}
