"""MCP output formatting helpers.

Provides functions to wrap tool results with MCP audience targeting.
Separates presentation logic from tool implementations.
"""

from pathlib import Path
from typing import Any

from mcp.types import Annotations, CallToolResult, TextContent

from ..response_models import BatchResponse


def wrap_mcp_result(
    result: Any,
    user_summary: str,
    *,
    is_error: bool = False,
    tool_name: str | None = None,
    breadcrumb_meta: dict[str, Any] | None = None,
) -> CallToolResult:
    """Wrap domain result with MCP audience-targeted content.

    Args:
        result: Domain object (BatchResponse, dict, Pydantic model)
        user_summary: Human-readable summary for users (can include markdown links)
        is_error: Whether this represents an error state
        tool_name: Optional tool name to prefix in user output
        breadcrumb_meta: Optional structured breadcrumb metadata for extension integration

    Returns:
        CallToolResult with audience-targeted content and breadcrumb metadata
    """
    # Convert to structured content
    if hasattr(result, "model_dump"):
        structured_content = result.model_dump(exclude_none=True)
    elif isinstance(result, dict):
        structured_content = result
    else:
        structured_content = {"result": str(result)}

    # Format outputs
    breadcrumb = f"[{tool_name}] {user_summary}" if tool_name else user_summary

    # Prepare metadata for extension breadcrumbs
    meta = {}
    if breadcrumb_meta:
        meta["breadcrumb"] = breadcrumb_meta

    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=breadcrumb,
                annotations=Annotations(audience=["user"]),
                _meta=meta if meta else None,
            ),
        ],
        structuredContent=structured_content,
        isError=is_error,
    )


def wrap_batch_result(
    batch: BatchResponse,
    formatter,
    *,
    tool_name: str,
) -> CallToolResult:
    """Wrap BatchResponse with formatted output.

    Args:
        batch: BatchResponse from file mutation tool
        formatter: Function that formats BatchResponse to user summary
        tool_name: Name of the MCP tool

    Returns:
        CallToolResult with formatted batch response
    """
    user_summary = formatter(batch)
    is_error = batch.status != "applied"
    return wrap_mcp_result(batch, user_summary, is_error=is_error, tool_name=tool_name)


# ──────────────────────────────────────────────────────────────────────
# File Link Formatting (VS Code Breadcrumb Display)
# ──────────────────────────────────────────────────────────────────────


