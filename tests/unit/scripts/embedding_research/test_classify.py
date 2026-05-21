"""Unit tests for scripts/embedding_research/classify.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import duckdb
import numpy as np
import pytest

from scripts.embedding_research import classify
from scripts.embedding_research.config import song_id


class _TransparentTqdm(list):
    """Simple iterable progress wrapper used to keep tests deterministic."""

    def __init__(self, items, **_kwargs) -> None:
        super().__init__(items)

    def set_postfix(self, **_kwargs) -> None:
        return None


@pytest.mark.unit
def test_build_flat_done_set_requires_both_pathways() -> None:
    done_rows = {
        ("song-a", "effnet", "mood", "mean", "ptc"),
        ("song-a", "effnet", "mood", "mean", "ctp"),
        ("song-b", "effnet", "mood", "median", "ptc"),
    }

    assert classify._build_flat_done_set(done_rows) == {("song-a", "effnet", "mood", "mean")}


@pytest.mark.unit
def test_build_binned_done_set_drops_bin_ids() -> None:
    done_rows = {
        ("song-a", "effnet", "mood", "temporal_global", 0.5, 0),
        ("song-a", "effnet", "mood", "temporal_global", 0.5, 1),
    }

    assert classify._build_binned_done_set(done_rows) == {("song-a", "effnet", "mood", "temporal_global", 0.5)}


@pytest.mark.unit
def test_public_api_exports_only_run_flat_and_run_binned() -> None:
    assert classify.__all__ == ["run_binned", "run_flat"]
    assert hasattr(classify, "run_flat")
    assert hasattr(classify, "run_binned")
    assert not hasattr(classify, "run")
    assert not hasattr(classify, "main")


@pytest.mark.unit
def test_run_flat_skips_song_when_bulk_cache_is_complete() -> None:
    audio_paths = [Path("song1.mp3"), Path("song2.mp3")]
    sid_done = song_id(audio_paths[0])
    done_rows = {
        (sid_done, "effnet", "mood", strategy_name, pathway)
        for strategy_name in classify.STRATEGIES
        for pathway in ("ptc", "ctp")
    }

    classify_song = MagicMock(side_effect=[True])
    create_session = MagicMock(return_value=object())

    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=audio_paths),
        patch.object(classify, "query_classify_done", return_value=done_rows) as mock_query_done,
        patch.object(classify, "load_pooled_matrix", return_value=(np.empty((0, 0), dtype=np.float32), [], [])),
        patch.object(classify, "_classify_song", classify_song),
        patch.object(classify, "tqdm", new=_TransparentTqdm),
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock(name="run_in_batches")),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", create_session),
    ):
        classify.run_flat(object(), backbones=["effnet"], heads=["mood"])

    mock_query_done.assert_called_once()
    create_session.assert_called_once_with("model.onnx", device="cpu", vram_limit_bytes=classify.HEAD_VRAM_BYTES)
    assert classify_song.call_count == 1
    called_path = classify_song.call_args.args[0]
    assert called_path == audio_paths[1]


@pytest.mark.unit
def test_run_binned_calls_compute_metrics_once_after_processing(tmp_path: Path) -> None:
    audio_paths = [Path("song1.mp3"), Path("song2.mp3")]
    sid_done = song_id(audio_paths[0])
    sidecar = tmp_path / "patches.npy"
    np.save(sidecar, np.ones((4, 3), dtype=np.float32))

    process_song_head = MagicMock(return_value=[("song2", "effnet", "mood", "temporal_global", 0.5, 0, b"ab", 4)])
    compute_metrics = MagicMock(return_value=1)
    create_session = MagicMock(return_value=object())
    done_rows = {(sid_done, "effnet", "mood", "temporal_global", 0.5, 0)}

    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=audio_paths),
        patch.object(classify, "query_binned_classify_done", return_value=done_rows) as mock_query_done,
        patch.object(classify, "_process_song_head", process_song_head),
        patch.object(classify, "compute_metrics", compute_metrics),
        patch.object(classify, "tqdm", new=_TransparentTqdm),
        patch.object(classify, "BIN_MODES", ["temporal_global"]),
        patch.object(classify, "DEFAULT_STD_THRESHOLDS", [0.5]),
        patch.object(classify, "patches_path", return_value=sidecar),
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock(name="run_in_batches")),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", create_session),
    ):
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE binned_classify_ctp ("
            "song_id TEXT, backbone TEXT, head TEXT, bin_mode TEXT, std_thresh DOUBLE, "
            "bin_id INTEGER, act BLOB, weight INTEGER, "
            "PRIMARY KEY (song_id, backbone, head, bin_mode, std_thresh, bin_id))"
        )
        try:
            classify.run_binned(con, backbones=["effnet"], heads=["mood"])
        finally:
            con.close()

    mock_query_done.assert_called_once()
    assert process_song_head.call_count == 1
    compute_metrics.assert_called_once_with(
        ANY,
        backbones=["effnet"],
        bin_modes=["temporal_global"],
        std_thresholds=[0.5],
        heads_filter=["mood"],
        verbose=False,
    )


def _run_in_batches_once(fn, data: np.ndarray, _batch_size: int) -> np.ndarray:
    """Run the provided batch function once over the full array."""
    return np.asarray(fn(data), dtype=np.float32)


def _make_metrics_con() -> duckdb.DuckDBPyConnection:
    """Create an in-memory DuckDB connection for metric tests."""
    con = duckdb.connect(":memory:")
    con.execute(
        "CREATE TABLE binned_head_results ("
        "song_id TEXT, backbone TEXT, head TEXT, bin_mode TEXT, "
        "std_thresh DOUBLE, act BLOB, weight INTEGER)"
    )
    con.execute(
        "CREATE TABLE binned_classify_ctp ("
        "song_id TEXT, backbone TEXT, head TEXT, bin_mode TEXT, "
        "std_thresh DOUBLE, act BLOB, weight INTEGER)"
    )
    con.execute(
        "CREATE TABLE binned_ptc_ctp_metrics ("
        "backbone TEXT, bin_mode TEXT, std_thresh DOUBLE, head TEXT, "
        "divergence_mean DOUBLE, bin_count_var DOUBLE, sim_align_corr DOUBLE, "
        "PRIMARY KEY (backbone, bin_mode, std_thresh, head))"
    )
    return con


@pytest.mark.unit
def test_classify_song_skips_when_all_strategies_in_done_set() -> None:
    path = Path("song1.mp3")
    sid = song_id(path)
    done_set = {(sid, "effnet", "mood", strategy_name) for strategy_name in classify.STRATEGIES}

    with patch.object(classify, "upsert_head") as upsert_head:
        result = classify._classify_song(
            path,
            "effnet",
            "mood",
            object(),
            _run_in_batches_once,
            8,
            object(),
            {},
            done_set=done_set,
            force=False,
        )

    assert result is False
    upsert_head.assert_not_called()


@pytest.mark.unit
def test_classify_song_skips_when_sidecar_missing(tmp_path: Path) -> None:
    path = Path("song1.mp3")
    missing_sidecar = tmp_path / "missing.npy"

    with patch.object(classify, "patches_path", return_value=missing_sidecar):
        result = classify._classify_song(
            path,
            "effnet",
            "mood",
            object(),
            _run_in_batches_once,
            8,
            object(),
            {},
            done_set=None,
            force=False,
        )

    assert result is False


@pytest.mark.unit
def test_classify_song_returns_false_for_empty_patches(tmp_path: Path) -> None:
    path = Path("song1.mp3")
    sidecar = tmp_path / "sidecar.npy"
    np.save(sidecar, np.empty((0, 64), dtype=np.float32))

    with patch.object(classify, "patches_path", return_value=sidecar):
        result = classify._classify_song(
            path,
            "effnet",
            "mood",
            object(),
            _run_in_batches_once,
            8,
            object(),
            {},
            done_set=None,
            force=False,
        )

    assert result is False


@pytest.mark.unit
def test_classify_song_raises_on_inference_error(tmp_path: Path) -> None:
    path = Path("song1.mp3")
    sidecar = tmp_path / "sidecar.npy"
    np.save(sidecar, np.ones((4, 3), dtype=np.float32))

    def broken_run_in_batches(_fn, _data, _batch_size: int) -> np.ndarray:
        raise ValueError("inference failed")

    with (
        patch.object(classify, "patches_path", return_value=sidecar),
        pytest.raises(RuntimeError, match="CTP head inference failed"),
    ):
        classify._classify_song(
            path,
            "effnet",
            "mood",
            object(),
            broken_run_in_batches,
            8,
            object(),
            {},
            done_set=None,
            force=False,
        )


@pytest.mark.unit
def test_classify_song_writes_ptc_and_ctp_for_all_strategies(tmp_path: Path) -> None:
    path = Path("song1.mp3")
    sidecar = tmp_path / "sidecar.npy"
    np.save(sidecar, np.arange(12, dtype=np.float32).reshape(4, 3))

    def fake_run(output_names, inputs) -> list[np.ndarray]:
        _ = output_names
        batch = inputs["embeddings"]
        acts = np.tile(np.array([0.3, 0.7], dtype=np.float32), (batch.shape[0], 1))
        return [acts]

    head_session = MagicMock()
    head_session.run.side_effect = fake_run

    with (
        patch.object(classify, "patches_path", return_value=sidecar),
        patch.object(classify, "upsert_head") as upsert_head,
    ):
        result = classify._classify_song(
            path,
            "effnet",
            "mood",
            head_session,
            _run_in_batches_once,
            8,
            object(),
            {},
            done_set=None,
            force=False,
        )

    assert result is True
    assert upsert_head.call_count == 2 * len(classify.STRATEGIES)


@pytest.mark.unit
def test_process_song_head_skips_when_all_done() -> None:
    sid = "song1"
    done_set = {(sid, "effnet", "mood", bin_mode, 0.5) for bin_mode in classify.BIN_MODES}

    result = classify._process_song_head(
        sid,
        "effnet",
        "mood",
        object(),
        _run_in_batches_once,
        8,
        np.random.rand(4, 3).astype(np.float32),
        [0.5],
        force=False,
        done_set=done_set,
    )

    assert result == []


@pytest.mark.unit
def test_process_song_head_returns_empty_for_zero_acts() -> None:
    patches = np.random.rand(4, 3).astype(np.float32)

    def empty_run_in_batches(_fn, _data, _batch_size: int) -> np.ndarray:
        return np.empty((0, 2), dtype=np.float32)

    result = classify._process_song_head(
        "song1",
        "effnet",
        "mood",
        object(),
        empty_run_in_batches,
        8,
        patches,
        [0.5],
        force=False,
        done_set=None,
    )

    assert result == []


@pytest.mark.unit
def test_process_song_head_handles_degenerate_std() -> None:
    patches = np.ones((4, 3), dtype=np.float32)

    def fake_run(output_names, inputs) -> list[np.ndarray]:
        _ = output_names
        n_rows = inputs["embeddings"].shape[0]
        acts = np.zeros((n_rows, 2), dtype=np.float32)
        acts[:, 1] = 0.5
        return [acts]

    head_session = MagicMock()
    head_session.run.side_effect = fake_run

    rows = classify._process_song_head(
        "song1",
        "effnet",
        "mood",
        head_session,
        _run_in_batches_once,
        8,
        patches,
        [1.0],
        force=True,
        done_set=None,
    )

    assert isinstance(rows, list)


@pytest.mark.unit
def test_process_song_head_returns_rows_for_valid_input() -> None:
    patches = np.random.rand(10, 3).astype(np.float32)
    scores = np.array([0.8] * 5 + [0.2] * 5, dtype=np.float32)

    def fake_run(output_names, inputs) -> list[np.ndarray]:
        _ = output_names
        n_rows = inputs["embeddings"].shape[0]
        acts = np.zeros((n_rows, 2), dtype=np.float32)
        acts[:, 1] = scores[:n_rows]
        return [acts]

    head_session = MagicMock()
    head_session.run.side_effect = fake_run

    rows = classify._process_song_head(
        "song1",
        "effnet",
        "mood",
        head_session,
        _run_in_batches_once,
        8,
        patches,
        [0.5],
        force=False,
        done_set=None,
    )

    assert rows
    assert all(len(row) == 8 for row in rows)
    assert {row[1] for row in rows} == {"effnet"}
    assert {row[2] for row in rows} == {"mood"}
    assert {row[3] for row in rows}.issubset(set(classify.BIN_MODES))


@pytest.mark.unit
def test_weighted_song_score_returns_none_for_empty_rows() -> None:
    assert classify._weighted_song_score([]) is None


@pytest.mark.unit
def test_weighted_song_score_returns_none_when_all_blobs_too_small() -> None:
    small_blob = np.array([0.7], dtype=np.float32).tobytes()

    assert classify._weighted_song_score([(small_blob, 1)]) is None


@pytest.mark.unit
def test_weighted_song_score_returns_weighted_average() -> None:
    blob_high = np.array([0.2, 0.8], dtype=np.float32).tobytes()
    blob_low = np.array([0.8, 0.2], dtype=np.float32).tobytes()

    result = classify._weighted_song_score([(blob_high, 2), (blob_low, 3)])

    assert result == pytest.approx(0.44, abs=1e-5)


@pytest.mark.unit
def test_weighted_song_score_returns_none_for_zero_weight() -> None:
    small_blob = np.array([0.5], dtype=np.float32).tobytes()

    assert classify._weighted_song_score([(small_blob, 5), (small_blob, 3)]) is None


@pytest.mark.unit
def test_safe_pearson_returns_zero_for_single_element() -> None:
    assert classify._safe_pearson(np.array([1.0]), np.array([2.0])) == 0.0


@pytest.mark.unit
def test_safe_pearson_returns_zero_for_constant_x() -> None:
    assert classify._safe_pearson(np.array([1.0, 1.0, 1.0]), np.array([1.0, 2.0, 3.0])) == 0.0


@pytest.mark.unit
def test_safe_pearson_returns_zero_for_constant_y() -> None:
    assert classify._safe_pearson(np.array([1.0, 2.0, 3.0]), np.array([5.0, 5.0, 5.0])) == 0.0


@pytest.mark.unit
def test_safe_pearson_returns_positive_correlation() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([2.0, 4.0, 5.0, 4.0, 5.0])

    result = classify._safe_pearson(x, y)

    assert 0.0 < result <= 1.0


@pytest.mark.unit
def test_safe_pearson_returns_negative_correlation() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    y = np.array([5.0, 4.0, 3.0, 2.0, 1.0])

    result = classify._safe_pearson(x, y)

    assert result == pytest.approx(-1.0, abs=1e-6)


@pytest.mark.unit
def test_compute_metrics_returns_zero_when_no_data() -> None:
    con = _make_metrics_con()
    try:
        with patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True):
            result = classify.compute_metrics(con, ["effnet"], ["temporal_global"], [0.5], None)
    finally:
        con.close()

    assert result == 0


@pytest.mark.unit
def test_compute_metrics_skips_when_no_shared_songs() -> None:
    con = _make_metrics_con()
    blob = np.array([0.3, 0.7], dtype=np.float32).tobytes()
    try:
        con.execute(
            "INSERT INTO binned_head_results VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["song-a", "effnet", "mood", "temporal_global", 0.5, blob, 1],
        )
        con.execute(
            "INSERT INTO binned_classify_ctp VALUES (?, ?, ?, ?, ?, ?, ?)",
            ["song-b", "effnet", "mood", "temporal_global", 0.5, blob, 1],
        )
        with patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True):
            result = classify.compute_metrics(con, ["effnet"], ["temporal_global"], [0.5], None)
    finally:
        con.close()

    assert result == 0


@pytest.mark.unit
def test_compute_metrics_upserts_rows_for_shared_songs() -> None:
    con = _make_metrics_con()
    blob_high = np.array([0.3, 0.7], dtype=np.float32).tobytes()
    try:
        for table_name in ("binned_head_results", "binned_classify_ctp"):
            con.execute(
                f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["song-a", "effnet", "mood", "temporal_global", 0.5, blob_high, 2],
            )
            con.execute(
                f"INSERT INTO {table_name} VALUES (?, ?, ?, ?, ?, ?, ?)",
                ["song-b", "effnet", "mood", "temporal_global", 0.5, blob_high, 1],
            )

        with patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True):
            result = classify.compute_metrics(con, ["effnet"], ["temporal_global"], [0.5], None)

        row = con.execute("SELECT backbone, head, divergence_mean FROM binned_ptc_ctp_metrics").fetchone()
    finally:
        con.close()

    assert result == 1
    assert row is not None
    assert row[0] == "effnet"
    assert row[1] == "mood"
    assert row[2] == pytest.approx(0.0, abs=1e-5)


@pytest.mark.unit
def test_compute_metrics_verbose_prints_skip_when_no_overlap(capsys) -> None:
    con = _make_metrics_con()
    try:
        with patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True):
            result = classify.compute_metrics(con, ["effnet"], ["temporal_global"], [0.5], None, verbose=True)
    finally:
        con.close()

    captured = capsys.readouterr()
    assert result == 0
    assert "no overlap" in captured.out or "skip" in captured.out


@pytest.mark.unit
def test_run_flat_logs_error_on_session_creation_failure(capsys) -> None:
    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=[]),
        patch.object(classify, "query_classify_done", return_value=set()),
        patch.object(classify, "load_pooled_matrix", return_value=(np.empty((0, 0), dtype=np.float32), [], [])),
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock()),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", side_effect=RuntimeError("load failed")),
    ):
        classify.run_flat(object(), backbones=["effnet"], heads=["mood"])

    captured = capsys.readouterr()
    assert "ERROR" in captured.out or "load failed" in captured.out


@pytest.mark.unit
def test_run_flat_logs_verbose_error_on_classify_exception() -> None:
    audio_paths = [Path("song1.mp3")]
    create_session = MagicMock(return_value=object())

    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=audio_paths),
        patch.object(classify, "query_classify_done", return_value=set()),
        patch.object(classify, "load_pooled_matrix", return_value=(np.empty((0, 0), dtype=np.float32), [], [])),
        patch.object(classify, "_classify_song", side_effect=RuntimeError("boom")),
        patch.object(classify, "tqdm", new=_TransparentTqdm),
        patch.object(_TransparentTqdm, "write", create=True) as mock_write,
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock()),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", create_session),
    ):
        classify.run_flat(object(), backbones=["effnet"], heads=["mood"], verbose=True)

    create_session.assert_called_once()
    mock_write.assert_called_once()
    assert "boom" in mock_write.call_args.args[0]


@pytest.mark.unit
def test_run_binned_logs_error_on_session_creation_failure(capsys) -> None:
    compute_metrics = MagicMock(return_value=0)

    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=[]),
        patch.object(classify, "query_binned_classify_done", return_value=set()),
        patch.object(classify, "compute_metrics", compute_metrics),
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock()),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", side_effect=RuntimeError("load failed")),
    ):
        classify.run_binned(object(), backbones=["effnet"], heads=["mood"])

    captured = capsys.readouterr()
    assert "ERROR" in captured.out or "load failed" in captured.out
    compute_metrics.assert_called_once()


@pytest.mark.unit
def test_run_binned_skips_song_when_sidecar_missing(tmp_path: Path) -> None:
    audio_paths = [Path("song1.mp3")]
    missing_sidecar = tmp_path / "missing.npy"
    process_song_head = MagicMock()
    compute_metrics = MagicMock(return_value=0)
    create_session = MagicMock(return_value=object())

    with (
        patch.object(classify, "bootstrap_nomarr"),
        patch.object(classify, "discover_audio", return_value=audio_paths),
        patch.object(classify, "query_binned_classify_done", return_value=set()),
        patch.object(classify, "_process_song_head", process_song_head),
        patch.object(classify, "compute_metrics", compute_metrics),
        patch.object(classify, "tqdm", new=_TransparentTqdm),
        patch.object(classify, "patches_path", return_value=missing_sidecar),
        patch.dict(classify.HEADS, {"effnet": {"mood": "model.onnx"}}, clear=True),
        patch("nomarr.components.ml.onnx.ml_session_comp._BACKBONE_BATCH_SIZE", 8),
        patch("nomarr.components.ml.onnx.ml_session_comp._run_in_batches", MagicMock()),
        patch("nomarr.components.ml.onnx.ml_session_comp.create_session", create_session),
    ):
        classify.run_binned(object(), backbones=["effnet"], heads=["mood"])

    create_session.assert_called_once()
    process_song_head.assert_not_called()
    compute_metrics.assert_called_once()
