"""Tests for content_boundaries helper — tolerance behavior."""


from mcp_code_intel.helpers.content_boundaries import find_content_boundaries


def _make_lines(*texts: str) -> list[str]:
    """Build a flat list of file lines from multi-line strings."""
    result: list[str] = []
    for t in texts:
        result.extend(t.split("\n"))
    return result


# ---------------------------------------------------------------------------
# Exact match still preferred
# ---------------------------------------------------------------------------


def test_exact_match_preferred() -> None:
    """Exact line-count match returns 2-tuple without warning."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # Range lines 2-4 (bravo..delta) = 3 lines
    result = find_content_boundaries(lines, "bravo", "delta", 3)
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result == (2, 4)


# ---------------------------------------------------------------------------
# Tolerance ±1 — single candidate → 3-tuple with warning
# ---------------------------------------------------------------------------


def test_tolerance_plus_one_returns_3_tuple() -> None:
    """Off-by-+1 with single candidate returns 3-tuple warning."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # Actual range bravo..delta = 3 lines, but we claim 2 (off by -1)
    result = find_content_boundaries(lines, "bravo", "delta", 2)
    assert isinstance(result, tuple)
    assert len(result) == 3
    start, end, warning = result
    assert start == 2
    assert end == 4
    assert "off by" in warning.lower() or "+1" in warning


def test_tolerance_minus_one_returns_3_tuple() -> None:
    """Off-by--1 with single candidate returns 3-tuple warning."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # Actual range bravo..delta = 3 lines, but we claim 4 (off by +1)
    result = find_content_boundaries(lines, "bravo", "delta", 4)
    assert isinstance(result, tuple)
    assert len(result) == 3
    start, end, warning = result
    assert start == 2
    assert end == 4
    assert "off by" in warning.lower() or "-1" in warning


# ---------------------------------------------------------------------------
# Tolerance ±2 — single candidate → 3-tuple with warning
# ---------------------------------------------------------------------------


def test_tolerance_plus_two_returns_3_tuple() -> None:
    """Off-by-+2 with single candidate returns 3-tuple warning."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # Actual range bravo..delta = 3 lines, but we claim 1 (off by -2)
    result = find_content_boundaries(lines, "bravo", "delta", 1)
    assert isinstance(result, tuple)
    assert len(result) == 3
    start, end, warning = result
    assert start == 2
    assert end == 4
    assert "off by" in warning.lower()


def test_tolerance_minus_two_returns_3_tuple() -> None:
    """Off-by--2 with single candidate returns 3-tuple warning."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # Actual range bravo..delta = 3 lines, but we claim 5 (off by +2)
    result = find_content_boundaries(lines, "bravo", "delta", 5)
    assert isinstance(result, tuple)
    assert len(result) == 3
    start, end, warning = result
    assert start == 2
    assert end == 4
    assert "off by" in warning.lower()


# ---------------------------------------------------------------------------
# Tolerance — multiple candidates → ambiguity error string
# ---------------------------------------------------------------------------


def test_tolerance_multiple_candidates_returns_ambiguity_error() -> None:
    """Multiple tolerance matches return ambiguity error string."""
    # Two identical blocks — both match within tolerance
    lines = _make_lines(
        "START",
        "body",
        "END",
        "filler",
        "START",
        "body",
        "END",
    )
    # Actual range = 3 lines each, claim 2 (off by -1) → 2 tolerance matches
    result = find_content_boundaries(lines, "START", "END", 2)
    assert isinstance(result, str)
    assert "ambiguous" in result.lower()


# ---------------------------------------------------------------------------
# Tolerance — 0 candidates → diagnostic error string
# ---------------------------------------------------------------------------


def test_tolerance_zero_candidates_returns_diagnostic_error() -> None:
    """No matches even with tolerance returns diagnostic error string."""
    lines = _make_lines(
        "alpha",
        "bravo",
        "charlie",
        "delta",
        "echo",
    )
    # bravo..delta = 3 lines, claim 100 — way outside ±2
    result = find_content_boundaries(lines, "bravo", "delta", 100)
    assert isinstance(result, str)
    assert "no matching range" in result.lower()
