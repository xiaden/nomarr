"""Tests for asr_md helper — ASR markdown parsing and generation."""

import textwrap
from pathlib import Path
from typing import Any, cast

import pytest

from mcp_code_intel.helpers.asr_md import (
    ASR,
    generate_asr,
    make_asr_filename,
    next_asr_number,
    parse_asr,
    parse_asr_metadata,
    validate_priority,
    validate_status,
)

# ---------------------------------------------------------------------------
# generate_asr + parse_asr round-trip
# ---------------------------------------------------------------------------


def test_generate_parse_round_trip_with_notes() -> None:
    asr = ASR(
        number=7,
        priority=1,
        status="Active",
        created="2026-01-01",
        updated="2026-04-09",
        requirement="System must start within 30 seconds.",
        notes="See ADR-003.",
    )

    markdown = generate_asr(asr)
    parsed = parse_asr(markdown)

    assert parsed.number == asr.number
    assert parsed.priority == asr.priority
    assert parsed.status == asr.status
    assert parsed.created == asr.created
    assert parsed.updated == asr.updated
    assert parsed.requirement == asr.requirement
    assert parsed.notes == asr.notes


def test_generate_parse_round_trip_without_notes() -> None:
    asr = ASR(
        number=8,
        priority=0,
        status="Archived",
        created="2026-02-02",
        updated="2026-04-09",
        requirement="System must preserve successful startup state.",
        notes="",
    )

    markdown = generate_asr(asr)

    assert "## Notes" not in markdown

    parsed = parse_asr(markdown)

    assert parsed.notes == ""


# ---------------------------------------------------------------------------
# parse_asr error cases
# ---------------------------------------------------------------------------


def test_parse_asr_missing_requirement_raises() -> None:
    markdown = textwrap.dedent(
        """\
        # ASR-0001

        **Priority:** 3
        **Status:** Active
        **Created:** 2026-01-01
        **Updated:** 2026-04-09
        """
    )

    with pytest.raises(ValueError):
        parse_asr(markdown)


def test_parse_asr_number_not_found_raises() -> None:
    markdown = textwrap.dedent(
        """\
        **Priority:** 3
        **Status:** Active
        **Created:** 2026-01-01
        **Updated:** 2026-04-09

        ## Requirement

        Requirement text.
        """
    )

    with pytest.raises(ValueError):
        parse_asr(markdown)


def test_parse_asr_old_format_raises() -> None:
    markdown = textwrap.dedent(
        """\
        # ASR-001: some slug title

        **Priority:** 3
        **Status:** Active
        **Created:** 2026-01-01
        **Updated:** 2026-04-09

        ## Requirement

        Requirement text.
        """
    )

    with pytest.raises(ValueError):
        parse_asr(markdown)


# ---------------------------------------------------------------------------
# validate_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("Active", None),
        ("Archived", None),
        ("Superseded by ASR-0003", None),
        ("Critical", "error"),
        ("superseded by ASR-0003", "error"),
    ],
)
def test_validate_status(status: str, expected: str | None) -> None:
    result = validate_status(status)

    if expected is None:
        assert result is None
    else:
        assert result is not None


# ---------------------------------------------------------------------------
# validate_priority
# ---------------------------------------------------------------------------


def test_validate_priority_zero() -> None:
    assert validate_priority(0) is None


def test_validate_priority_positive_int() -> None:
    assert validate_priority(5) is None


def test_validate_priority_negative_int() -> None:
    assert validate_priority(-1) is not None


def test_validate_priority_bool() -> None:
    assert validate_priority(True) is not None


def test_validate_priority_float() -> None:
    assert validate_priority(cast(Any, 3.5)) is not None


# ---------------------------------------------------------------------------
# make_asr_filename
# ---------------------------------------------------------------------------


def test_make_asr_filename_single_digit() -> None:
    assert make_asr_filename(1) == "ASR-0001.md"


def test_make_asr_filename_two_digits() -> None:
    assert make_asr_filename(16) == "ASR-0016.md"


# ---------------------------------------------------------------------------
# next_asr_number
# ---------------------------------------------------------------------------


def test_next_asr_number_empty_dir(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "reqs"
    requirements_dir.mkdir()

    assert next_asr_number(requirements_dir) == 1


def test_next_asr_number_nonexistent_dir(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "reqs"

    assert next_asr_number(requirements_dir) == 1


def test_next_asr_number_old_slug_files_only(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "reqs"
    requirements_dir.mkdir()
    (requirements_dir / "ASR-001-slug-title.md").write_text("x")
    (requirements_dir / "ASR-005-another.md").write_text("x")

    assert next_asr_number(requirements_dir) == 1


def test_next_asr_number_new_style_files(tmp_path: Path) -> None:
    requirements_dir = tmp_path / "reqs"
    requirements_dir.mkdir()
    (requirements_dir / "ASR-0001.md").write_text("x")
    (requirements_dir / "ASR-0005.md").write_text("x")

    assert next_asr_number(requirements_dir) == 6


# ---------------------------------------------------------------------------
# parse_asr_metadata
# ---------------------------------------------------------------------------


def test_parse_asr_metadata_priority_is_int() -> None:
    markdown = textwrap.dedent(
        """\
        # ASR-0001

        **Priority:** 3
        **Status:** Active
        **Created:** 2026-01-01
        **Updated:** 2026-04-09

        ## Requirement

        Requirement text.
        """
    )

    result = parse_asr_metadata(markdown)

    assert result["priority"] == 3
    assert isinstance(result["priority"], int) is True
    assert isinstance(result["priority"], bool) is False
