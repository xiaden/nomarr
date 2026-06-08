"""MCP output formatting helpers.

Provides ToolOutput, the unified return DTO for all MCP tools.
Builds CallToolResult with proper content array:
- User breadcrumb (audience=["user"])
- Assistant content items (audience=["assistant"], priority=1.0)
- JSON metadata as TextContent
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mcp.types import (
    Annotations,
    AudioContent,
    CallToolResult,
    EmbeddedResource,
    ImageContent,
    ResourceLink,
    TextContent,
)

# ──────────────────────────────────────────────────────────────────────
# File Link Formatting (VS Code Breadcrumb Display)
# ──────────────────────────────────────────────────────────────────────


def _format_line_info(start_line: int | None, end_line: int | None) -> str:
    """Format line range information for display."""
    if start_line is None:
        return ""
    if end_line is not None and end_line != start_line:
        return f", lines {start_line} to {end_line}"
    return f", line {start_line}"


def make_file_markdown_link(
    file_path: str | Path,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    """Create file URI for VS Code breadcrumb display.

    Args:
        file_path: Absolute or relative file path
        start_line: Optional start line (1-based)
        end_line: Optional end line (1-based)

    Returns:
        File URI string: file:///path#L10-L20

    """
    abs_path = Path(file_path).resolve()
    file_uri = abs_path.as_uri()

    if start_line is not None:
        if end_line is not None and end_line != start_line:
            file_uri += f"#L{start_line}-L{end_line}"
        else:
            file_uri += f"#L{start_line}"

    return file_uri


# ──────────────────────────────────────────────────────────────────────
# FileLink — individual file reference
# ──────────────────────────────────────────────────────────────────────


@dataclass
class FileLink:
    """A file reference with optional line range and action label."""

    file_path: str | Path
    start_line: int | None = None
    end_line: int | None = None
    action: str = "Read"
    line_count: int | None = None


# ──────────────────────────────────────────────────────────────────────
# ToolOutput — unified output DTO for all tools
# ──────────────────────────────────────────────────────────────────────


@dataclass
class ToolOutput:
    """Unified return DTO for all MCP tools.

    Five explicit content channels — tools declare what each audience sees:

    - tool_name: Tool identifier (used in breadcrumb prefix)
    - breadcrumb: User-facing summary. Auto-generated from tool_name + file_links
                  if left empty.
    - assistant_content: Text items the model should reason about (source code,
                         lint output, traces). Each becomes a separate TextContent
                         with audience=["assistant"], priority=1.0.
    - metadata: Structured data for programmatic use (line numbers, match counts,
                status). Serialized as JSON TextContent with no audience restriction.
    - error: Error message if the tool failed. When set, isError=True on the result
             and the error appears as its own TextContent item.
    - file_links: Optional file references for VS Code breadcrumb integration.
                  Encoded in breadcrumb text and _meta, not as separate content items.

    Usage (simple tool, no files)::

        return ToolOutput(
            tool_name="list_project_routes",
            breadcrumb="Listed all API routes",
            metadata=result,
        ).to_call_tool_result()

    Usage (read tool with source code)::

        source = result.pop("source")
        return ToolOutput(
            tool_name="read_module_source",
            assistant_content=[source],
            metadata=result,
            file_links=[FileLink(file_path="nomarr/app.py", start_line=10, end_line=20)],
        ).to_call_tool_result()

    Usage (error result)::

        return ToolOutput(
            tool_name="edit_file_move",
            error="Target file already exists",
            metadata=result,
        ).to_call_tool_result()

    """

    tool_name: str
    breadcrumb: str = ""
    assistant_content: list[str] | None = None
    metadata: dict[str, Any] | None = None
    error: str | None = None
    file_links: list[FileLink] | None = None

    def _build_breadcrumb(self) -> str:
        r"""Build the user-facing breadcrumb string.

        - breadcrumb set + file_links: ``[tool] summary\nuri1\nuri2``
        - breadcrumb set, no links: ``[tool] summary``
        - no breadcrumb + file_links: ``[tool] action uri`` per link
        - neither: ``[tool]``

        When a breadcrumb header is present, file links render as bare URIs
        (no action prefix) since the header already provides context.
        """
        if self.breadcrumb:
            header = f"[{self.tool_name}] {self.breadcrumb}"
            link_lines = self._format_file_link_lines(bare=True)
            return f"{header}\n{link_lines}" if link_lines else header

        link_lines = self._format_file_link_lines()
        if link_lines:
            return f"[{self.tool_name}] {link_lines}"

        return f"[{self.tool_name}]"

    def _format_file_link_lines(self, *, bare: bool = False) -> str:
        """Render file links as lines for breadcrumb display.

        When *bare* is True, action prefixes are suppressed (used when a
        breadcrumb header already provides context).  If a link has
        ``line_count`` set, it is appended as ``N lines`` after the URI.
        """
        if not self.file_links:
            return ""
        parts: list[str] = []
        for link in self.file_links:
            uri = make_file_markdown_link(link.file_path, link.start_line, link.end_line)
            suffix = f" {link.line_count} lines" if link.line_count is not None else ""
            if not bare and link.action:
                parts.append(f"{link.action} {uri}{suffix}")
            else:
                parts.append(f"{uri}{suffix}")
        return "\n".join(parts)

    def _build_breadcrumb_meta(self) -> dict[str, Any] | None:
        """Build structured breadcrumb metadata for extension integration."""
        if not self.file_links:
            return None

        if len(self.file_links) == 1:
            link = self.file_links[0]
            meta: dict[str, Any] = {
                "type": "file_location",
                "action": link.action,
                "file_path": str(link.file_path),
            }
            if link.start_line is not None:
                meta["start_line"] = link.start_line
            if link.end_line is not None:
                meta["end_line"] = link.end_line
            return meta

        locations = []
        for link in self.file_links:
            loc: dict[str, Any] = {
                "action": link.action,
                "file_path": str(link.file_path),
            }
            if link.start_line is not None:
                loc["start_line"] = link.start_line
            if link.end_line is not None:
                loc["end_line"] = link.end_line
            locations.append(loc)
        return {"type": "multiple_file_locations", "locations": locations}

    def to_call_tool_result(self) -> CallToolResult:
        """Build CallToolResult with content array.

        Content order:
        1. User breadcrumb (audience=["user"], with _meta from file_links)
        2. Error text if error is set (no audience restriction)
        3. Assistant content items (audience=["assistant"], priority=1.0)
        4. JSON metadata blob (no audience restriction)

        """
        breadcrumb_text = self._build_breadcrumb()
        breadcrumb_meta = self._build_breadcrumb_meta()

        meta_wrapper: dict[str, Any] = {}
        if breadcrumb_meta:
            meta_wrapper["breadcrumb"] = breadcrumb_meta

        items: list[TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource] = [
            TextContent(
                type="text",
                text=breadcrumb_text,
                annotations=Annotations(audience=["user"]),
                _meta=meta_wrapper if meta_wrapper else None,
            ),
        ]

        # Error content — visible to both user and assistant
        if self.error:
            items.append(
                TextContent(
                    type="text",
                    text=self.error,
                ),
            )

        # Assistant content — source code, lint output, traces
        if self.assistant_content:
            items.extend(
                TextContent(
                    type="text",
                    text=text,
                    annotations=Annotations(audience=["assistant"], priority=1.0),
                )
                for text in self.assistant_content
            )

        # Metadata — structured data as JSON
        if self.metadata:
            items.append(
                TextContent(
                    type="text",
                    text=json.dumps(self.metadata),
                ),
            )

        return CallToolResult(
            content=items,
            isError=self.error is not None,
        )
