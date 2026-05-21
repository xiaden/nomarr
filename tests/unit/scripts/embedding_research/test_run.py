"""Unit tests for scripts/embedding_research/run.py."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

from scripts.embedding_research import run
from scripts.embedding_research.config import BACKBONES

_DEFAULT_BACKBONE = next(iter(BACKBONES))
_DEFAULT_SONG_IDS = frozenset(["sid_alpha", "sid_beta", "sid_gamma"])


def _make_cfg(**overrides: object) -> dict:
    values: dict[str, object] = {
        "song_ids": _DEFAULT_SONG_IDS,
        "limit": 25,
        "force": True,
        "backbones": [_DEFAULT_BACKBONE],
        "heads": ["mood", "danceability"],
        "k": 15,
        "workers": 6,
        "blas_threads": 2,
        "device": "cuda",
    }
    values.update(overrides)
    return values


@pytest.mark.unit
def test_embed_calls_flat_and_binned_embed_with_song_ids() -> None:
    con = object()
    cfg = _make_cfg()
    flat_embed = MagicMock(name="flat_embed")
    binned_embed = MagicMock(name="binned_embed")
    flat_module = ModuleType("scripts.embedding_research.strategy_flat")
    flat_module.__dict__["embed"] = flat_embed
    binned_module = ModuleType("scripts.embedding_research.strategy_binned")
    binned_module.__dict__["embed"] = binned_embed

    with patch.dict(
        sys.modules,
        {
            "scripts.embedding_research.strategy_flat": flat_module,
            "scripts.embedding_research.strategy_binned": binned_module,
        },
    ):
        run._embed(con, cfg)

    flat_embed.assert_called_once_with(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        device=cfg["device"],
    )
    binned_embed.assert_called_once_with(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        device=cfg["device"],
    )


@pytest.mark.unit
def test_classify_calls_run_flat_and_run_binned_with_song_ids() -> None:
    con = object()
    cfg = _make_cfg()
    run_flat = MagicMock(name="run_flat")
    run_binned = MagicMock(name="run_binned")
    classify_module = ModuleType("scripts.embedding_research.classify")
    classify_module.__dict__["run_flat"] = run_flat
    classify_module.__dict__["run_binned"] = run_binned

    with patch.dict(sys.modules, {"scripts.embedding_research.classify": classify_module}):
        run._classify(con, cfg)

    run_flat.assert_called_once_with(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        heads=cfg["heads"],
        device=cfg["device"],
    )
    run_binned.assert_called_once_with(
        con,
        song_ids=cfg["song_ids"],
        force=cfg["force"],
        backbones=cfg["backbones"],
        heads=cfg["heads"],
        device=cfg["device"],
    )


@pytest.mark.unit
def test_analyze_calls_all_three_analyze_with_song_ids() -> None:
    con = object()
    cfg = _make_cfg(backbones=[_DEFAULT_BACKBONE], k=20, workers=8, blas_threads=3)
    flat_analyze = MagicMock(name="flat_analyze")
    binned_analyze = MagicMock(name="binned_analyze")
    ctp_analyze = MagicMock(name="ctp_analyze")
    flat_module = ModuleType("scripts.embedding_research.strategy_flat")
    flat_module.__dict__["analyze"] = flat_analyze
    binned_module = ModuleType("scripts.embedding_research.strategy_binned")
    binned_module.__dict__["analyze"] = binned_analyze
    binned_module.__dict__["analyze_ctp"] = ctp_analyze

    with patch.dict(
        sys.modules,
        {
            "scripts.embedding_research.strategy_flat": flat_module,
            "scripts.embedding_research.strategy_binned": binned_module,
        },
    ):
        run._analyze(con, cfg)

    flat_analyze.assert_called_once_with(
        con,
        k=cfg["k"],
        backbones=cfg["backbones"],
        song_ids=cfg["song_ids"],
    )
    binned_analyze.assert_called_once_with(
        con,
        k=cfg["k"],
        backbones=cfg["backbones"],
        workers=cfg["workers"],
        blas_threads=cfg["blas_threads"],
        song_ids=cfg["song_ids"],
    )
    ctp_analyze.assert_called_once_with(
        con,
        k=cfg["k"],
        backbones=cfg["backbones"],
        workers=cfg["workers"],
        blas_threads=cfg["blas_threads"],
        song_ids=cfg["song_ids"],
    )


@pytest.mark.unit
def test_report_calls_report_run_with_connection() -> None:
    con = object()
    report_run = MagicMock(name="report_run")
    report_module = ModuleType("scripts.embedding_research.report")
    report_module.__dict__["run"] = report_run

    with patch.dict(sys.modules, {"scripts.embedding_research.report": report_module}):
        run._report(con, _make_cfg())

    report_run.assert_called_once_with(con)


@pytest.mark.unit
def test_main_install_only_calls_install_and_skips_duckdb_connect() -> None:
    with (
        patch("sys.argv", ["run.py", "--install"]),
        patch.object(run, "_install") as mock_install,
        patch.object(
            run.duckdb, "connect", side_effect=AssertionError("duckdb.connect should not be used")
        ) as mock_connect,
    ):
        run.main()

    mock_install.assert_called_once_with()
    mock_connect.assert_not_called()


@pytest.mark.unit
def test_install_calls_subprocess_with_pip_install_requirements() -> None:
    with patch.object(run.subprocess, "check_call") as mock_check_call:
        run._install()

    mock_check_call.assert_called_once_with([sys.executable, "-m", "pip", "install", "-r", str(run._REQ)])
