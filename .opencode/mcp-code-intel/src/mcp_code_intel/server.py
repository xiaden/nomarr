"""Nomarr Coding Tools MCP Server (opencode fork).

Stripped-down version for opencode — removed file editing tools and other
tools that opencode handles natively. Fixed workspace root detection to
work outside VS Code.

Project navigation:
- read_module_api: Show public API of any nomarr module (signatures, methods, constants)
- read_module_source: Get source code of a specific function/method/class
- read_file_symbol_at_line: Get full function/class containing a line

Call tracing:
- trace_module_calls: Trace call chains from entry point through layers
- trace_project_endpoint: Resolve FastAPI DI to trace full endpoint behavior

Quality validation:
- lint_project_backend: Run ruff (check + format) + mypy on modified files
- lint_project_frontend: Run ESLint, TypeScript type checking, and Vitest on frontend

Task plan tools:
- plan_read: Read a task plan as structured JSON
- plan_complete_step: Mark a step complete and get next step

Artifact tools:
- log_read/log_write/log_archive: Agent logging
- adr_suggest/adr_commit/adr_read/adr_search: Architecture Decision Records
- asr_create/asr_read/asr_search: Architecturally Significant Requirements
- dd_create/dd_read/dd_archive: Design Documents

Python introspection:
- py_introspect: Run whitelist-only Python introspection checks in isolated subprocess

Usage:
    python -m mcp_code_intel
"""

import logging
import os
import sys
from pathlib import Path
from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult

from .helpers.config_loader import load_config
from .helpers.mcp_output_helper import (
    FileLink,
    ToolOutput,
)
from .tools.adr_commit import adr_commit as adr_commit_impl
from .tools.adr_read import adr_read as adr_read_impl
from .tools.adr_search import adr_search as adr_search_impl
from .tools.adr_suggest import adr_suggest as adr_suggest_impl
from .tools.asr_create import asr_create as asr_create_impl
from .tools.asr_read import asr_read as asr_read_impl
from .tools.asr_search import asr_search as asr_search_impl
from .tools.dd_archive import dd_archive as dd_archive_impl
from .tools.dd_create import dd_create as dd_create_impl
from .tools.dd_read import dd_read as dd_read_impl
from .tools.lint_project_backend import lint_project_backend as lint_project_backend_impl
from .tools.lint_project_frontend import lint_project_frontend as lint_project_frontend_impl
from .tools.log_archive import log_archive as log_archive_impl
from .tools.log_read import log_read as log_read_impl
from .tools.log_write import log_write as log_write_impl
from .tools.plan_archive import plan_archive as plan_archive_impl
from .tools.plan_complete_step import plan_complete_step as plan_complete_step_impl
from .tools.plan_read import plan_read as plan_read_impl
from .tools.py_introspect import py_introspect as py_introspect_impl
from .tools.read_file_symbol_at_line import (
    read_file_symbol_at_line as read_file_symbol_at_line_impl,
)
from .tools.read_module_api import read_module_api as read_module_api_impl
from .tools.read_module_source import read_module_source as read_module_source_impl
from .tools.trace_module_calls import trace_module_calls as trace_module_calls_impl
from .tools.trace_project_endpoint import trace_project_endpoint as trace_project_endpoint_impl

# Tool registry for programmatic access
TOOL_IMPLS: dict[str, object] = {
    "adr_commit": adr_commit_impl,
    "adr_read": adr_read_impl,
    "adr_suggest": adr_suggest_impl,
    "adr_search": adr_search_impl,
    "asr_create": asr_create_impl,
    "asr_read": asr_read_impl,
    "asr_search": asr_search_impl,
    "dd_archive": dd_archive_impl,
    "dd_create": dd_create_impl,
    "dd_read": dd_read_impl,
    "log_archive": log_archive_impl,
    "log_read": log_read_impl,
    "log_write": log_write_impl,
    "plan_archive": plan_archive_impl,
    "plan_complete_step": plan_complete_step_impl,
    "plan_read": plan_read_impl,
    "lint_project_backend": lint_project_backend_impl,
    "lint_project_frontend": lint_project_frontend_impl,
    "read_module_api": read_module_api_impl,
    "read_module_source": read_module_source_impl,
    "read_file_symbol_at_line": read_file_symbol_at_line_impl,
    "trace_module_calls": trace_module_calls_impl,
    "trace_project_endpoint": trace_project_endpoint_impl,
    "py_introspect": py_introspect_impl,
}

