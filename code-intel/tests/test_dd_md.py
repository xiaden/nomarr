"""Tests for dd_md helper — Design Document markdown parsing and generation.

Covers:
- validate_slug: valid slugs, empty, single char, leading/trailing hyphens, uppercase, special chars
- validate_status: each valid status, invalid, empty
- generate_dd + parse_dd round-trip: DesignDocument → markdown → parse → compare
- parse_dd: missing title, sections, related docs, metadata
- make_dd_filename, today_iso
"""

import textwrap
from datetime import date

import pytest

from mcp_code_intel.helpers.dd_md import (
    DD_STATUSES,
    DesignDocument,
    generate_dd,
    make_dd_filename,
    parse_dd,
    today_iso,
    validate_slug,
    validate_status,
)

# ---------------------------------------------------------------------------
# validate_slug
# ---------------------------------------------------------------------------


def test_validate_slug_valid() -> None:
    assert validate_slug("my-feature") is None


def test_validate_slug_valid_numeric() -> None:
    assert validate_slug("v2-cache") is None


def test_validate_slug_valid_no_hyphens() -> None:
    assert validate_slug("ab") is None


def test_validate_slug_empty() -> None:
    err = validate_slug("")
    assert err is not None
    assert "empty" in err.lower()


def test_validate_slug_single_char() -> None:
    err = validate_slug("a")
    assert err is not None  # Needs at least 2 chars


def test_validate_slug_leading_hyphen() -> None:
    err = validate_slug("-my-slug")
    assert err is not None


def test_validate_slug_trailing_hyphen() -> None:
    err = validate_slug("my-slug-")
    assert err is not None


def test_validate_slug_uppercase() -> None:
    err = validate_slug("My-Feature")
    assert err is not None


def test_validate_slug_special_chars() -> None:
    err = validate_slug("my_feature!")
    assert err is not None


def test_validate_slug_spaces() -> None:
    err = validate_slug("my feature")
    assert err is not None


# ---------------------------------------------------------------------------
# validate_status
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", sorted(DD_STATUSES))
def test_validate_status_valid(status: str) -> None:
    assert validate_status(status) is None


def test_validate_status_invalid() -> None:
    err = validate_status("Pending")
    assert err is not None


def test_validate_status_empty() -> None:
    err = validate_status("")
    assert err is not None


def test_validate_status_lowercase() -> None:
    err = validate_status("draft")
    assert err is not None  # Case-sensitive


# ---------------------------------------------------------------------------
# make_dd_filename
# ---------------------------------------------------------------------------


def test_make_dd_filename() -> None:
    assert make_dd_filename("my-feature") == "DD-my-feature.md"


def test_make_dd_filename_short_slug() -> None:
    assert make_dd_filename("ab") == "DD-ab.md"


# ---------------------------------------------------------------------------
# today_iso
# ---------------------------------------------------------------------------


def test_today_iso_format() -> None:
    result = today_iso()
    assert result == date.today().isoformat()


# ---------------------------------------------------------------------------
# generate_dd + parse_dd round-trip
# ---------------------------------------------------------------------------


def test_generate_parse_round_trip_minimal() -> None:
    doc = DesignDocument(
        title="Test Feature",
        status="Draft",
        author="test-agent",
        created="2026-01-15",
        sections={"Scope": "Test scope content."},
    )
    md = generate_dd(doc)
    parsed = parse_dd(md)

    assert parsed.title == doc.title
    assert parsed.status == doc.status
    assert parsed.author == doc.author
    assert parsed.created == doc.created
    assert parsed.sections["Scope"] == "Test scope content."


def test_generate_parse_round_trip_all_fields() -> None:
    doc = DesignDocument(
        title="Full Feature",
        status="Approved",
        author="rnd-author",
        created="2026-03-01",
        revised="2026-03-15",
        related_documents=[
            {
                "title": "ADR-001",
                "path": "artifacts/decisions/ADR-001.md",
                "description": "Initial decision",
            }
        ],
        sections={
            "Scope": "Broad scope.",
            "Problem Statement": "The problem.",
            "Architecture": "The architecture.",
        },
    )
    md = generate_dd(doc)
    parsed = parse_dd(md)

    assert parsed.title == doc.title
    assert parsed.status == doc.status
    assert parsed.author == doc.author
    assert parsed.created == doc.created
    assert parsed.revised == doc.revised
    assert len(parsed.related_documents) == 1
    assert parsed.related_documents[0]["title"] == "ADR-001"
    assert parsed.related_documents[0]["path"] == "artifacts/decisions/ADR-001.md"
    assert parsed.related_documents[0]["description"] == "Initial decision"
    assert parsed.sections["Scope"] == "Broad scope."
    assert parsed.sections["Problem Statement"] == "The problem."
    assert parsed.sections["Architecture"] == "The architecture."


