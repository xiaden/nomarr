"""Tests for adr_md helper — ADR markdown parsing and generation.

Covers:
- validate_status: each valid status, invalid
- validate_source_log: valid, invalid formats, empty returns None
- generate_adr + parse_adr round-trip
- parse_adr_metadata: stops at first ##, correct keys
- next_adr_number: empty dir→1, existing→next, non-existent dir→1
- make_adr_filename, _slugify, today_iso
- Section ordering: standard first, extras, References last
"""

import textwrap
from datetime import date
from pathlib import Path

import pytest

from mcp_code_intel.helpers.adr_md import (
    ADR,
    ADR_STATUSES,
    DECISIONS_DIR,
    _slugify,
    generate_adr,
    make_adr_filename,
    next_adr_number,
    parse_adr,
    parse_adr_metadata,
    today_iso,
    validate_source_log,
    validate_status,
)

# ---------------------------------------------------------------------------
# validate_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(ADR_STATUSES))
def test_validate_status_valid(status: str) -> None:
    assert validate_status(status) is None


def test_validate_status_invalid() -> None:
    err = validate_status("Rejected")
    assert err is not None


def test_validate_status_empty() -> None:
    err = validate_status("")
    assert err is not None


def test_validate_status_lowercase() -> None:
    err = validate_status("proposed")
    assert err is not None


# ---------------------------------------------------------------------------
# validate_source_log
# ---------------------------------------------------------------------------


def test_validate_source_log_valid() -> None:
    assert validate_source_log("rnd-ddauthor#L42") is None


def test_validate_source_log_valid_long() -> None:
    assert validate_source_log("my-agent-name#L1") is None


def test_validate_source_log_empty_returns_none() -> None:
    assert validate_source_log("") is None


def test_validate_source_log_missing_hash() -> None:
    err = validate_source_log("rnd-ddauthorL42")
    assert err is not None


def test_validate_source_log_missing_line_number() -> None:
    err = validate_source_log("rnd-ddauthor#L")
    assert err is not None


def test_validate_source_log_no_line_prefix() -> None:
    err = validate_source_log("rnd-ddauthor#42")
    assert err is not None


def test_validate_source_log_uppercase_agent() -> None:
    err = validate_source_log("RND-Author#L1")
    assert err is not None


def test_validate_source_log_single_char_agent() -> None:
    err = validate_source_log("a#L1")
    assert err is not None  # Needs at least 2 chars


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


def test_slugify_simple() -> None:
    assert _slugify("Use Edges for Relations") == "use-edges-for-relations"


def test_slugify_special_chars() -> None:
    assert _slugify("Use ArangoDB — Graph DB!") == "use-arangodb-graph-db"


def test_slugify_collapses_hyphens() -> None:
    assert _slugify("lots---of---hyphens") == "lots-of-hyphens"


def test_slugify_strips_leading_trailing() -> None:
    assert _slugify("---hello---") == "hello"


# ---------------------------------------------------------------------------
# make_adr_filename
# ---------------------------------------------------------------------------


def test_make_adr_filename() -> None:
    assert make_adr_filename(3, "Use Edges") == "ADR-003-use-edges.md"


def test_make_adr_filename_large_number() -> None:
    assert make_adr_filename(123, "Big") == "ADR-123-big.md"


# ---------------------------------------------------------------------------
# today_iso
# ---------------------------------------------------------------------------


def test_today_iso() -> None:
    assert today_iso() == date.today().isoformat()


# ---------------------------------------------------------------------------
# next_adr_number
# ---------------------------------------------------------------------------


def test_next_adr_number_empty_dir(tmp_path: Path) -> None:
    decisions = tmp_path / DECISIONS_DIR
    decisions.mkdir(parents=True)
    assert next_adr_number(tmp_path) == 1


def test_next_adr_number_nonexistent_dir(tmp_path: Path) -> None:
    assert next_adr_number(tmp_path) == 1


def test_next_adr_number_existing_files(tmp_path: Path) -> None:
    decisions = tmp_path / DECISIONS_DIR
    decisions.mkdir(parents=True)
    (decisions / "ADR-001-first.md").write_text("x")
    (decisions / "ADR-005-fifth.md").write_text("x")
    assert next_adr_number(tmp_path) == 6


def test_next_adr_number_ignores_non_adr_files(tmp_path: Path) -> None:
    decisions = tmp_path / DECISIONS_DIR
    decisions.mkdir(parents=True)
    (decisions / "ADR-002-something.md").write_text("x")
    (decisions / "README.md").write_text("x")
    assert next_adr_number(tmp_path) == 3


# ---------------------------------------------------------------------------
# generate_adr + parse_adr round-trip
# ---------------------------------------------------------------------------


def test_generate_parse_round_trip_minimal() -> None:
    adr = ADR(
        number=1,
        title="Use Edges",
        status="Proposed",
        date="2026-01-15",
        tags=["persistence"],
        sections={"Context": "We need edges.", "Decision": "Use them.", "Consequences": "Faster."},
    )
    md = generate_adr(adr)
    parsed = parse_adr(md)

    assert parsed.number == adr.number
    assert parsed.title == adr.title
    assert parsed.status == adr.status
    assert parsed.date == adr.date
    assert parsed.tags == adr.tags
    assert parsed.source_log is None
    assert parsed.sections["Context"] == "We need edges."
    assert parsed.sections["Decision"] == "Use them."
    assert parsed.sections["Consequences"] == "Faster."