# ──────────────────────────────────────────────────────────────────────
# Early Setup: Configure logging to stderr (NEVER stdout for MCP stdio)
# ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s: %(message)s",
    stream=sys.stderr,  # Critical: MCP uses stdout for JSON-RPC
)

# Suppress noisy loggers
for noisy_logger in ["asyncio", "urllib3", "httpcore", "httpx"]:
    logging.getLogger(noisy_logger).setLevel(logging.ERROR)


def _detect_workspace_root() -> Path:
    """Detect workspace root without relying on cwd.

    Priority:
    1. OPENCODE_WORKSPACE_ROOT env var (explicit override)
    2. Walk up from this file's location looking for .git or pyproject.toml
    3. Fall back to cwd (original behavior)
    """
    # 1. Explicit env var
    env_root = os.environ.get("OPENCODE_WORKSPACE_ROOT")
    if env_root:
        p = Path(env_root).resolve()
        if p.is_dir():
            return p

    # 2. Walk up from this file's location
    # This file is at .opencode/mcp-code-intel/src/mcp_code_intel/server.py
    # So workspace root is 4 levels up from __file__
    here = Path(__file__).resolve().parent
    for parent in [here, *here.parents]:
        if (parent / ".git").exists() or (parent / "pyproject.toml").exists():
            return parent

    # 3. Fallback to cwd
    return Path.cwd()


ROOT = _detect_workspace_root()

# ──────────────────────────────────────────────────────────────────────
# Configuration Validation
# ──────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)
logger.info("Workspace root: %s", ROOT)


# Global config loaded at startup
_config: dict = {}