def test_generate_parse_round_trip_multiple_related_docs() -> None:
    doc = DesignDocument(
        title="Multi Ref",
        status="Draft",
        author="test",
        created="2026-01-01",
        related_documents=[
            {"title": "Doc A", "path": "a.md", "description": "First"},
            {"title": "Doc B", "path": "b.md", "description": "Second"},
        ],
        sections={"Scope": "Content."},
    )
    md = generate_dd(doc)
    parsed = parse_dd(md)
    assert len(parsed.related_documents) == 2
    assert parsed.related_documents[1]["title"] == "Doc B"


def test_generate_parse_round_trip_empty_sections() -> None:
    doc = DesignDocument(
        title="No Sections",
        status="Draft",
        author="test",
        created="2026-01-01",
        sections={},
    )
    md = generate_dd(doc)
    parsed = parse_dd(md)
    assert parsed.title == "No Sections"
    assert parsed.sections == {}


# ---------------------------------------------------------------------------
# parse_dd — error cases
# ---------------------------------------------------------------------------


def test_parse_dd_missing_title_raises() -> None:
    md = textwrap.dedent("""\
        **Status:** Draft
        **Author:** test
        **Created:** 2026-01-01

        ---

        ## Scope
        Content.
    """)
    with pytest.raises(ValueError, match="title"):
        parse_dd(md)


def test_parse_dd_sections_parsed() -> None:
    md = textwrap.dedent("""\
        # My Design — Design Document

        **Status:** Draft
        **Author:** test
        **Created:** 2026-01-01

        ---

        ## Scope

        Scope content here.

        ---

        ## Problem Statement

        Problem content here.
    """)
    doc = parse_dd(md)
    assert "Scope" in doc.sections
    assert "Problem Statement" in doc.sections
    assert doc.sections["Scope"] == "Scope content here."
    assert doc.sections["Problem Statement"] == "Problem content here."


def test_parse_dd_metadata_extraction() -> None:
    md = textwrap.dedent("""\
        # Test — Design Document

        **Status:** Approved
        **Author:** rnd-test
        **Created:** 2026-02-20
        **Revised:** 2026-03-01

        ---

        ## Scope

        Content.
    """)
    doc = parse_dd(md)
    assert doc.status == "Approved"
    assert doc.author == "rnd-test"
    assert doc.created == "2026-02-20"
    assert doc.revised == "2026-03-01"


def test_parse_dd_no_revised() -> None:
    md = textwrap.dedent("""\
        # Test — Design Document

        **Status:** Draft
        **Author:** test
        **Created:** 2026-01-01

        ---

        ## Scope

        Content.
    """)
    doc = parse_dd(md)
    assert doc.revised == ""



# ---------------------------------------------------------------------------
# CRLF normalization
# ---------------------------------------------------------------------------


def test_parse_dd_crlf_normalization() -> None:
    """CRLF line endings should be normalized to LF in all parsed fields."""
    md = (
        "# Full Feature \u2014 Design Document\r\n"
        "\r\n"
        "**Status:** Approved\r\n"
        "**Author:** rnd-author\r\n"
        "**Created:** 2026-03-01\r\n"
        "**Revised:** 2026-03-15\r\n"
        "\r\n"
        "### Related Documents\r\n"
        "\r\n"
        "| Title | Path | Description |\r\n"
        "| --- | --- | --- |\r\n"
        "| ADR-001 | artifacts/decisions/ADR-001.md | Initial decision |\r\n"
        "\r\n"
        "---\r\n"
        "\r\n"
        "## Scope\r\n"
        "\r\n"
        "Broad scope content.\r\n"
        "Multiple lines.\r\n"
        "\r\n"
        "---\r\n"
        "\r\n"
        "## Problem Statement\r\n"
        "\r\n"
        "The problem description.\r\n"
    )
    doc = parse_dd(md)

    # Scalar fields
    assert "\r" not in doc.title
    assert "\r" not in doc.status
    assert "\r" not in doc.author
    assert "\r" not in doc.created
    assert "\r" not in doc.revised

    # Related documents
    for rd in doc.related_documents:
        for key, val in rd.items():
            assert "\r" not in key, f"Related doc key {key!r} contains \\r"
            assert "\r" not in val, f"Related doc value {val!r} contains \\r"

    # Section values
    for name, body in doc.sections.items():
        assert "\r" not in name, f"Section name {name!r} contains \\r"
        assert "\r" not in body, f"Section {name!r} body contains \\r"
