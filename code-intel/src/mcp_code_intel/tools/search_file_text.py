"""Quick text search with context - find a string, get 2 lines around it.

Simple search tool for config files, logs, and non-Python text.
"""

__all__ = ["file_search_text"]

from pathlib import Path

from ..helpers.file_lines import read_raw_line_range
from ..helpers.semantic_tool_examples import get_semantic_tool_examples


def search_file_text(file_path: str, search_string: str, workspace_root: Path) -> dict:
    """Search for exact string match and return each occurrence with 2 lines of context.

    Args:
        file_path: Workspace-relative or absolute path to the file
        search_string: Exact text to search for (case-sensitive)
        workspace_root: Project root path

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - matches: List of dicts, each with:
            - line_number: Line where match was found (1-indexed)
            - content: 5 lines (2 before, match, 2 after) or fewer at file boundaries
            - line_range: Range label (e.g., "48-52")
        - total_matches: Count of matches found
        - error: Error message if search fails

    """
    # Guard against empty search string
    if not search_string:
        return {"error": "search_string is required (can't search for nothing)"}

    try:
        # Resolve path relative to workspace root
        target_path = Path(file_path)
        if not target_path.is_absolute():
            target_path = workspace_root / file_path

        # Security check: ensure path is within workspace
        try:
            target_path = target_path.resolve()
            target_path.relative_to(workspace_root)
        except (ValueError, RuntimeError):
            return {"error": f"Path {file_path} is outside workspace root"}

        # Check file exists
        if not target_path.exists():
            return {"error": f"File not found: {file_path}"}

        if not target_path.is_file():
            return {"error": f"Path is not a file: {file_path}"}

        # Read file
        content = target_path.read_text(encoding="utf-8")
        all_lines = content.splitlines(keepends=True)
        total_lines = len(all_lines)

        # Find all matching lines
        matches = []
        for line_idx, line in enumerate(all_lines):
            if search_string in line:
                line_number = line_idx + 1  # Convert to 1-indexed

                # Calculate context range
                start = max(1, line_number - 2)
                end = min(total_lines, line_number + 2)

                # Extract lines with context using raw bytes (preserves exact line endings)
                context_content = read_raw_line_range(str(target_path), start, end)

                # Build line range label
                if start == 1 and end < total_lines:
                    line_range = f"{start}-{end}(start)"
                elif end == total_lines and start > 1:
                    line_range = f"{start}-{end}(EOF)"
                elif start == 1 and end == total_lines:
                    line_range = f"{start}-{end}(entire file)"
                else:
                    line_range = f"{start}-{end}"

                matches.append(
                    {
                        "line_number": line_number,
                        "content": context_content,
                        "line_range": line_range,
                    }
                )

        # Build result
        result = {
            "path": str(target_path.relative_to(workspace_root)),
            "matches": matches,
            "total_matches": len(matches),
        }

        # Add Python file semantic tool guidance
        if target_path.suffix == ".py":
            result["semantic_tools_available"] = {
                "hint": "Python files: semantic tools provide structured output",
                "example_outputs": get_semantic_tool_examples(),
            }

        return result

    except UnicodeDecodeError:
        return {"error": f"File {file_path} is not a valid UTF-8 text file"}
    except Exception as e:
        return {"error": f"Failed to search file: {e!s}"}