def _validate_config_on_startup() -> dict:
    """Validate MCP configuration on startup."""
    try:
        config = load_config(ROOT)
        logger.info(f"Configuration loaded from {ROOT}")
        return config
    except Exception as e:
        logger.warning(f"Config validation error: {type(e).__name__}: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────
# Initialize MCP server
# ──────────────────────────────────────────────────────────────────────

mcp = FastMCP(
    name="coding-tools",
    instructions=(
        "Provides static analysis of Python code, call tracing, linting, "
        "and artifact management. Use read_module_api for module discovery, "
        "read_module_source for symbol bodies, trace_module_calls/trace_project_endpoint "
        "for call chains. No tools execute code or modify files."
    ),
)


def _extract_tool_error(result: dict[str, Any]) -> str | None:
    """Extract error message from a tool result dict, if present."""
    if "error" not in result:
        return None
    msg: str = result.get("message") or result["error"]
    return msg


# Validate configuration on startup
_config = _validate_config_on_startup()


# ──────────────────────────────────────────────────────────────────────
# Python Code Navigation Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def read_module_api(
    module_name: Annotated[str, "Fully qualified module name (e.g., 'nomarr.components.ml')"],
) -> CallToolResult:
    """Discover the entire API of any Python module."""
    result = read_module_api_impl(module_name)
    error = _extract_tool_error(result)
    file_path = result.get("file")
    file_links = [FileLink(file_path=file_path, action="")] if file_path else None
    return ToolOutput(
        tool_name="read_module_api",
        breadcrumb=f"Read API for module: {module_name} at:",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def read_module_source(
    qualified_name: Annotated[
        str | None,
        "Dotted Python import path, e.g. 'nomarr.persistence.db.Database.close'. "
        "Mutually exclusive with file_path+symbol.",
    ] = None,
    *,
    file_path: Annotated[
        str | None,
        "Workspace-relative or absolute file path, e.g. 'nomarr/persistence/db.py'. "
        "Must be paired with 'symbol'. Mutually exclusive with qualified_name.",
    ] = None,
    symbol: Annotated[
        str | None,
        "Dotted symbol name within the file, e.g. 'Database.close'. "
        "Only valid alongside file_path.",
    ] = None,
    large_context: Annotated[bool, "If True, include 10 lines context (default: 2 lines)"] = False,
) -> CallToolResult:
    """Get source code of a Python function, method, or class by import path.

    Uses static AST parsing (no code execution). Returns symbol with context lines
    plus exact symbol boundaries for precise replacements.
    """
    result = read_module_source_impl(
        qualified_name, file_path=file_path, symbol=symbol, large_context=large_context
    )
    error = _extract_tool_error(result)
    file_path = result.get("file")
    start_line = result.get("symbol_start_line")
    end_line = result.get("symbol_end_line")
    source = result.pop("source", "")
    file_links = None
    if file_path and start_line:
        file_links = [
            FileLink(
                file_path=file_path,
                start_line=start_line,
                end_line=end_line,
                action="",
            ),
        ]
    return ToolOutput(
        tool_name="read_module_source",
        breadcrumb="Read source:",
        error=error,
        assistant_content=[source] if source else None,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def read_file_symbol_at_line(
    file_path: Annotated[str, "Absolute or relative path to Python file"],
    line_number: Annotated[int, "Line number (1-indexed) from error message or trace"],
) -> CallToolResult:
    """Get full function/method/class containing a line for contextual understanding."""
    result = read_file_symbol_at_line_impl(file_path, line_number, ROOT)
    error = _extract_tool_error(result)
    source = result.pop("source", "")
    symbol_name = result.get("qualified_name", "symbol")
    return ToolOutput(
        tool_name="read_file_symbol_at_line",
        breadcrumb=f"Read {symbol_name} at:",
        error=error,
        assistant_content=[source] if source else None,
        metadata=result,
        file_links=[
            FileLink(
                file_path=file_path,
                start_line=line_number,
                end_line=line_number,
                action="",
            ),
        ],
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Quality Validation Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def lint_project_backend(
    path: Annotated[
        str | None, "Relative path to lint (e.g., 'nomarr/services'). Default: 'nomarr/'"
    ] = None,
    *,
    check_all: Annotated[
        bool,
        "If True, lint ALL files in path. "
        "If False (default), only lint git-modified and untracked files.",
    ] = False,
) -> CallToolResult:
    """Run backend linting tools on specified path."""
    result = lint_project_backend_impl(path, check_all)
    summary = result.get("summary", {})
    is_clean = summary.get("clean", False)

    file_links: list[FileLink] = []
    if not is_clean:
        for tool_name in ("ruff", "ruff-format", "mypy", "import-linter"):
            tool_errors = result.get(tool_name, {})
            for code_info in tool_errors.values():
                for occ in code_info.get("occurrences", []):
                    file_path = occ.get("file")
                    line = occ.get("line")
                    if file_path:
                        file_links.append(
                            FileLink(file_path=file_path, start_line=line, action="Error")
                        )
                    if len(file_links) >= 10:
                        break
                if len(file_links) >= 10:
                    break
            if len(file_links) >= 10:
                break

    pytest_status = result.get("pytest", {}).get("status", "")
    if is_clean and pytest_status == "pass":
        breadcrumb = f"Linted {path or 'nomarr/'} - all checks passed (tests OK)"
    elif is_clean and pytest_status in ("skipped", ""):
        breadcrumb = f"Linted {path or 'nomarr/'} - all checks passed"
    elif pytest_status == "fail":
        breadcrumb = f"Linted {path or 'nomarr/'} with errors (pytest failed)"
    else:
        breadcrumb = (
            f"Linted {path or 'nomarr/'} - all checks passed"
            if is_clean
            else f"Linted {path or 'nomarr/'} with errors"
        )
    return ToolOutput(
        tool_name="lint_project_backend",
        breadcrumb=breadcrumb,
        metadata=result,
        file_links=file_links or None,
    ).to_call_tool_result()


@mcp.tool()
def lint_project_frontend() -> CallToolResult:
    """Run frontend linting tools (ESLint, TypeScript, and Vitest)."""
    result = lint_project_frontend_impl()
    status = result.get("status", "")
    is_error = status == "error"

    file_links: list[FileLink] = []
    if status == "errors":
        for err in result.get("errors", [])[:10]:
            file_path = err.get("file")
            line = err.get("line")
            if file_path:
                file_links.append(FileLink(file_path=file_path, start_line=line, action="Error"))

    if is_error:
        error_message = result.get("summary", {}).get("error", "unknown")
        breadcrumb = f"Frontend lint error: {error_message}"
    elif status == "clean":
        breadcrumb = "Linted frontend - all checks passed"
    else:
        breadcrumb = "Frontend lint completed with errors"

    return ToolOutput(
        tool_name="lint_project_frontend",
        breadcrumb=breadcrumb,
        metadata=result,
        error=result.get("summary", {}).get("error") if is_error else None,
        file_links=file_links or None,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Design Document Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def dd_create(
    title: Annotated[str, "Title of the design document"],
    slug: Annotated[str, "URL-safe slug (lowercase, hyphens, e.g., 'schema-refactor-v1')"],
    status: Annotated[str, "Status: Draft, Approved, Completed, or Superseded"],
    author: Annotated[str, "Author agent or person name (e.g., 'RnD-DDAuthor')"],
    scope: Annotated[str, "Scope section content"],
    problem_statement: Annotated[str, "Problem Statement section content"],
    architecture: Annotated[str, "Architecture section content"],
    design_goals: Annotated[str, "Design Goals section content (optional)"] = "",
    constraints: Annotated[str, "Constraints section content (optional)"] = "",
    open_questions: Annotated[str, "Open Questions section content (optional)"] = "",
    related_documents: Annotated[
        list[dict[str, str]] | None,
        "Related docs list [{title, path, description}] (optional)",
    ] = None,
    extra_sections: Annotated[
        list[dict[str, str]] | None,
        "Additional sections [{heading, content}] appended after standard sections (optional)",
    ] = None,
) -> CallToolResult:
    """Create a new Design Document (DD) markdown file in artifacts/designs/pending/."""
    result = dd_create_impl(
        title=title,
        slug=slug,
        status=status,
        author=author,
        scope=scope,
        problem_statement=problem_statement,
        architecture=architecture,
        design_goals=design_goals,
        constraints=constraints,
        open_questions=open_questions,
        related_documents=related_documents,
        extra_sections=extra_sections,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="created")]
    return ToolOutput(
        tool_name="dd_create",
        breadcrumb="Created DD at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def dd_read(
    name: Annotated[
        str,
        "DD name — slug ('my-feature'), filename ('DD-my-feature.md'), or prefix ('DD-my-feature')",
    ],
) -> CallToolResult:
    """Read and parse an existing Design Document."""
    result = dd_read_impl(name, workspace_root=ROOT)
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="")]
    return ToolOutput(
        tool_name="dd_read",
        breadcrumb="Read DD at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Architecture Decision Record Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def adr_suggest(
    title: Annotated[str, "Title of the architecture decision"],
    status: Annotated[str, "Status: Proposed, Accepted, Deprecated, or Superseded"],
    tags: Annotated[list[str], "Tags for categorization (at least one required)"],
    context: Annotated[str, "Context section — why this decision is needed"],
    decision: Annotated[str, "Decision section — what was decided"],
    consequences: Annotated[str, "Consequences section — what follows from this decision"],
    references: Annotated[str, "References section content (optional)"] = "",
    source_log: Annotated[str, "Source log reference '{agent}#L{N}' (optional)"] = "",
    extra_sections: Annotated[
        list[dict[str, str]] | None,
        "Additional sections [{heading, content}] inserted before References (optional)",
    ] = None,
    supersedes: Annotated[
        list[str] | None, "List of ADR identifiers this decision supersedes"
    ] = None,
) -> CallToolResult:
    """Preview an ADR without writing to disk."""
    if supersedes is None:
        supersedes = []
    result = adr_suggest_impl(
        title=title,
        status=status,
        tags=tags,
        context=context,
        decision=decision,
        consequences=consequences,
        references=references,
        source_log=source_log,
        extra_sections=extra_sections,
        supersedes=supersedes,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "draft_path" in result:
        file_links = [FileLink(file_path=ROOT / result["draft_path"], action="draft")]
    return ToolOutput(
        tool_name="adr_suggest",
        breadcrumb="ADR draft saved at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def adr_commit(
    draft_id: Annotated[
        str,
        "Slug from adr_suggest (e.g. 'use-onnx-runtime'). "
        "If provided, all content is loaded from the staging draft file.",
    ] = "",
    title: Annotated[str, "Title of the architecture decision (optional when draft_id given)"] = "",
    status: Annotated[
        str, "Status: Proposed, Accepted, Deprecated, or Superseded (optional when draft_id given)"
    ] = "",
    tags: Annotated[list[str], "Tags for categorization (optional when draft_id given)"] = [],  # noqa: B006
    context: Annotated[
        str, "Context section — why this decision is needed (optional when draft_id given)"
    ] = "",
    decision: Annotated[
        str, "Decision section — what was decided (optional when draft_id given)"
    ] = "",
    consequences: Annotated[
        str, "Consequences section — what follows from this decision (optional when draft_id given)"
    ] = "",
    references: Annotated[str, "References section content (optional)"] = "",
    source_log: Annotated[str, "Source log reference '{agent}#L{N}' (optional)"] = "",
    extra_sections: Annotated[
        list[dict[str, str]] | None,
        "Additional sections [{heading, content}] inserted before References (optional)",
    ] = None,
    supersedes: Annotated[
        list[str] | None, "List of ADR identifiers this decision supersedes"
    ] = None,
) -> CallToolResult:
    """Write an approved ADR to disk in artifacts/decisions/."""
    if supersedes is None:
        supersedes = []
    result = adr_commit_impl(
        title=title,
        status=status,
        tags=tags or [],
        context=context,
        decision=decision,
        consequences=consequences,
        references=references,
        source_log=source_log,
        extra_sections=extra_sections,
        supersedes=supersedes,
        draft_id=draft_id,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="created")]
    return ToolOutput(
        tool_name="adr_commit",
        breadcrumb="Created ADR at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def adr_read(
    name: Annotated[
        str,
        "ADR identifier — number ('3', '003'), filename "
        "('ADR-003-use-edges.md'), or prefix ('ADR-003')",
    ],
) -> CallToolResult:
    """Read and parse an existing Architecture Decision Record."""
    result = adr_read_impl(name, workspace_root=ROOT)
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="")]
    return ToolOutput(
        tool_name="adr_read",
        breadcrumb="Read ADR at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def adr_search(
    query: Annotated[str, "Text to search in title, tags, and body (optional)"] = "",
    tag: Annotated[str, "Filter by exact tag match, case-insensitive (optional)"] = "",
    status: Annotated[str, "Filter by exact status match (optional)"] = "",
    limit: Annotated[int, "Maximum results to return (capped at 50)"] = 50,
) -> CallToolResult:
    """Search Architecture Decision Records by tag, status, and/or text query."""
    result = adr_search_impl(
        query=query,
        tag=tag,
        status=status,
        limit=limit,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    return ToolOutput(
        tool_name="adr_search",
        breadcrumb="Searched ADRs",
        error=error,
        metadata=result,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Architecturally Significant Requirement Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def asr_create(
    priority: Annotated[
        int,
        "Priority integer — non-negative; lower = higher importance.",
    ],
    requirement: Annotated[
        str,
        "The requirement body — scoped, measurable, technology-independent.",
    ],
    notes: Annotated[str, "Optional notes (optional)"] = "",
    status: Annotated[str, "Status: 'Active', 'Archived', or 'Superseded by ASR-NNNN'"] = "Active",
) -> CallToolResult:
    """Create a new Architecturally Significant Requirement (ASR) in artifacts/requirements/."""
    result = asr_create_impl(
        priority=priority,
        requirement=requirement,
        notes=notes,
        status=status,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="created")]
    return ToolOutput(
        tool_name="asr_create",
        breadcrumb="Created ASR at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def asr_read(
    name: Annotated[
        str,
        "ASR identifier — number ('1', '0001'), or ASR-prefixed ('ASR-0001', 'ASR-0001.md')",
    ],
) -> CallToolResult:
    """Read and parse an existing Architecturally Significant Requirement."""
    result = asr_read_impl(name, workspace_root=ROOT)
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="")]
    return ToolOutput(
        tool_name="asr_read",
        breadcrumb="Read ASR at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def asr_search(
    query: Annotated[
        str, "Text to search in requirement and notes, case-insensitive (optional)"
    ] = "",
    status: Annotated[str, "Filter by exact status match (optional)"] = "",
    priority_min: Annotated[int | None, "Minimum priority value to include (optional)"] = None,
    priority_max: Annotated[int | None, "Maximum priority value to include (optional)"] = None,
    limit: Annotated[int, "Maximum results to return (capped at 50)"] = 50,
) -> CallToolResult:
    """Search Architecturally Significant Requirements."""
    result = asr_search_impl(
        query=query,
        status=status,
        priority_min=priority_min,
        priority_max=priority_max,
        limit=limit,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    return ToolOutput(
        tool_name="asr_search",
        breadcrumb="Searched ASRs",
        error=error,
        metadata=result,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Agent Log Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def log_write(
    agent: Annotated[str, "Agent name (lowercase, hyphens, e.g., 'rnd-ddauthor')"],
    title: Annotated[str, "Entry title — concise summary of the log entry"],
    category: Annotated[
        str,
        "Category: research, decision, blocker, discovery, "
        "dead-end, implementation, or observation",
    ],
    body: Annotated[str, "Entry body text (optional)"] = "",
    tags: Annotated[list[str] | None, "Tags for categorization (optional)"] = None,
) -> CallToolResult:
    """Append an entry to an agent's log file in artifacts/logs/."""
    result = log_write_impl(
        agent=agent,
        title=title,
        category=category,
        body=body,
        tags=tags,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="modified")]
    return ToolOutput(
        tool_name="log_write",
        breadcrumb="Wrote log entry at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def log_read(
    agent: Annotated[
        str,
        "Agent name (lowercase, hyphens, e.g., 'rnd-ddauthor'). Use '*' to read across all agents.",
    ],
    category: Annotated[str, "Filter by exact category match (optional)"] = "",
    tag: Annotated[str, "Filter by tag, case-insensitive (optional)"] = "",
    title_query: Annotated[str, "Filter by case-insensitive substring in title (optional)"] = "",
    since: Annotated[
        str,
        "Only return entries at or after this time. "
        "Relative: '30m', '2h', '7d'. Absolute: ISO 8601. Empty = no lower bound.",
    ] = "",
    until: Annotated[
        str,
        "Only return entries at or before this time. Same format as since. Empty = no upper bound.",
    ] = "",
    limit: Annotated[int, "Maximum entries to return (capped at 50)"] = 50,
) -> CallToolResult:
    """Read an agent's log entries, newest-first, with optional filters."""
    result = log_read_impl(
        agent=agent,
        category=category,
        tag=tag,
        title_query=title_query,
        since=since,
        until=until,
        limit=limit,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "agent" in result and agent != "*":
        log_path = ROOT / "artifacts" / "logs" / f"{agent}.log.jsonl"
        if log_path.exists():
            file_links = [FileLink(file_path=log_path, action="")]
    return ToolOutput(
        tool_name="log_read",
        breadcrumb="Read log for",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def log_archive(
    agent: Annotated[str, "Agent name (lowercase, hyphens, e.g., 'rnd-ddauthor')"],
    ids: Annotated[
        list[str] | None,
        "Exact entry IDs to archive (e.g. ['L1', 'L5']).",
    ] = None,
    tag: Annotated[str, "Archive all entries with this tag (optional)"] = "",
    category: Annotated[str, "Archive all entries with this exact category (optional)"] = "",
    title_query: Annotated[
        str, "Archive all entries whose title contains this substring (optional)"
    ] = "",
    before: Annotated[
        str,
        "Archive entries with timestamps strictly before this time. "
        "Relative: '30m', '2h', '7d'. Absolute: ISO 8601. Empty = no lower bound.",
    ] = "",
    after: Annotated[
        str,
        "Archive entries with timestamps strictly after this time. Same format as before.",
    ] = "",
) -> CallToolResult:
    """Move matching log entries to an archive file."""
    result = log_archive_impl(
        agent=agent,
        ids=ids,
        tag=tag,
        category=category,
        title_query=title_query,
        before=before,
        after=after,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "archive_path" in result:
        file_links = [FileLink(file_path=ROOT / result["archive_path"], action="modified")]
    return ToolOutput(
        tool_name="log_archive",
        breadcrumb=f"Archived {result.get('archived', 0)} entries to",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Archive Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def plan_archive(
    plan_name: Annotated[str, "Plan name (with or without .md extension)"],
    ignore_blocked: Annotated[
        bool,
        "If True, archive despite Blocked annotations on steps",
    ] = False,
) -> CallToolResult:
    """Archive a completed task plan from pending to completed."""
    result = plan_archive_impl(
        plan_name,
        ignore_blocked=ignore_blocked,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="archived")]
    return ToolOutput(
        tool_name="plan_archive",
        breadcrumb="Archived plan at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def dd_archive(
    name: Annotated[str, "DD name — slug, filename, or DD-prefixed name"],
) -> CallToolResult:
    """Archive a design document from pending to completed."""
    result = dd_archive_impl(name, workspace_root=ROOT)
    error = _extract_tool_error(result)
    file_links = None
    if "path" in result:
        file_links = [FileLink(file_path=ROOT / result["path"], action="archived")]
    return ToolOutput(
        tool_name="dd_archive",
        breadcrumb="Archived DD at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Task Plan Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def plan_read(
    plan_name: Annotated[
        str, "Plan name (with or without .md extension), e.g., 'TASK-refactor-library'"
    ],
) -> CallToolResult:
    """Read a task plan and return structured JSON summary."""
    result = plan_read_impl(plan_name, workspace_root=ROOT)
    error = _extract_tool_error(result)
    plan_file = plan_name if plan_name.endswith(".md") else f"{plan_name}.md"
    plan_path = ROOT / "plans" / plan_file
    file_links = None
    if plan_path.exists():
        file_links = [FileLink(file_path=plan_path, action="")]
    return ToolOutput(
        tool_name="plan_read",
        breadcrumb="Read Plan at",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def plan_complete_step(
    plan_name: Annotated[str, "Plan name (with or without .md extension)"],
    step_id: Annotated[
        str, "Step ID in format P<phase>-S<step> (e.g., 'P1-S3' for Phase 1, Step 3)"
    ],
    annotation_marker: Annotated[
        str | None,
        "Annotation marker word. Requires annotation_text.",
    ] = None,
    annotation_text: Annotated[
        str | None,
        "Text to add under the step. Requires annotation_marker.",
    ] = None,
) -> CallToolResult:
    """Mark a step as complete in a task plan."""
    ann_dict = None
    if annotation_marker and annotation_text:
        ann_dict = {"marker": annotation_marker, "text": annotation_text}
    elif annotation_marker or annotation_text:
        error_message = "Both annotation_marker and annotation_text must be provided together."
        return ToolOutput(
            tool_name="plan_complete_step",
            breadcrumb="Error: incomplete annotation",
            error=error_message,
            metadata={"error": error_message},
        ).to_call_tool_result()
    result = plan_complete_step_impl(plan_name, step_id, workspace_root=ROOT, annotation=ann_dict)
    error = _extract_tool_error(result)
    plan_file = plan_name if plan_name.endswith(".md") else f"{plan_name}.md"
    plan_path = ROOT / "plans" / plan_file
    file_links = None
    if plan_path.exists():
        file_links = [FileLink(file_path=plan_path, action="")]
    parts = step_id.split("-")
    phase_num = parts[0][1:] if len(parts) >= 1 else "?"
    step_num = parts[1][1:] if len(parts) >= 2 else "?"
    breadcrumb_text = f"Completed Phase {phase_num} Step {step_num} at"
    return ToolOutput(
        tool_name="plan_complete_step",
        breadcrumb=breadcrumb_text,
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Python Introspection
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def py_introspect(
    imports: Annotated[
        list[str] | None,
        "Extra dotted imports to execute before checks (e.g. ['nomarr.services']).",
    ] = None,
    checks: Annotated[
        list[dict[str, Any]] | None,
        "Ordered list of check dicts. Each has a 'check' key "
        "(mro|issubclass|signature|doc|getsource_contains|ast_raises) "
        "plus check-specific fields.",
    ] = None,
    timeout_ms: Annotated[int, "Hard timeout for the subprocess in milliseconds (500-30000)."] = 3000,
    max_source_chars: Annotated[int, "Max characters for source-text results (100-50000)."] = 2000,
) -> CallToolResult:
    """Run whitelist-only Python introspection checks in isolated subprocess."""
    result = py_introspect_impl(
        imports=imports,
        checks=checks,
        timeout_ms=timeout_ms,
        max_source_chars=max_source_chars,
    )
    status = result.get("status", "error")
    n_checks = len(result.get("results", []))
    n_ok = sum(1 for r in result.get("results", []) if r.get("ok"))

    if status == "ok":
        summary = f"All {n_checks} check(s) passed"
    elif status == "partial":
        summary = f"{n_ok}/{n_checks} check(s) succeeded"
    else:
        errors = result.get("errors", [])
        summary = f"Error: {errors[0]}" if errors else "Unknown error"

    error = errors[0] if status == "error" and errors else None
    return ToolOutput(
        tool_name="py_introspect",
        breadcrumb=summary,
        error=error,
        metadata=result,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


def main() -> None:
    """Run the MCP server."""
    mcp.run()


if __name__ == "__main__":
    main()
