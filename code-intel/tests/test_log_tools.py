"""Tests for log tools.

Covers:
- log_write: first write creates file, subsequent appends, invalid
    agent/category/title, tags, round-trip
- log_read: newest-first, filter by category/tag/title_query, combined, limit, not found
"""

from pathlib import Path

from mcp_code_intel.helpers.log_md import LOGS_DIR, parse_log
from mcp_code_intel.tools.log_read import log_read
from mcp_code_intel.tools.log_write import log_write

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_entry(tmp_path: Path, agent: str = "test-agent", **kwargs) -> dict:
    defaults = dict(
        agent=agent,
        title="Test entry",
        category="research",
        workspace_root=tmp_path,
    )
    defaults.update(kwargs)
    return log_write(**defaults)


# ---------------------------------------------------------------------------
# log_write
# ---------------------------------------------------------------------------


def test_log_write_creates_file(tmp_path: Path) -> None:
    result = _write_entry(tmp_path)
    assert "path" in result
    assert result["entry_id"] == "L1"
    log_file = tmp_path / LOGS_DIR / "test-agent.log.md"
    assert log_file.exists()


def test_log_write_subsequent_appends(tmp_path: Path) -> None:
    r1 = _write_entry(tmp_path, title="First")
    r2 = _write_entry(tmp_path, title="Second")
    assert r1["entry_id"] == "L1"
    assert r2["entry_id"] == "L2"


def test_log_write_invalid_agent(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, agent="Bad Agent!")
    assert result["error"] == "invalid_agent"


def test_log_write_invalid_category(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, category="invalid-cat")
    assert result["error"] == "invalid_category"


def test_log_write_empty_title(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, title="")
    assert result["error"] == "invalid_title"


def test_log_write_whitespace_title(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, title="   ")
    assert result["error"] == "invalid_title"


def test_log_write_with_tags(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, tags=["tag1", "tag2"])
    assert "path" in result
    md = (tmp_path / LOGS_DIR / "test-agent.log.md").read_text(encoding="utf-8")
    parsed = parse_log(md)
    assert parsed.entries[0].tags == ["tag1", "tag2"]


def test_log_write_with_body(tmp_path: Path) -> None:
    result = _write_entry(tmp_path, body="Detailed body text.")
    assert "path" in result
    md = (tmp_path / LOGS_DIR / "test-agent.log.md").read_text(encoding="utf-8")
    parsed = parse_log(md)
    assert "Detailed body text." in parsed.entries[0].body


def test_log_write_round_trip(tmp_path: Path) -> None:
    _write_entry(
        tmp_path,
        title="Research entry",
        category="research",
        tags=["db"],
        body="Found something.",
    )
    _write_entry(tmp_path, title="Decision entry", category="decision", body="Decided.")
    md = (tmp_path / LOGS_DIR / "test-agent.log.md").read_text(encoding="utf-8")
    parsed = parse_log(md)
    assert len(parsed.entries) == 2
    assert parsed.entries[0].title == "Research entry"
    assert parsed.entries[1].title == "Decision entry"


# ---------------------------------------------------------------------------
# log_read
# ---------------------------------------------------------------------------


def test_log_read_newest_first(tmp_path: Path) -> None:
    _write_entry(tmp_path, title="First")
    _write_entry(tmp_path, title="Second")
    result = log_read(agent="test-agent", workspace_root=tmp_path)
    assert result["entries"][0]["title"] == "Second"
    assert result["entries"][1]["title"] == "First"


def test_log_read_filter_by_category(tmp_path: Path) -> None:
    _write_entry(tmp_path, title="Research", category="research")
    _write_entry(tmp_path, title="Decision", category="decision")
    result = log_read(agent="test-agent", category="decision", workspace_root=tmp_path)
    assert result["total"] == 1
    assert result["entries"][0]["title"] == "Decision"


def test_log_read_filter_by_tag(tmp_path: Path) -> None:
    _write_entry(tmp_path, title="Tagged", tags=["db", "ml"])
    _write_entry(tmp_path, title="Untagged")
    result = log_read(agent="test-agent", tag="db", workspace_root=tmp_path)
    assert result["total"] == 1
    assert result["entries"][0]["title"] == "Tagged"


def test_log_read_filter_by_title_query(tmp_path: Path) -> None:
    _write_entry(tmp_path, title="Important discovery")
    _write_entry(tmp_path, title="Routine check")
    result = log_read(agent="test-agent", title_query="discovery", workspace_root=tmp_path)
    assert result["total"] == 1


def test_log_read_combined_filters(tmp_path: Path) -> None:
    _write_entry(tmp_path, title="DB Research", category="research", tags=["db"])
    _write_entry(tmp_path, title="ML Research", category="research", tags=["ml"])
    _write_entry(tmp_path, title="DB Decision", category="decision", tags=["db"])
    result = log_read(agent="test-agent", category="research", tag="db", workspace_root=tmp_path)
    assert result["total"] == 1
    assert result["entries"][0]["title"] == "DB Research"


def test_log_read_limit(tmp_path: Path) -> None:
    for i in range(5):
        _write_entry(tmp_path, title=f"Entry {i}")
    result = log_read(agent="test-agent", limit=2, workspace_root=tmp_path)
    assert len(result["entries"]) == 2
    assert result["total"] == 5


def test_log_read_not_found(tmp_path: Path) -> None:
    result = log_read(agent="nonexistent", workspace_root=tmp_path)
    assert result["error"] == "log_not_found"


def test_log_read_invalid_agent(tmp_path: Path) -> None:
    result = log_read(agent="Bad!", workspace_root=tmp_path)
    assert result["error"] == "invalid_agent"
