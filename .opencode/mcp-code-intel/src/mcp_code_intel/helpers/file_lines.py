"""Helper for reading raw file lines for deterministic replacement.

Any MCP tool returning source code for replacement should use this helper
to ensure the returned text matches the actual file bytes exactly.
"""

from __future__ import annotations

from pathlib import Path


def calculate_range_with_context(
    target_line: int | None,
    start_line: int | None,
    end_line: int | None,
    total_lines: int,
    context_lines: int = 2,
) -> tuple[int, int]:
    """Calculate line range with context padding for replacement safety.

    Provides consistent context padding across all file read tools to ensure
    replacements have enough surrounding context to match uniquely.

    This is used by read_file_line and read_file_line_range to automatically
    return extra context around the requested range.

    Args:
        target_line: Single target line (for read_file_line)
        start_line: Range start (for read_file_line_range)
        end_line: Range end (for read_file_line_range)
        total_lines: Total lines in file
        context_lines: Lines of context to add before/after (default: 2)

    Returns:
        Tuple of (effective_start, effective_end) clamped to [1, total_lines]

    Examples:
        # Single line with 2 context: Request line 50 → Returns lines 48-52
        calculate_range_with_context(50, None, None, 100)  # (48, 52)

        # Range with 2 context: Request lines 20-25 → Returns lines 18-27
        calculate_range_with_context(None, 20, 25, 100)  # (18, 27)
    """
    if target_line is not None:
        # Single line mode - add context around target
        start = max(1, target_line - context_lines)
        end = min(total_lines, target_line + context_lines)
    else:
        # Range mode - add context around requested range
        if start_line is None or end_line is None:
            raise ValueError("Must provide either target_line or (start_line, end_line)")
        start = max(1, start_line - context_lines)
        end = min(total_lines, end_line + context_lines)

    return start, end


def read_raw_lines(file_path: str | Path, start_line: int, total_lines: int) -> str:
    """Read raw lines from a file, preserving exact bytes.

    This is the canonical way to get source text for replacement operations.
    Uses binary read + decode to preserve exact line endings and whitespace.

    Args:
        file_path: Path to the file.
        start_line: 1-indexed line number to start from.
        total_lines: Number of lines to read.

    Returns:
        Raw string content of the specified lines, including line endings.

    Raises:
        FileNotFoundError: If file doesn't exist.
        ValueError: If start_line < 1 or total_lines < 1.

    """
    if start_line < 1:
        msg = f"start_line must be >= 1, got {start_line}"
        raise ValueError(msg)
    if total_lines < 1:
        msg = f"total_lines must be >= 1, got {total_lines}"
        raise ValueError(msg)

    path = Path(file_path)
    if not path.exists():
        msg = f"File not found: {file_path}"
        raise FileNotFoundError(msg)

    # Read as binary to preserve exact bytes, then decode
    raw_bytes = path.read_bytes()

    # Detect line ending style
    if b"\r\n" in raw_bytes:
        line_ending = "\r\n"
    elif b"\r" in raw_bytes:
        line_ending = "\r"
    else:
        line_ending = "\n"

    # Decode and split
    content = raw_bytes.decode("utf-8")
    lines = content.split(line_ending)

    # Extract the requested range (convert to 0-indexed)
    start_idx = start_line - 1
    end_idx = start_idx + total_lines

    if start_idx >= len(lines):
        msg = f"start_line {start_line} exceeds file length ({len(lines)} lines)"
        raise ValueError(msg)

    selected = lines[start_idx:end_idx]

    # Rejoin with original line ending
    return line_ending.join(selected)


def read_raw_line_range(file_path: str | Path, start_line: int, end_line: int) -> str:
    """Read raw lines from start_line to end_line (inclusive).

    Convenience wrapper around read_raw_lines.

    Args:
        file_path: Path to the file.
        start_line: 1-indexed start line (inclusive).
        end_line: 1-indexed end line (inclusive).

    Returns:
        Raw string content of the specified lines.

    """
    if end_line < start_line:
        msg = f"end_line ({end_line}) must be >= start_line ({start_line})"
        raise ValueError(msg)

    total_lines = end_line - start_line + 1
    return read_raw_lines(file_path, start_line, total_lines)
