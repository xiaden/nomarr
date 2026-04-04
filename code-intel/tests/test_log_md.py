"""Tests for log_md helper — Agent log markdown parsing, generation, and appending.

Covers:
- validate_category: each valid category, invalid
- validate_agent_name: valid names, empty, single char, uppercase, leading/trailing hyphens
- generate_log_header + append_entry + parse_log round-trip
- next_entry_id: empty log→L1, existing→next
- parse_log: multiple entries, missing header, metadata-to-body transition
"""

from pathlib import Path

import pytest

from mcp_code_intel.helpers.log_md import (
    CATEGORIES,
    AgentLog,
    LogEntry,
    append_entry,
    generate_log_header,
    next_entry_id,
    parse_log,
    validate_agent_name,
    validate_category,
)

# ---------------------------------------------------------------------------
# validate_category
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", sorted(CATEGORIES))
def test_validate_category_valid(category: str) -> None:
    assert validate_category(category) is None


def test_validate_category_invalid() -> None:
    err = validate_category("invalid-cat")
    assert err is not None


def test_validate_category_empty() -> None:
    err = validate_category("")
    assert err is not None


def test_validate_category_uppercase() -> None:
    err = validate_category("Research")
    assert err is not None


# ---------------------------------------------------------------------------
# validate_agent_name
# ---------------------------------------------------------------------------


def test_validate_agent_name_valid() -> None:
    assert validate_agent_name("rnd-ddauthor") is None


def test_validate_agent_name_valid_short() -> None:
    assert validate_agent_name("ab") is None


def test_validate_agent_name_empty() -> None:
    err = validate_agent_name("")
    assert err is not None
    assert "empty" in err.lower()


def test_validate_agent_name_single_char() -> None:
    err = validate_agent_name("a")
    assert err is not None


def test_validate_agent_name_uppercase() -> None:
    err = validate_agent_name("RND-Author")
    assert err is not None


def test_validate_agent_name_leading_hyphen() -> None:
    err = validate_agent_name("-my-agent")
    assert err is not None


def test_validate_agent_name_trailing_hyphen() -> None:
    err = validate_agent_name("my-agent-")
    assert err is not None


def test_validate_agent_name_with_numbers() -> None:
    assert validate_agent_name("agent42") is None


# ---------------------------------------------------------------------------
# next_entry_id
# ---------------------------------------------------------------------------


def test_next_entry_id_empty_log() -> None:
    log = AgentLog(agent="test")
    assert next_entry_id(log) == "L1"


def test_next_entry_id_existing_entries() -> None:
    log = AgentLog(
        agent="test",
        entries=[
            LogEntry(id="L1", title="First", date="2026-01-01", category="research"),
            LogEntry(id="L3", title="Third", date="2026-01-03", category="decision"),
        ],
    )
    assert next_entry_id(log) == "L4"


def test_next_entry_id_single_entry() -> None:
    log = AgentLog(
        agent="test",
        entries=[LogEntry(id="L1", title="Only", date="2026-01-01", category="research")],
    )
    assert next_entry_id(log) == "L2"


# ---------------------------------------------------------------------------
# generate_log_header
# ---------------------------------------------------------------------------


def test_generate_log_header_format() -> None:
    header = generate_log_header("test-agent")
    assert "# Agent Log: test-agent" in header
    assert "---" in header


# ---------------------------------------------------------------------------
# parse_log — basic
# ---------------------------------------------------------------------------


def test_parse_log_header_only() -> None:
    md = "# Agent Log: test-agent\n\n---\n"
    log = parse_log(md)
    assert log.agent == "test-agent"
    assert log.entries == []


def test_parse_log_single_entry() -> None:
    md = (
        "# Agent Log: test-agent\n\n---\n\n"
        "## [L1] First entry\n"
        "**Date:** 2026-01-01T10:00:00  \n"
        "**Category:** research  \n"
        "**Tags:** persistence, db  \n"
        "\n"
        "Body text here.\n"
        "\n---\n"
    )
    log = parse_log(md)
    assert log.agent == "test-agent"
    assert len(log.entries) == 1
    e = log.entries[0]
    assert e.id == "L1"
    assert e.title == "First entry"
    assert e.category == "research"
    assert e.tags == ["persistence", "db"]
    assert "Body text here." in e.body


def test_parse_log_multiple_entries() -> None:
    md = (
        "# Agent Log: test-agent\n\n---\n\n"
        "## [L1] First\n"
        "**Date:** 2026-01-01T10:00:00  \n"
        "**Category:** research  \n\n"
        "First body.\n\n---\n\n"
        "## [L2] Second\n"
        "**Date:** 2026-01-02T10:00:00  \n"
        "**Category:** decision  \n\n"
        "Second body.\n\n---\n"
    )
    log = parse_log(md)
    assert len(log.entries) == 2
    assert log.entries[0].id == "L1"
    assert log.entries[1].id == "L2"
    assert log.entries[0].category == "research"
    assert log.entries[1].category == "decision"


def test_parse_log_missing_header_raises() -> None:
    md = "## [L1] No header\n**Date:** 2026-01-01\n**Category:** research\n"
    with pytest.raises(ValueError, match="header"):
        parse_log(md)


