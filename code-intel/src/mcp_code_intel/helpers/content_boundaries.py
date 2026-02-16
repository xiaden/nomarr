"""Content-boundary matching for line-number-free file editing.

Provides functions to locate text ranges by content boundaries instead of line
numbers. Boundaries are matched as stripped substrings against file lines,
supporting multi-line patterns and disambiguating via expected line counts.
"""

from __future__ import annotations


def _find_all_substring_matches(
    file_lines: list[str],
    boundary_lines: list[str],
    *,
    search_start: int = 0,
) -> list[int]:
    """Find all positions where boundary_lines match consecutive file lines.

    Each boundary line is matched as a stripped substring: the stripped boundary
    text must appear within the stripped file line.

    Args:
        file_lines: All lines in the file (no trailing newlines).
        boundary_lines: Boundary pattern lines (already stripped externally
            or will be stripped here).
        search_start: 0-indexed position to start scanning from.

    Returns:
        List of 0-indexed start positions where the boundary matched.

    """
    stripped_boundary = [bl.strip() for bl in boundary_lines]
    if not stripped_boundary or not stripped_boundary[0]:
        return []

    matches: list[int] = []
    boundary_len = len(stripped_boundary)
    last_possible_start = len(file_lines) - boundary_len

    for i in range(search_start, last_possible_start + 1):
        if all(
            stripped_boundary[j] in file_lines[i + j].strip()
            for j in range(boundary_len)
        ):
            matches.append(i)

    return matches


def _format_match_context(
    file_lines: list[str],
    match_line_0idx: int,
    *,
    context_before: int = 2,
    context_after: int = 2,
) -> str:
    """Format context lines around a match for error messages.

    Args:
        file_lines: All lines in the file (no trailing newlines).
        match_line_0idx: 0-indexed line number of the match.
        context_before: Lines to show before match (default 2).
        context_after: Lines to show after match (default 2).

    Returns:
        Formatted string with line numbers and content.
        Match line is marked with ` > `, context lines with `   `.

    """
    total_lines = len(file_lines)
    max_line_num = total_lines  # for width calculation
    width = len(str(max_line_num))

    start = max(0, match_line_0idx - context_before)
    end = min(total_lines - 1, match_line_0idx + context_after)

    lines: list[str] = []
    for i in range(start, end + 1):
        line_num = i + 1  # 1-indexed for display
        content = file_lines[i].rstrip()
        if i == match_line_0idx:
            prefix = " > "
        else:
            prefix = "   "
        lines.append(f"{prefix}{line_num:>{width}} | {content}")

    return "\n".join(lines)


