"""Corrective Plan E deletion and scientific-hash retention tests."""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

from scripts.embedding_research import validate_fixture_report as validator

PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_deleted_traceability_files_are_absent() -> None:
    assert not (PACKAGE_ROOT / "tests" / "test_gram_traceability.py").exists()
    assert not (PACKAGE_ROOT / "tools" / ("emit_" + "traceability.py")).exists()


def test_validator_has_report_only_surface() -> None:
    source = inspect.getsource(validator)
    retired_option = "-" * 2 + "traceability"
    assert "validate_report" in source
    assert "sha256_bytes" in source
    assert "validate_traceability" not in source
    assert retired_option not in source
    assert "source.commit" not in source
    assert "source.files" not in source
    assert "R1-R14" not in source.replace("Git/source R1-R14", "")


def test_traceability_option_is_not_accepted() -> None:
    retired_option = "-" * 2 + "traceability"
    with pytest.raises(SystemExit) as raised:
        validator.main(["report.json", retired_option, "traceability.json"])
    assert raised.value.code == 2


def test_scientific_hash_helpers_remain_available() -> None:
    payload = b'{"scientific":true}'
    expected = hashlib.sha256(payload).hexdigest()
    assert validator.sha256_bytes(payload) == expected
    assert validator.is_sha256(expected)
    assert not validator.is_sha256("not-a-digest")