def test_parse_log_metadata_to_body_transition() -> None:
    """Blank line between metadata and body transitions parser correctly."""
    md = (
        "# Agent Log: test-agent\n\n---\n\n"
        "## [L1] With body\n"
        "**Date:** 2026-01-01T10:00:00  \n"
        "**Category:** research  \n"
        "\n"
        "This is the body.\n"
        "It has multiple lines.\n"
        "\n---\n"
    )
    log = parse_log(md)
    assert "This is the body." in log.entries[0].body
    assert "It has multiple lines." in log.entries[0].body


def test_parse_log_entry_without_body() -> None:
    md = (
        "# Agent Log: test-agent\n\n---\n\n"
        "## [L1] No body\n"
        "**Date:** 2026-01-01T10:00:00  \n"
        "**Category:** research  \n"
        "\n---\n"
    )
    log = parse_log(md)
    assert log.entries[0].body == ""


def test_parse_log_entry_without_tags() -> None:
    md = (
        "# Agent Log: test-agent\n\n---\n\n"
        "## [L1] No tags\n"
        "**Date:** 2026-01-01T10:00:00  \n"
        "**Category:** research  \n"
        "\n---\n"
    )
    log = parse_log(md)
    assert log.entries[0].tags == []


# ---------------------------------------------------------------------------
# generate_log_header + append_entry + parse_log round-trip (with tmp_path)
# ---------------------------------------------------------------------------


def test_round_trip_create_append_parse(tmp_path: Path) -> None:
    log_file = tmp_path / "test-agent.log.md"
    log_file.write_text(generate_log_header("test-agent"), encoding="utf-8")

    entry1 = LogEntry(
        id="L1",
        title="Discovery entry",
        date="2026-01-01T10:00:00",
        category="discovery",
        tags=["tag1", "tag2"],
        body="Found something important.",
    )
    append_entry(log_file, entry1)

    entry2 = LogEntry(
        id="L2",
        title="Decision entry",
        date="2026-01-02T14:00:00",
        category="decision",
        body="Decided to proceed.",
    )
    append_entry(log_file, entry2)

    md = log_file.read_text(encoding="utf-8")
    parsed = parse_log(md)

    assert parsed.agent == "test-agent"
    assert len(parsed.entries) == 2
    assert parsed.entries[0].id == "L1"
    assert parsed.entries[0].title == "Discovery entry"
    assert parsed.entries[0].tags == ["tag1", "tag2"]
    assert "Found something important." in parsed.entries[0].body
    assert parsed.entries[1].id == "L2"
    assert parsed.entries[1].title == "Decision entry"
    assert parsed.entries[1].category == "decision"


def test_round_trip_entry_no_tags_no_body(tmp_path: Path) -> None:
    log_file = tmp_path / "minimal.log.md"
    log_file.write_text(generate_log_header("minimal"), encoding="utf-8")

    entry = LogEntry(
        id="L1",
        title="Simple",
        date="2026-01-01T10:00:00",
        category="observation",
    )
    append_entry(log_file, entry)

    parsed = parse_log(log_file.read_text(encoding="utf-8"))
    assert len(parsed.entries) == 1
    assert parsed.entries[0].body == ""
    assert parsed.entries[0].tags == []



# ---------------------------------------------------------------------------
# CRLF normalization
# ---------------------------------------------------------------------------


def test_parse_log_crlf_normalization() -> None:
    """CRLF line endings should be normalized to LF in all parsed fields."""
    md = (
        "# Agent Log: test-agent\r\n"
        "\r\n"
        "---\r\n"
        "\r\n"
        "## [L1] First entry\r\n"
        "**Date:** 2026-01-01T10:00:00  \r\n"
        "**Category:** research  \r\n"
        "**Tags:** persistence, db  \r\n"
        "\r\n"
        "Body text here.\r\n"
        "Second line of body.\r\n"
        "\r\n"
        "---\r\n"
        "\r\n"
        "## [L2] Second entry\r\n"
        "**Date:** 2026-01-02T14:00:00  \r\n"
        "**Category:** decision  \r\n"
        "\r\n"
        "Decision body.\r\n"
        "\r\n"
        "---\r\n"
    )
    log = parse_log(md)

    # Agent name
    assert "\r" not in log.agent

    # All entries
    for entry in log.entries:
        assert "\r" not in entry.id, f"Entry {entry.id!r} id contains \\r"
        assert "\r" not in entry.title, f"Entry {entry.id!r} title contains \\r"
        assert "\r" not in entry.date, f"Entry {entry.id!r} date contains \\r"
        assert "\r" not in entry.category, f"Entry {entry.id!r} category contains \\r"
        assert "\r" not in entry.body, f"Entry {entry.id!r} body contains \\r"
        for tag in entry.tags:
            assert "\r" not in tag, f"Entry {entry.id!r} tag {tag!r} contains \\r"

    # Verify content was actually parsed (not just empty)
    assert len(log.entries) == 2
    assert log.entries[0].tags == ["persistence", "db"]
    assert "Body text here." in log.entries[0].body