def find_content_boundaries(
    file_lines: list[str],
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
) -> tuple[int, int] | str:
    """Locate a unique text range by its start and end content boundaries.

    Args:
        file_lines: All lines in the file (no trailing newlines).
        start_boundary: Content marking the beginning of the range. May span
            multiple lines (separated by ``\\n``).  Each line is stripped and
            matched as a substring.
        end_boundary: Content marking the end of the range. Same rules.
        expected_line_count: Exact number of lines the matched range must span
            (inclusive of boundary lines).  Serves as a safety check.

    Returns:
        ``(start_line, end_line)`` 1-indexed inclusive, or an error string.

    """
    if expected_line_count == 1 and start_boundary == end_boundary:
        collapsed_line = start_boundary.split("\n", 1)[0].rstrip("\r")
        start_bl = [collapsed_line]
        end_bl = [collapsed_line]
    else:
        start_bl = start_boundary.split("\n")
        end_bl = end_boundary.split("\n")

    # --- find all start-boundary matches ---
    start_matches = _find_all_substring_matches(file_lines, start_bl)
    if not start_matches:
        return (
            f"Start boundary not found in file.\n"
            f"  Searched for: {start_boundary!r}"
        )

    # --- for each start, find matching end + line-count candidates ---
    candidates: list[tuple[int, int]] = []  # (start_0idx, end_0idx_last_line)

    for s in start_matches:
        # End boundary must start no earlier than after the start boundary
        search_from = s + len(start_bl) - 1  # allow overlap on last start line
        if len(start_bl) == 1 and len(end_bl) == 1:
            # Single-line boundaries: end can be the SAME line as start
            search_from = s
        end_matches = _find_all_substring_matches(
            file_lines, end_bl, search_start=search_from,
        )

        for e in end_matches:
            end_last = e + len(end_bl) - 1  # 0-indexed last line of end match
            actual_count = end_last - s + 1
            if actual_count == expected_line_count:
                candidates.append((s, end_last))

    if len(candidates) == 1:
        s0, e0 = candidates[0]
        return (s0 + 1, e0 + 1)  # convert to 1-indexed

    if len(candidates) == 0:
        # Provide diagnostics with context
        diag_parts: list[str] = [
            f"No matching range found with expected_line_count={expected_line_count}.",
        ]

        # Show context for start boundary matches (limit to 2)
        shown_starts = start_matches[:2]
        for i, s in enumerate(shown_starts):
            diag_parts.append(f"  Start boundary match {i + 1} at line {s + 1}:")
            diag_parts.append(_format_match_context(file_lines, s))

        if len(start_matches) > 2:
            diag_parts.append(f"  ... and {len(start_matches) - 2} more start matches")

        # Show end matches from first start with context
        if start_matches:
            first_s = start_matches[0]
            end_matches = _find_all_substring_matches(
                file_lines, end_bl, search_start=first_s,
            )
            if end_matches:
                # Show up to 2 end matches with context
                shown_ends = end_matches[:2]
                for em in shown_ends:
                    end_last = em + len(end_bl) - 1
                    actual = end_last - first_s + 1
                    diag_parts.append(
                        f"  End boundary at line {end_last + 1} "
                        f"(range = {actual} lines, expected {expected_line_count}):"
                    )
                    diag_parts.append(_format_match_context(file_lines, end_last))
                if len(end_matches) > 2:
                    diag_parts.append(f"  ... and {len(end_matches) - 2} more end matches")
            else:
                diag_parts.append("  End boundary not found after start boundary.")

        return "\n".join(diag_parts)

    # Multiple candidates - show context for up to 3
    ambig_parts: list[str] = [
        f"Ambiguous: {len(candidates)} matching ranges found. "
        f"Provide more specific boundaries.",
    ]

    shown_candidates = candidates[:3]
    for i, (s, e) in enumerate(shown_candidates):
        ambig_parts.append(f"  Candidate {i + 1}: lines {s + 1}-{e + 1}")
        ambig_parts.append(f"    Start (line {s + 1}):")
        ambig_parts.append(_format_match_context(file_lines, s))
        ambig_parts.append(f"    End (line {e + 1}):")
        ambig_parts.append(_format_match_context(file_lines, e))

    if len(candidates) > 3:
        ambig_parts.append(f"  ... and {len(candidates) - 3} more candidates")

    return "\n".join(ambig_parts)


def find_anchor_line(
    file_lines: list[str],
    anchor: str,
) -> int | str:
    """Find a unique line by content anchor.

    Args:
        file_lines: All lines in the file (no trailing newlines).
        anchor: Text to search for.  Stripped and matched as a substring
            against each stripped file line.

    Returns:
        1-indexed line number, or an error string.

    """
    stripped_anchor = anchor.strip()
    if not stripped_anchor:
        return "Anchor text is empty."

    matches: list[int] = []
    for i, line in enumerate(file_lines):
        if stripped_anchor in line.strip():
            matches.append(i)

    if len(matches) == 1:
        return matches[0] + 1  # 1-indexed

    if len(matches) == 0:
        return f"Anchor not found: {anchor!r}"

    # Show first few matches for diagnostics
    preview_count = min(5, len(matches))
    previews = [
        f"  Line {m + 1}: {file_lines[m].strip()!r}"
        for m in matches[:preview_count]
    ]
    suffix = (
        f"\n  ... and {len(matches) - preview_count} more"
        if len(matches) > preview_count
        else ""
    )
    return (
        f"Ambiguous anchor: {len(matches)} matches found for {anchor!r}. "
        f"Provide more specific anchor text.\n"
        + "\n".join(previews)
        + suffix
    )
