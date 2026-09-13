"""Scientific evidence output-path hygiene tests."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from scripts.embedding_research.config import OUTPUT_ROOT, PATCHES_DIR, RUNTIME_ROOT
from scripts.embedding_research.tests import _gram_evidence
from scripts.embedding_research.tools import _evidence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


def test_evidence_root_is_configured_root() -> None:
    assert _evidence.EVIDENCE_ROOT is OUTPUT_ROOT
    assert _gram_evidence.EVIDENCE_ROOT is OUTPUT_ROOT
    assert PATCHES_DIR.is_relative_to(RUNTIME_ROOT)
    assert not PATCHES_DIR.is_relative_to(OUTPUT_ROOT)


def test_write_evidence_accepts_relative_and_in_root_absolute(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_evidence, "OUTPUT_ROOT", tmp_path)
    monkeypatch.setattr(_evidence, "EVIDENCE_ROOT", tmp_path)

    relative = _evidence.write_evidence("nested/relative.json", {"b": 2, "a": 1})
    absolute = _evidence.write_evidence(tmp_path / "absolute.json", {"value": True})

    assert relative == (tmp_path / "nested/relative.json").resolve()
    assert absolute == (tmp_path / "absolute.json").resolve()
    assert relative.read_bytes() == b'{"a":1,"b":2}'


@pytest.mark.parametrize("name", ["../escape.json", "nested/../../escape.json", "report.html", "report"])
def test_write_evidence_rejects_invalid_destinations_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    monkeypatch.setattr(_evidence, "OUTPUT_ROOT", tmp_path)
    destination = tmp_path / name

    with pytest.raises(ValueError):
        _evidence.write_evidence(destination, {"value": 1})

    assert not destination.exists()
    assert not (tmp_path.parent / "escape.json").exists()


def test_fixture_helper_preserves_digest_and_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_gram_evidence, "EVIDENCE_ROOT", tmp_path)

    record = _gram_evidence.emit_evidence("fixture/nested.json", {"z": 3, "a": 1})
    path = tmp_path / "fixture/nested.json"

    assert json.loads(path.read_text(encoding="utf-8")) == record
    assert record["evidence_sha256"] == _gram_evidence.sha256_bytes(b'{"a":1,"z":3}')


@pytest.mark.parametrize("name", ["../escape.json", "fixture/../../escape.json", "fixture/report.html"])
def test_fixture_helper_rejects_escape_and_non_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    monkeypatch.setattr(_gram_evidence, "EVIDENCE_ROOT", tmp_path)

    with pytest.raises(ValueError):
        _gram_evidence.emit_evidence(name, {"value": 1})

    assert not (tmp_path.parent / "escape.json").exists()


def test_research_db_path_inside_output_root_is_rejected_before_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    import scripts.embedding_research.config as config

    candidate = config.OUTPUT_ROOT / "research-test" / "research.duckdb"
    monkeypatch.setenv("RESEARCH_DB_PATH", str(candidate))
    with pytest.raises(ValueError, match="outside OUTPUT_ROOT"):
        importlib.reload(config)
    assert not candidate.exists()
    monkeypatch.delenv("RESEARCH_DB_PATH")
    importlib.reload(config)
