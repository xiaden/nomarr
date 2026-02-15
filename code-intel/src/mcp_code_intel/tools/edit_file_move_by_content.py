"""Move text between locations using content boundaries instead of line numbers.

Replaces ``edit_file_move_text`` which relied on fragile line-number
coordinates.  Source range is located via start/end content boundaries;
target insertion point is located via a content anchor.
"""

from __future__ import annotations

from pathlib import Path

from mcp_code_intel.helpers.content_boundaries import (
    find_anchor_line,
    find_content_boundaries,
)
from mcp_code_intel.helpers.file_helpers import (
    build_content,
    check_mtime,
    detect_eol,
    ensure_trailing_newline,
    normalize_eol,
    read_file_with_metadata,
    resolve_file_path,
    resolve_path_for_create,
)

# ---------------------------------------------------------------------------
# Internal helpers (same-file and cross-file)
# ---------------------------------------------------------------------------


def _extract_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Extract lines from *start* to *end* (1-indexed, inclusive)."""
    return lines[start - 1 : end]


def _remove_lines(lines: list[str], start: int, end: int) -> list[str]:
    """Remove lines from *start* to *end* (1-indexed, inclusive)."""
    return lines[: start - 1] + lines[end:]


def _insert_lines(
    lines: list[str], insert_before: int, new_lines: list[str],
) -> list[str]:
    """Insert *new_lines* before *insert_before* (1-indexed)."""
    idx = insert_before - 1
    return lines[:idx] + new_lines + lines[idx:]


def _generate_context(
    lines: list[str], target_line: int, *, context_lines: int = 2,
) -> str:
    """Show a few lines around *target_line* for confirmation."""
    start = max(1, target_line - context_lines)
    end = min(len(lines), target_line + context_lines)
    parts: list[str] = []
    for i in range(start - 1, end):
        lno = i + 1
        parts.append(f"   {lno:3d} | {lines[i].rstrip(chr(10) + chr(13))}")
    return "\n".join(parts)


def _read_and_parse(
    file_path: str, workspace_root: Path,
) -> dict | tuple[Path, str, list[str], list[str], float, str, bool]:
    """Read a file and return parsed line data or an error dict.

    Returns:
        On success: (resolved_path, rel_path, lines_with_eol,
                     plain_lines, mtime, eol, had_trailing_newline)
        On failure: ``{"error": ..., "changed": False}``

    """
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        return {"error": resolved["error"], "changed": False}

    file_data = read_file_with_metadata(resolved)
    if "error" in file_data:
        return {"error": file_data["error"], "changed": False}

    content: str = file_data["content"]
    lines = content.splitlines(keepends=True)
    lines = ensure_trailing_newline(lines)
    plain = [ln.rstrip("\n").rstrip("\r") for ln in lines]
    rel = str(resolved.relative_to(workspace_root))
    trailing = content.endswith(("\n", "\r"))

    return (
        resolved,
        rel,
        lines,
        plain,
        file_data["mtime"],
        file_data["eol"],
        trailing,
    )


# ---------------------------------------------------------------------------
# Same-file move
# ---------------------------------------------------------------------------


def _same_file_move_by_content(
    file_path: str,
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
    target_anchor: str,
    target_position: str,
    workspace_root: Path,
) -> dict:
    """Move a content-bounded block within a single file."""
    parsed = _read_and_parse(file_path, workspace_root)
    if isinstance(parsed, dict):
        return parsed

    (
        path_obj, rel, lines, plain, mtime, _eol, trailing,
    ) = parsed

    # Locate source range
    src_result = find_content_boundaries(
        plain, start_boundary, end_boundary, expected_line_count,
    )
    if isinstance(src_result, str):
        return {"error": src_result, "changed": False}
    src_start, src_end = src_result

    # Locate target anchor
    anchor_result = find_anchor_line(plain, target_anchor)
    if isinstance(anchor_result, str):
        return {"error": anchor_result, "changed": False}
    anchor_line: int = anchor_result  # 1-indexed

    # Determine insertion line (before or after anchor)
    if target_position == "before":
        insert_before = anchor_line
    else:
        insert_before = anchor_line + 1

    # Check for no-op: target within source range
    if src_start <= insert_before <= src_end + 1:
        return {
            "path": rel,
            "changed": False,
            "lines_moved": 0,
            "note": "Target is within source range — no change needed",
        }

    # Extract, remove, adjust target, insert
    moved = _extract_lines(lines, src_start, src_end)
    after_remove = _remove_lines(lines, src_start, src_end)

    adjusted = insert_before
    if insert_before > src_end:
        adjusted -= src_end - src_start + 1

    new_lines = _insert_lines(after_remove, adjusted, moved)
    new_content = build_content(new_lines, had_trailing_newline=trailing)

    # mtime guard
    mtime_err = check_mtime(path_obj, mtime)
    if mtime_err:
        return {"error": mtime_err, "changed": False}

    path_obj.write_bytes(new_content.encode("utf-8"))

    context = _generate_context(new_lines, adjusted)
    return {
        "path": rel,
        "changed": True,
        "lines_moved": src_end - src_start + 1,
        "new_context": context,
    }


# ---------------------------------------------------------------------------
# Cross-file move
# ---------------------------------------------------------------------------


def _cross_file_move_by_content(
    source_file: str,
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
    target_file: str,
    target_anchor: str,
    target_position: str,
    workspace_root: Path,
) -> dict:
    """Move a content-bounded block from one file to another."""
    # --- read source ---
    src_parsed = _read_and_parse(source_file, workspace_root)
    if isinstance(src_parsed, dict):
        return src_parsed
    (
        src_path, src_rel, src_lines, src_plain,
        src_mtime, _src_eol, src_trailing,
    ) = src_parsed

    # --- read target ---
    tgt_parsed = _read_and_parse(target_file, workspace_root)
    if isinstance(tgt_parsed, dict):
        return tgt_parsed
    (
        tgt_path, tgt_rel, tgt_lines, tgt_plain,
        tgt_mtime, tgt_eol, tgt_trailing,
    ) = tgt_parsed

    # --- locate source range ---
    src_result = find_content_boundaries(
        src_plain, start_boundary, end_boundary, expected_line_count,
    )
    if isinstance(src_result, str):
        return {"error": src_result, "changed": False}
    src_start, src_end = src_result

    # --- locate target anchor ---
    anchor_result = find_anchor_line(tgt_plain, target_anchor)
    if isinstance(anchor_result, str):
        return {"error": anchor_result, "changed": False}
    anchor_line: int = anchor_result

    insert_before = anchor_line if target_position == "before" else anchor_line + 1

    # --- build new contents ---
    moved = _extract_lines(src_lines, src_start, src_end)
    normalized = [normalize_eol(ln, tgt_eol) for ln in moved]

    new_src_lines = _remove_lines(src_lines, src_start, src_end)
    new_src = build_content(new_src_lines, had_trailing_newline=src_trailing)

    new_tgt_lines = _insert_lines(tgt_lines, insert_before, normalized)
    new_tgt = build_content(new_tgt_lines, had_trailing_newline=tgt_trailing)

    # --- mtime guards ---
    src_mtime_err = check_mtime(src_path, src_mtime)
    if src_mtime_err:
        return {"error": src_mtime_err, "changed": False}
    tgt_mtime_err = check_mtime(tgt_path, tgt_mtime)
    if tgt_mtime_err:
        return {"error": tgt_mtime_err, "changed": False}

    # Write target first (duplication > data loss on partial failure)
    tgt_path.write_bytes(new_tgt.encode("utf-8"))
    src_path.write_bytes(new_src.encode("utf-8"))

    context = _generate_context(new_tgt_lines, insert_before)
    return {
        "source_file": src_rel,
        "target_file": tgt_rel,
        "changed": True,
        "lines_moved": src_end - src_start + 1,
        "new_context": context,
    }


# ---------------------------------------------------------------------------
# New-file move (no anchor, target must not exist)
# ---------------------------------------------------------------------------


def _new_file_move_by_content(
    source_file: str,
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
    target_file: str,
    workspace_root: Path,
) -> dict:
    """Move a content-bounded block into a brand-new file.

    The target file must **not** already exist — if it does, the call
    fails with a clear error.
    """
    # --- read source ---
    src_parsed = _read_and_parse(source_file, workspace_root)
    if isinstance(src_parsed, dict):
        return src_parsed
    (
        src_path, src_rel, src_lines, src_plain,
        src_mtime, _src_eol, src_trailing,
    ) = src_parsed

    # --- resolve target (must not exist) ---
    tgt_resolved = resolve_path_for_create(target_file, workspace_root)
    if isinstance(tgt_resolved, dict):
        return {"error": tgt_resolved["error"], "changed": False}
    if tgt_resolved.exists():
        return {
            "error": (
                f"Target file already exists: {target_file}. "
                "Provide target_anchor to insert into an existing file."
            ),
            "changed": False,
        }

    # --- locate source range ---
    src_result = find_content_boundaries(
        src_plain, start_boundary, end_boundary, expected_line_count,
    )
    if isinstance(src_result, str):
        return {"error": src_result, "changed": False}
    src_start, src_end = src_result

    # --- build new file content ---
    moved = _extract_lines(src_lines, src_start, src_end)
    tgt_eol = detect_eol(src_path)  # inherit EOL from source
    normalized = [normalize_eol(ln, tgt_eol) for ln in moved]
    new_tgt = "".join(normalized)
    # Ensure trailing newline
    if new_tgt and not new_tgt.endswith(("\n", "\r")):
        new_tgt += tgt_eol

    # --- remove from source ---
    new_src_lines = _remove_lines(src_lines, src_start, src_end)
    new_src = build_content(
        new_src_lines, had_trailing_newline=src_trailing,
    )

    # --- mtime guard (source only — target is new) ---
    src_mtime_err = check_mtime(src_path, src_mtime)
    if src_mtime_err:
        return {"error": src_mtime_err, "changed": False}

    # Write target first (duplication > data loss)
    tgt_resolved.parent.mkdir(parents=True, exist_ok=True)
    tgt_resolved.write_bytes(new_tgt.encode("utf-8"))
    src_path.write_bytes(new_src.encode("utf-8"))

    tgt_rel = str(tgt_resolved.relative_to(workspace_root))
    return {
        "source_file": src_rel,
        "target_file": tgt_rel,
        "changed": True,
        "lines_moved": src_end - src_start + 1,
        "created_new_file": True,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def edit_file_move_by_content(
    file_path: str,
    start_boundary: str,
    end_boundary: str,
    expected_line_count: int,
    target_anchor: str | None,
    target_position: str,
    workspace_root: Path,
    target_file: str | None = None,
) -> dict:
    """Move a content-bounded text range to a new location.

    Source range is located by *start_boundary* / *end_boundary* with
    *expected_line_count* validation (same semantics as
    ``edit_file_replace_by_content``).

    Target insertion point is located by *target_anchor* (single-line
    substring match, must be unique in the target file).

    When *target_anchor* is ``None`` and *target_file* is set, the moved
    block becomes the **entire content** of a newly created file.  The
    target file must **not** already exist in that case.

    Args:
        file_path: Source file.
        start_boundary: Content marking the start of the range to move.
        end_boundary: Content marking the end of the range to move.
        expected_line_count: Safety validation for source range.
        target_anchor: Content line in target to anchor insertion, or
            ``None`` to create a new file from the moved block.
        target_position: ``'before'`` or ``'after'`` the anchor line.
            Ignored when *target_anchor* is ``None``.
        workspace_root: Workspace root for path resolution.
        target_file: Optional target file for cross-file moves.

    Returns:
        Result dict with ``changed``, ``lines_moved``, ``new_context``.

    """
    # --- new-file extraction (no anchor) ---
    if target_anchor is None:
        if target_file is None or target_file == file_path:
            return {
                "error": (
                    "target_anchor is required for same-file moves. "
                    "Omit target_anchor only when extracting to a "
                    "new target_file."
                ),
                "changed": False,
            }
        return _new_file_move_by_content(
            file_path,
            start_boundary,
            end_boundary,
            expected_line_count,
            target_file,
            workspace_root,
        )

    # --- same-file move ---
    if target_file is None or target_file == file_path:
        return _same_file_move_by_content(
            file_path,
            start_boundary,
            end_boundary,
            expected_line_count,
            target_anchor,
            target_position,
            workspace_root,
        )

    # --- cross-file move into existing file ---
    return _cross_file_move_by_content(
        file_path,
        start_boundary,
        end_boundary,
        expected_line_count,
        target_file,
        target_anchor,
        target_position,
        workspace_root,
    )
