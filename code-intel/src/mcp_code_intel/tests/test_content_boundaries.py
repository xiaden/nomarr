"""Tests for content_boundaries helper functions."""

from __future__ import annotations

from mcp_code_intel.helpers.content_boundaries import (
    find_anchor_line,
    find_content_boundaries,
)

# ---------------------------------------------------------------------------
# find_content_boundaries
# ---------------------------------------------------------------------------


class TestFindContentBoundaries:
    """Tests for find_content_boundaries."""

    SAMPLE_LINES = [
        "import os",             # 1
        "",                      # 2
        "class Foo:",            # 3
        "    def bar(self):",    # 4
        "        x = 1",         # 5
        "        y = 2",         # 6
        "        return x + y",  # 7
        "",                      # 8
        "    def baz(self):",    # 9
        "        pass",          # 10
        "",                      # 11
        "class Qux:",            # 12
        "    def bar(self):",    # 13
        "        return 42",     # 14
    ]

    def test_simple_single_line_boundaries(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="def bar(self):",
            end_boundary="return x + y",
            expected_line_count=4,
        )
        assert result == (4, 7)

    def test_multiline_start_boundary(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="class Foo:\n    def bar(self):",
            end_boundary="return x + y",
            expected_line_count=5,
        )
        assert result == (3, 7)

    def test_multiline_end_boundary(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="def baz(self):",
            end_boundary="pass",
            expected_line_count=2,
        )
        assert result == (9, 10)

    def test_start_boundary_not_found(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="def nonexistent():",
            end_boundary="pass",
            expected_line_count=2,
        )
        assert isinstance(result, str)
        assert "Start boundary not found" in result

    def test_end_boundary_not_found(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="class Foo:",
            end_boundary="totally_missing",
            expected_line_count=5,
        )
        assert isinstance(result, str)
        assert "End boundary not found" in result

    def test_wrong_line_count(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="def bar(self):",
            end_boundary="return x + y",
            expected_line_count=10,  # Wrong
        )
        assert isinstance(result, str)
        assert "expected_line_count=10" in result

    def test_ambiguous_boundaries(self) -> None:
        """def bar(self): appears at line 4 and 13.
        With return at line 7 (count 4) and 14 (count 2),
        only one matches count 4, so it should succeed."""
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="def bar(self):",
            end_boundary="return",
            expected_line_count=4,
        )
        assert result == (4, 7)

    def test_truly_ambiguous_same_count(self) -> None:
        """Two ranges with identical line counts."""
        lines = [
            "# start",
            "body",
            "# end",
            "# start",
            "body",
            "# end",
        ]
        result = find_content_boundaries(
            lines,
            start_boundary="# start",
            end_boundary="# end",
            expected_line_count=3,
        )
        assert isinstance(result, str)
        assert "Ambiguous" in result
        assert "2 matching ranges" in result

    def test_single_line_range(self) -> None:
        """Start and end boundary are the same line."""
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="import os",
            end_boundary="import os",
            expected_line_count=1,
        )
        assert result == (1, 1)

    def test_single_line_range_with_trailing_newline(self) -> None:
        """Start/end boundaries copied with newline still match one line."""
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="import os\n",
            end_boundary="import os\n",
            expected_line_count=1,
        )
        assert result == (1, 1)

    def test_whitespace_tolerance(self) -> None:
        """Boundaries with different indentation should still match."""
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="  def bar(self):  ",  # extra whitespace
            end_boundary="  return x + y  ",
            expected_line_count=4,
        )
        assert result == (4, 7)

    def test_empty_start_boundary(self) -> None:
        result = find_content_boundaries(
            self.SAMPLE_LINES,
            start_boundary="",
            end_boundary="pass",
            expected_line_count=1,
        )
        assert isinstance(result, str)
        assert "Start boundary not found" in result


# ---------------------------------------------------------------------------
# find_anchor_line
# ---------------------------------------------------------------------------


class TestFindAnchorLine:
    """Tests for find_anchor_line."""

    SAMPLE_LINES = [
        "import os",
        "",
        "class Foo:",
        "    def bar(self):",
        "        pass",
        "",
        "class Bar:",
        "    def baz(self):",
        "        pass",
    ]

    def test_unique_match(self) -> None:
        result = find_anchor_line(self.SAMPLE_LINES, "class Foo:")
        assert result == 3

    def test_substring_match(self) -> None:
        """Anchor matches as substring."""
        result = find_anchor_line(self.SAMPLE_LINES, "import")
        assert result == 1

    def test_not_found(self) -> None:
        result = find_anchor_line(self.SAMPLE_LINES, "nonexistent")
        assert isinstance(result, str)
        assert "Anchor not found" in result

    def test_ambiguous(self) -> None:
        """'pass' appears twice."""
        result = find_anchor_line(self.SAMPLE_LINES, "pass")
        assert isinstance(result, str)
        assert "Ambiguous anchor" in result
        assert "2 matches" in result

    def test_whitespace_tolerance(self) -> None:
        result = find_anchor_line(self.SAMPLE_LINES, "  class Foo:  ")
        assert result == 3

    def test_empty_anchor(self) -> None:
        result = find_anchor_line(self.SAMPLE_LINES, "")
        assert isinstance(result, str)
        assert "empty" in result

    def test_whitespace_only_anchor(self) -> None:
        result = find_anchor_line(self.SAMPLE_LINES, "   ")
        assert isinstance(result, str)
        assert "empty" in result
