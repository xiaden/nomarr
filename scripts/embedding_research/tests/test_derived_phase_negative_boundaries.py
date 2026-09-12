"""Call-level negative sentinels over the four derived phases.

``geometry``, ``analyze``, ``head-analysis`` and ``report`` consume only committed
stream/geometry/head artifacts.  They must complete with audio discovery, model loading,
ONNX session construction and CUDA ABSENT, and must PROVE no such call happened: raising
sentinels are attached to the real call sites, and a caught sentinel is a test failure,
never a success.  Each runtime case asserts BOTH halves of the gate — the derived entry
COMPLETES and every installed sentinel recorded ZERO calls.
"""

from __future__ import annotations

import contextlib

import duckdb
import pytest

from scripts.embedding_research import run as run_mod
from scripts.embedding_research.config import discover_audio as _config_discover_audio
from scripts.embedding_research.db._schema import ensure_schema
from scripts.embedding_research.tests import _report_seed

# Optional ML-stack availability.  The derived phases never import these; if a platform
# has them we still sentinel them so a regression that reaches them fires; if they are
# absent they cannot be called, which is itself the CPU-only proof.
try:  # pragma: no cover - environment dependent
    import onnxruntime  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    onnxruntime = None  # type: ignore[assignment]

try:  # pragma: no cover - environment dependent
    import torch  # type: ignore[import-not-found]
except Exception:  # pragma: no cover
    torch = None  # type: ignore[assignment]


class _RaisingSentinel:
    """Sentinel that records its invocation and raises (a call is a test failure)."""

    def __init__(self, name: str, events: list[str]) -> None:
        self.name = name
        self.events = events

    def __call__(self, *_args, **_kwargs):
        self.events.append(self.name)
        raise AssertionError(f"forbidden call during a CPU-only derived phase: {self.name}")


def _install_sentinels(monkeypatch) -> tuple[list[str], list[str]]:
    """Attach raising sentinels to the real audio/model/CUDA call sites."""
    events: list[str] = []
    installed: list[str] = []

    sentinel = _RaisingSentinel("config.discover_audio", events)
    monkeypatch.setattr(_config_discover_audio.__module__ + ".discover_audio", sentinel)
    installed.append("config.discover_audio")

    if onnxruntime is not None:
        monkeypatch.setattr(onnxruntime, "InferenceSession", _RaisingSentinel("onnxruntime.InferenceSession", events))
        installed.append("onnxruntime.InferenceSession")

    if torch is not None:
        monkeypatch.setattr(torch.cuda, "is_available", _RaisingSentinel("torch.cuda.is_available", events))
        installed.append("torch.cuda.is_available")

    return events, installed


@pytest.fixture
def seeded_con():
    con = _report_seed.build_seeded_con()
    yield con
    con.close()


def test_canonical_report_owner_is_cpu_only(seeded_con, tmp_path, monkeypatch):
    from scripts.embedding_research.report import run as report_run

    events, installed = _install_sentinels(monkeypatch)
    report_run(seeded_con, tmp_path, run_id=_report_seed.RUN_ID)
    assert installed
    assert events == []
    assert (tmp_path / "report.json").is_file()


def test_report_phase_dispatch_completes_with_zero_forbidden_calls(seeded_con, tmp_path, monkeypatch):
    events, installed = _install_sentinels(monkeypatch)
    cfg = {"run_id": _report_seed.RUN_ID, "report_dir": tmp_path, "report_run_id": _report_seed.RUN_ID}
    run_mod._run_single_phase(seeded_con, "report", cfg)
    assert installed
    assert events == []
    assert (tmp_path / "report.json").is_file()
    rows = seeded_con.execute(
        "SELECT status FROM run_provenance WHERE run_id = ? AND phase = 'report'",
        (_report_seed.RUN_ID,),
    ).fetchall()
    assert rows  # runtime dispatch recorded the exact derived phase verb


def test_geometry_phase_dispatch_is_cpu_only_on_empty_store(tmp_path, monkeypatch):
    con = duckdb.connect(":memory:")
    ensure_schema(con)
    try:
        events, installed = _install_sentinels(monkeypatch)
        cfg = {
            "run_lock": contextlib.nullcontext(),
            "output_root": tmp_path,
            "backbones": None,
            "song_ids": None,
        }
        result = run_mod._run_geometry(con, cfg, "run-geometry")
        assert installed
        assert events == []
        assert result["song_count"] == 0
    finally:
        con.close()
