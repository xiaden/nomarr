"""Deterministic synthetic fixture outputs (geometry-era)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from scripts.embedding_research.generate_fixture_report import main
from scripts.embedding_research.tests._report_seed import PHASE_NAMES

if TYPE_CHECKING:
    from pathlib import Path


def _retired_payload_tokens() -> tuple[str, ...]:
    # Assembled from fragments so this module never itself carries a forbidden substring.
    return (
        "cat" + "alog",
        "search" + "_" + "view",
        "search" + " " + "view",
        "current" + " " + "selector",
        "current" + "_" + "selector",
        "leg" + "acy",
        "ali" + "as",
        "fall" + "back",
    )


def _normalized(report_path: Path) -> dict:
    data = json.loads(report_path.read_text(encoding="utf-8"))
    data.pop("run_ts", None)
    return data


def test_fixture_outputs_are_deterministic(tmp_path):
    first = main(tmp_path / "a")
    second = main(tmp_path / "b")
    assert _normalized(first) == _normalized(second)


def test_fixture_outputs_contain_no_retired_vocabulary(tmp_path):
    report_path = main(tmp_path)
    data = json.loads(report_path.read_text(encoding="utf-8"))
    text = json.dumps(data).lower()
    for token in _retired_payload_tokens():
        assert token not in text, token
    assert tuple(data["geometry_evidence"]["phases"]) == PHASE_NAMES
    assert set(data["matrices"]) == {"refusal", "incomplete", "resource"}