def make_file_markdown_link(
    file_path: str | Path,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Create markdown-style file link for VS Code breadcrumb display.

    Uses the empty link syntax []() which VS Code renders as a clickable breadcrumb.

    Args:
        file_path: Absolute or relative file path
        start_line: Optional start line (1-based)
        end_line: Optional end line (1-based)

    Returns:
        Markdown link: [](file:///path#L10-L20)
    """
    abs_path = Path(file_path).resolve()
    file_uri = abs_path.as_uri()

    # Add line range fragment if provided
    if start_line is not None:
        if end_line is not None and end_line != start_line:
            file_uri += f"#L{start_line}-L{end_line}"
        else:
            file_uri += f"#L{start_line}"

    # Empty brackets create clickable breadcrumb in VS Code
    return f"{file_uri}"


def wrap_mcp_result_with_file_link(
    result: Any,
    file_path: str | Path,
    start_line: int | None = None,
    end_line: int | None = None,
    *,
    action: str = "Read",
    tool_name: str | None = None,
) -> CallToolResult:
    """Wrap result with clickable file link in user summary.

    Args:
        result: Domain object to return
        file_path: File path to link to
        start_line: Optional start line (1-based)
        end_line: Optional end line (1-based)
        action: Action verb (Read, Edited, Created, etc.)
        tool_name: Optional tool name

    Returns:
        CallToolResult with clickable file breadcrumb and structured metadata
    """
    # Create markdown link for breadcrumb
    file_link = make_file_markdown_link(file_path, start_line, end_line)

    # Build user-friendly summary with line info
    line_info = ""
    if start_line is not None:
        if end_line is not None and end_line != start_line:
            line_info = f", lines {start_line} to {end_line}"
        else:
            line_info = f", line {start_line}"

    user_summary = f"{action} {file_link}{line_info}"

    # Create structured breadcrumb metadata for extension
    breadcrumb_meta: dict[str, Any] = {
        "type": "file_location",
        "action": action,
        "file_path": str(file_path),
    }
    if start_line is not None:
        breadcrumb_meta["start_line"] = start_line
    if end_line is not None:
        breadcrumb_meta["end_line"] = end_line

    return wrap_mcp_result(
        result, user_summary, tool_name=tool_name, breadcrumb_meta=breadcrumb_meta
    )


def wrap_mcp_result_with_multiple_file_links(
    result: Any,
    file_locations: list[tuple[str | Path, int | None, int | None, str]],
    *,
    tool_name: str | None = None,
) -> CallToolResult:
    """Wrap result with multiple clickable file links.

    Args:
        result: Domain object to return
        file_locations: List of (file_path, start_line, end_line, action) tuples
        tool_name: Optional tool name

    Returns:
        CallToolResult with multiple clickable file breadcrumbs and structured metadata
    """
    # Create markdown links for each file
    file_links = []
    locations_meta = []

    for file_path, start_line, end_line, action in file_locations:
        link = make_file_markdown_link(file_path, start_line, end_line)

        line_info = ""
        if start_line is not None:
            if end_line is not None and end_line != start_line:
                line_info = f", lines {start_line}-{end_line}"
            else:
                line_info = f", line {start_line}"

        file_links.append(f"{action} {link}{line_info}")

        # Add structured metadata for each file
        location_meta: dict[str, Any] = {
            "action": action,
            "file_path": str(file_path),
        }
        if start_line is not None:
            location_meta["start_line"] = start_line
        if end_line is not None:
            location_meta["end_line"] = end_line
        locations_meta.append(location_meta)

    # Join with newlines for multi-line breadcrumb
    user_summary = "\n".join(file_links)

    # Create structured breadcrumb metadata
    breadcrumb_meta = {
        "type": "multiple_file_locations",
        "locations": locations_meta,
    }

    return wrap_mcp_result(
        result, user_summary, tool_name=tool_name, breadcrumb_meta=breadcrumb_meta
    )


# ──────────────────────────────────────────────────────────────────────
# Legacy/Deprecated Helpers
# ──────────────────────────────────────────────────────────────────────


def make_workspace_relative(path: str | Path, workspace_root: Path) -> str:
    """Convert absolute path to workspace-relative path with forward slashes.

    Args:
        path: Absolute or relative path
        workspace_root: Workspace root directory

    Returns:
        Workspace-relative path with forward slashes
    """
    path_obj = Path(path)
    try:
        # Try to make relative to workspace
        rel_path = path_obj.relative_to(workspace_root)
        return str(rel_path).replace("\\", "/")
    except ValueError:
        # Path is outside workspace or already relative
        return str(path_obj).replace("\\", "/")


def format_file_link(file_path: str | Path, workspace_root: Path | None = None) -> str:
    """Format file path as workspace-relative path.

    Deprecated: Use wrap_mcp_result_with_file_link() for clickable breadcrumbs.

    Args:
        file_path: File path to format
        workspace_root: Optional workspace root

    Returns:
        Workspace-relative path
    """
    if workspace_root:
        return make_workspace_relative(file_path, workspace_root)
    else:
        return str(Path(file_path).name)


def format_file_line_link(
    file_path: str | Path, line: int, workspace_root: Path | None = None
) -> str:
    """Format file:line as text.

    Deprecated: Use wrap_mcp_result_with_file_link() for clickable breadcrumbs.

    Args:
        file_path: File path to format
        line: Line number (1-indexed)
        workspace_root: Optional workspace root

    Returns:
        Path with line: file.py:42
    """
    if workspace_root:
        rel_path = make_workspace_relative(file_path, workspace_root)
    else:
        rel_path = str(Path(file_path).name)
    return f"{rel_path}:{line}"


def format_file_range_link(
    file_path: str | Path,
    start_line: int,
    end_line: int,
    workspace_root: Path | None = None,
) -> str:
    """Format file with line range as text.

    Deprecated: Use wrap_mcp_result_with_file_link() for clickable breadcrumbs.

    Args:
        file_path: File path to format
        start_line: Start line number (1-indexed)
        end_line: End line number (1-indexed)
        workspace_root: Optional workspace root

    Returns:
        Path with range: file.py:10-20
    """
    if workspace_root:
        rel_path = make_workspace_relative(file_path, workspace_root)
    else:
        rel_path = str(Path(file_path).name)
    return f"{rel_path}:{start_line}-{end_line}"
