"""Tests for raw output stream packaging in process_file_workflow."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.components.ml.inference.ml_backbone_embed_comp import BackboneEmbedding, BackboneEmbeddingResult
from nomarr.helpers.dto.ml_dto import LoadAudioMonoResult, ProcessHeadPredictionsResult, RawOutputStream
from nomarr.helpers.dto.processing_dto import DeferredOutputStreamWrite, ProcessorConfig
from nomarr.workflows.processing.process_file_wf import process_file_workflow


@pytest.mark.unit
@pytest.mark.mocked
def test_process_file_workflow_packages_resolved_output_streams_and_skips_missing_indexes() -> None:
    """Resolved output-index mappings become deferred writes; missing ones are skipped."""
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
            ]
        },
        per_head_timings={},
    )

    with (
        patch("nomarr.workflows.processing.process_file_wf.build_library_path_from_db", return_value=library_path),
        patch("nomarr.workflows.processing.process_file_wf.compute_model_suite_hash", return_value="suite-hash"),
        patch(
            "nomarr.workflows.processing.process_file_wf.load_audio_mono",
            return_value=LoadAudioMonoResult(waveform=MagicMock(), sample_rate=16000, duration=120.0),
        ),
        patch("nomarr.workflows.processing.process_file_wf.should_skip_short", return_value=False),
        patch("nomarr.workflows.processing.process_file_wf.compute_chromaprint", return_value="fp"),
        patch("nomarr.workflows.processing.process_file_wf.compute_backbone_embeddings", return_value=embed_result),
        patch("nomarr.workflows.processing.process_file_wf.run_heads", return_value=head_result),
        patch("nomarr.workflows.processing.process_file_wf.persist_backbone_vector", return_value=None),
        patch("nomarr.workflows.processing.process_file_wf.collect_mood_outputs", return_value={}),
        patch(
            "nomarr.workflows.processing.process_file_wf.build_model_output_index_map",
            return_value={model_path: {0: "ml_model_outputs/out-0", 2: "ml_model_outputs/out-2"}},
        ) as build_output_index_map_mock,
        patch("nomarr.workflows.processing.process_file_wf.build_timing_summary", return_value="timing-summary"),
    ):
        result = process_file_workflow(
            path="song.flac",
            config=config,
            cache=cache,
            db=mock_db,
            file_id="library_files/file-1",
        )

    build_output_index_map_mock.assert_called_once_with(mock_db)
    assert result.deferred_writes is not None
    assert result.deferred_writes.raw_output_streams == [
        DeferredOutputStreamWrite(output_id="ml_model_outputs/out-0", values=[0.1, 0.9]),
        DeferredOutputStreamWrite(output_id="ml_model_outputs/out-2", values=[0.7, 0.3]),
    ]