def test_generate_parse_round_trip_all_fields() -> None:
    adr = ADR(
        number=42,
        title="Adopt ONNX",
        status="Accepted",
        date="2026-02-01",
        tags=["ml", "inference"],
        source_log="rnd-ml#L15",
        sections={
            "Context": "Context here.",
            "Decision": "Decision here.",
            "Consequences": "Consequences here.",
            "Migration": "Migration plan.",
            "References": "- Link A\n- Link B",
        },
    )
    md = generate_adr(adr)
    parsed = parse_adr(md)

    assert parsed.number == 42
    assert parsed.source_log == "rnd-ml#L15"
    assert parsed.tags == ["ml", "inference"]
    assert "Migration" in parsed.sections
    assert "References" in parsed.sections


def test_generate_adr_section_ordering() -> None:
    """Standard sections first, extras middle, References last."""
    adr = ADR(
        number=1,
        title="Order Test",
        status="Proposed",
        date="2026-01-01",
        tags=["test"],
        sections={
            "References": "Link.",
            "Custom Extra": "Extra content.",
            "Context": "Context.",
            "Decision": "Decision.",
            "Consequences": "Consequences.",
        },
    )
    md = generate_adr(adr)
    # Find section positions
    ctx_pos = md.index("## Context")
    dec_pos = md.index("## Decision")
    con_pos = md.index("## Consequences")
    ext_pos = md.index("## Custom Extra")
    ref_pos = md.index("## References")

    assert ctx_pos < dec_pos < con_pos < ext_pos < ref_pos


# ---------------------------------------------------------------------------
# parse_adr — error cases
# ---------------------------------------------------------------------------


def test_parse_adr_missing_title_raises() -> None:
    md = textwrap.dedent("""\
        **Status:** Proposed
        **Date:** 2026-01-01
        **Tags:** test

        ## Context
        Content.
    """)
    with pytest.raises(ValueError, match="title"):
        parse_adr(md)


def test_parse_adr_sections_parsed() -> None:
    md = textwrap.dedent("""\
        # ADR-001: Test

        **Status:** Proposed
        **Date:** 2026-01-01
        **Tags:** test

        ## Context

        Context text.

        ## Decision

        Decision text.
    """)
    adr = parse_adr(md)
    assert adr.sections["Context"] == "Context text."
    assert adr.sections["Decision"] == "Decision text."


# ---------------------------------------------------------------------------
# parse_adr_metadata
# ---------------------------------------------------------------------------


def test_parse_adr_metadata_basic() -> None:
    md = textwrap.dedent("""\
        # ADR-007: Important Choice

        **Status:** Accepted
        **Date:** 2026-03-15
        **Tags:** api, http
        **Source Log:** rnd-api#L5

        ## Context

        Context body that should not be parsed.
    """)
    meta = parse_adr_metadata(md)
    assert meta["number"] == 7
    assert meta["title"] == "Important Choice"
    assert meta["status"] == "Accepted"
    assert meta["date"] == "2026-03-15"
    assert meta["tags"] == ["api", "http"]
    assert meta["source_log"] == "rnd-api#L5"


def test_parse_adr_metadata_stops_at_section() -> None:
    """Metadata parser stops at first ## — does not parse sections."""
    md = textwrap.dedent("""\
        # ADR-001: Test

        **Status:** Proposed
        **Date:** 2026-01-01
        **Tags:** test

        ## Context

        **Tags:** should-not-be-parsed
    """)
    meta = parse_adr_metadata(md)
    assert meta["tags"] == ["test"]


def test_parse_adr_metadata_keys() -> None:
    md = "# ADR-001: X\n**Status:** Proposed\n**Date:** 2026-01-01\n**Tags:** a\n"
    meta = parse_adr_metadata(md)
    expected_keys = {"number", "title", "status", "date", "tags", "source_log"}
    assert set(meta.keys()) == expected_keys



# ---------------------------------------------------------------------------
# CRLF normalization
# ---------------------------------------------------------------------------


def test_parse_adr_crlf_normalization() -> None:
    """CRLF line endings should be normalized to LF in all parsed fields."""
    md = (
        "# ADR-042: Adopt ONNX for Inference\r\n"
        "\r\n"
        "**Status:** Accepted\r\n"
        "**Date:** 2026-02-01\r\n"
        "**Tags:** ml, inference\r\n"
        "**Source Log:** rnd-ml#L15\r\n"
        "\r\n"
        "## Context\r\n"
        "\r\n"
        "We need fast inference.\r\n"
        "Multiple lines of context.\r\n"
        "\r\n"
        "## Decision\r\n"
        "\r\n"
        "Use ONNX runtime.\r\n"
        "\r\n"
        "## Consequences\r\n"
        "\r\n"
        "Faster inference.\r\n"
        "\r\n"
        "## References\r\n"
        "\r\n"
        "- Link A\r\n"
        "- Link B\r\n"
    )
    adr = parse_adr(md)

    # Scalar fields
    assert "\r" not in adr.title
    assert "\r" not in adr.status
    assert "\r" not in adr.date
    assert adr.source_log is not None
    assert "\r" not in adr.source_log

    # List fields
    for tag in adr.tags:
        assert "\r" not in tag

    # Section values
    for name, body in adr.sections.items():
        assert "\r" not in name, f"Section name {name!r} contains \\r"
        assert "\r" not in body, f"Section {name!r} body contains \\r"
