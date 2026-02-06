#!/usr/bin/env python3
"""Nomarr Coding Tools MCP Server.

Exposes code discovery tools and resources to AI agents via MCP.
All tools use static analysis and return structured JSON.

Project navigation:
- list_project_directory_tree: List directory contents with smart filtering
- list_project_routes: List all API routes by static analysis
- analyze_project_api_coverage: Check which backend endpoints are used by frontend

Python module navigation:
- read_module_api: Show public API of any nomarr module (signatures, methods, constants)
- locate_module_symbol: Find where a symbol is defined (by simple or partially qualified name)
- read_module_source: Get source code of a specific function/method/class

File operations:
- read_file_symbol_at_line: Get full function/class containing a line (for contextual error fixes)
- read_file_line_range: Read line range from any file (YAML, TS, CSS, configs, etc.)
- read_file_line: Quick error context (1 line + 2 around) for trivial fixes
- search_file_text: Find exact text in files and show 2-line context

Call tracing:
- trace_module_calls: Trace call chains from entry point through layers
- trace_project_endpoint: Resolve FastAPI DI to trace full endpoint behavior

Quality validation:
- lint_project_backend: Run ruff, mypy, and import-linter on specified path
- lint_project_frontend: Run ESLint and TypeScript type checking on frontend

Task plan tools:
- plan_read: Read a task plan as structured JSON
- plan_complete_step: Mark a step complete and get next step

File editing tools:
- edit_file_replace_string: Apply multiple string replacements atomically (single write)
- edit_file_replace_line_range: Replace line range with new content (line-anchored)
- edit_file_move_text: Move lines within a file or between files atomically
- edit_file_create: Create new files with mkdir -p behavior (atomic batch)
- edit_file_replace_content: Replace entire file contents atomically
- edit_file_insert_text: Insert text at precise positions (bof/eof/before_line/after_line)
- edit_file_copy_paste_text: Copy text from sources to targets (stamp decorator pattern)

Usage:
    python -m scripts.mcp.nomarr_mcp
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import BaseModel, Field

from .helpers.config_loader import load_config
from .helpers.mcp_output_helper import (
    format_file_link,
    format_file_range_link,
    wrap_mcp_result,
    wrap_mcp_result_with_file_link,
)
from .tools.analyze_project_api_coverage import (
    analyze_project_api_coverage as analyze_project_api_coverage_impl,
)
from .tools.edit_file_copy_paste_text import (
    edit_file_copy_paste_text as edit_file_copy_paste_text_impl,
)
from .tools.edit_file_create import edit_file_create as edit_file_create_impl
from .tools.edit_file_insert_text import edit_file_insert_text as edit_file_insert_text_impl
from .tools.edit_file_move_text import edit_file_move_text as edit_file_move_text_impl
from .tools.edit_file_replace_content import (
    edit_file_replace_content as edit_file_replace_content_impl,
)
from .tools.edit_file_replace_line_range import (
    edit_file_replace_line_range as edit_file_replace_line_range_impl,
)

# Import tool implementations with _impl suffix to avoid name collision
# with MCP-decorated wrapper functions defined below
from .tools.edit_file_replace_string import (
    edit_file_replace_string as edit_file_replace_string_impl,
)
from .tools.lint_project_backend import lint_project_backend as lint_project_backend_impl
from .tools.lint_project_frontend import lint_project_frontend as lint_project_frontend_impl
from .tools.list_project_directory_tree import (
    list_project_directory_tree as list_project_directory_tree_impl,
)
from .tools.list_project_routes import list_project_routes as list_project_routes_impl
from .tools.locate_module_symbol import locate_module_symbol as locate_module_symbol_impl
from .tools.plan_complete_step import plan_complete_step as plan_complete_step_impl
from .tools.plan_read import plan_read as plan_read_impl
from .tools.read_file_line import read_file_line as read_file_line_impl
from .tools.read_file_range import read_file_range as read_file_range_impl
from .tools.read_file_symbol_at_line import (
    read_file_symbol_at_line as read_file_symbol_at_line_impl,
)
from .tools.read_module_api import read_module_api as read_module_api_impl
from .tools.read_module_source import read_module_source as read_module_source_impl
from .tools.search_file_text import search_file_text as search_file_text_impl
from .tools.trace_module_calls import trace_module_calls as trace_module_calls_impl
from .tools.trace_project_endpoint import trace_project_endpoint as trace_project_endpoint_impl

# Tool registry for programmatic access (replaces _ToolsNamespace)
TOOL_IMPLS: dict[str, object] = {
    "edit_file_replace_string": edit_file_replace_string_impl,
    "edit_file_move_text": edit_file_move_text_impl,
    "edit_file_copy_paste_text": edit_file_copy_paste_text_impl,
    "edit_file_create": edit_file_create_impl,
    "edit_file_insert_text": edit_file_insert_text_impl,
    "read_file_line": read_file_line_impl,
    "read_file_line_range": read_file_range_impl,
    "edit_file_replace_content": edit_file_replace_content_impl,
    "edit_file_replace_line_range": edit_file_replace_line_range_impl,
    "search_file_text": search_file_text_impl,
    "read_file_symbol_at_line": read_file_symbol_at_line_impl,
    "lint_project_backend": lint_project_backend_impl,
    "lint_project_frontend": lint_project_frontend_impl,
    "read_module_api": read_module_api_impl,
    "read_module_source": read_module_source_impl,
    "locate_module_symbol": locate_module_symbol_impl,
    "plan_complete_step": plan_complete_step_impl,
    "plan_read": plan_read_impl,
    "analyze_project_api_coverage": analyze_project_api_coverage_impl,
    "list_project_directory_tree": list_project_directory_tree_impl,
    "list_project_routes": list_project_routes_impl,
    "trace_module_calls": trace_module_calls_impl,
    "trace_project_endpoint": trace_project_endpoint_impl,
}

# ──────────────────────────────────────────────────────────────────────
# Early Setup: Configure logging to stderr (NEVER stdout for MCP stdio)
# ──────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(name)s: %(message)s",
    stream=sys.stderr,  # Critical: MCP uses stdout for JSON-RPC
)

# Suppress noisy loggers that might write to handlers
for noisy_logger in ["asyncio", "urllib3", "httpcore", "httpx"]:
    logging.getLogger(noisy_logger).setLevel(logging.ERROR)

# Workspace root - determined from current working directory
# VS Code MCP starts the server with cwd set to workspace folder
ROOT = Path.cwd()


# ──────────────────────────────────────────────────────────────────────
# Configuration Validation
# ──────────────────────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


# Global config loaded at startup (can be overridden by tools via dependency injection)
_config: dict = {}


def _validate_config_on_startup() -> dict:
    """Validate MCP configuration on startup.

    Loads and validates the configuration file. Logs warnings for invalid config
    but does not block startup to allow tools to work with defaults.

    Returns:
        The loaded configuration dict, or empty dict if loading fails.
    """
    try:
        config = load_config(ROOT)
        logger.info(f"✓ Configuration loaded successfully from {ROOT}")

        # Log which configuration source was used
        config_file = ROOT / "mcp_config.json"
        if config_file.exists():
            logger.info(f"  Using project config: {config_file}")
        else:
            config_dir = ROOT / ".mcp"
            if (config_dir / "config.json").exists():
                logger.info(f"  Using MCP config: {config_dir / 'config.json'}")
            else:
                logger.info("  Using default configuration (no mcp_config.json found)")

        # Validate backend config
        backend = config.get("backend", {})
        if backend:
            logger.debug(f"  Backend framework: {backend.get('framework', 'fastapi')}")
            routes = backend.get("routes", {})
            if routes.get("decorators"):
                logger.debug(f"  Route decorators: {len(routes['decorators'])} patterns configured")

        # Validate frontend config
        frontend = config.get("frontend", {})
        if frontend:
            logger.debug(f"  Frontend framework: {frontend.get('framework', 'react')}")
            api_calls = frontend.get("api_calls", {})
            if api_calls.get("patterns"):
                logger.debug(f"  API patterns: {len(api_calls['patterns'])} patterns configured")

        # Validate tracing config
        tracing = config.get("tracing", {})
        if tracing.get("include_patterns"):
            logger.debug(f"  Tracing patterns: {tracing['include_patterns']}")

        return config

    except Exception as e:
        logger.warning(f"⚠ Configuration validation error: {type(e).__name__}: {e}")
        logger.warning("  Proceeding with default configuration")
        logger.warning("  For configuration guide, see: scripts/mcp/config_schema.json")
        return {}


# ──────────────────────────────────────────────────────────────────────
# Pydantic Models for Complex Tool Parameters
# ──────────────────────────────────────────────────────────────────────


class StepAnnotation(BaseModel):
    """Annotation to add under a completed step."""

    marker: str = Field(
        description="Alphanumeric marker word (e.g., 'Notes', 'Warning', 'Blocked')"
    )
    text: str = Field(description="Annotation text to add under the step")


# Initialize MCP server
mcp = FastMCP(
    name="nom:coding-tools",
    instructions=(
        "Provides read-only, static analysis access to the Nomarr codebase. "
        "Tool priority: project_list_dir → module_discover_api → "
        "module_locate_symbol → module_get_source → "
        "file_symbol_at_line → trace_calls/trace_endpoint. "
        "Use structured Python tools first; file_read_line/file_read_range/file_search_text are "
        "fallbacks for non-Python files or when structured tools fail. "
        "No tools execute code, modify files, or infer behavior beyond what is "
        "statically observable."
    ),
)

# Validate configuration on startup and store globally for tools
_config = _validate_config_on_startup()


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_project_directory_tree(
    folder: Annotated[
        str,
        (
            "Subfolder path relative to workspace root (empty for root). "
            "Use forward slashes: 'nomarr/services'"
        ),
    ] = "",
) -> CallToolResult:
    """List directory contents with smart filtering.

    Root call: shows only top-level files + folder tree (minimal tokens).
    Specific folder: shows files at that level.
    Excludes: .venv, node_modules, __pycache__, etc.
    """
    result = list_project_directory_tree_impl(folder, workspace_root=ROOT)
    return wrap_mcp_result(
        result,
        user_summary=f"Listed directory: {folder or 'root'}",
        tool_name="list_project_directory_tree",
    )


# ──────────────────────────────────────────────────────────────────────
# Python Code Navigation Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)


@mcp.tool()
def read_module_api(
    module_name: Annotated[str, "Fully qualified module name (e.g., 'nomarr.components.ml')"],
) -> CallToolResult:
    """Discover the entire API of any Python module."""
    result = read_module_api_impl(module_name)
    return wrap_mcp_result(
        result,
        user_summary=f"Read API for module: {module_name}",
        tool_name="read_module_api",
    )


@mcp.tool()
def read_module_source(
    qualified_name: Annotated[
        str, "Python dotted path: 'module.function' or 'module.Class.method'"
    ],
    *,
    large_context: Annotated[bool, "If True, include 10 lines context (default: 2 lines)"] = False,
) -> CallToolResult:
    """Get source code of a Python function, method, or class by import path.

    Uses static AST parsing (no code execution). Returns symbol with context lines
    plus exact symbol boundaries for precise replacements.

    Returns:
        - line/line_count: Context range (includes surrounding lines for reading)
        - symbol_start_line/symbol_end_line: Actual symbol boundaries (use for replacements)
    """
    result = read_module_source_impl(qualified_name, large_context=large_context)
    return wrap_mcp_result(
        result,
        user_summary=f"Read source: {qualified_name}",
        tool_name="read_module_source",
    )


@mcp.tool()
def read_file_symbol_at_line(
    file_path: Annotated[str, "Absolute or relative path to Python file"],
    line_number: Annotated[int, "Line number (1-indexed) from error message or trace"],
) -> CallToolResult:
    """Get full function/method/class containing a line for contextual understanding.

    Use for: NameError, TypeError, logic errors, or understanding behavior at a specific line.
    Skip for: SyntaxError, simple typos.

    Returns the innermost containing symbol so you can reason about full context.
    """
    result = read_file_symbol_at_line_impl(file_path, line_number, ROOT)
    return wrap_mcp_result_with_file_link(
        result,
        file_path=file_path,
        start_line=line_number,
        end_line=line_number,
        action="Read symbol at",
        tool_name="read_file_symbol_at_line",
    )


@mcp.tool()
def locate_module_symbol(
    symbol_name: Annotated[
        str,
        "Symbol name (simple or partially qualified): 'ApplyCalibrationResponse', "
        "'components.FolderScanPlan', 'ConfigService.get_config'",
    ],
) -> CallToolResult:
    """Find all definitions of a symbol by name across the codebase.

    Searches all Python files in configured search paths for classes, functions, or variables.
    Supports partially qualified names for scoping (e.g., 'services.ConfigService').
    """
    result = locate_module_symbol_impl(symbol_name)
    return wrap_mcp_result(
        result,
        user_summary=f"Located symbol: {symbol_name}",
        tool_name="locate_module_symbol",
    )


@mcp.tool()
def trace_module_calls(
    function: Annotated[
        str,
        (
            "Fully qualified function name "
            "(e.g., 'nomarr.services.domain.library_svc.LibraryService.start_scan')"
        ),
    ],
) -> CallToolResult:
    """Trace the call chain from a function down through the codebase.

    Shows every nomarr function it calls, recursively, with file paths and line numbers.
    """
    result = trace_module_calls_impl(function, ROOT, config=_config)
    return wrap_mcp_result(
        result,
        user_summary=f"Traced calls from: {function}",
        tool_name="trace_module_calls",
    )


@mcp.tool()
def list_project_routes() -> CallToolResult:
    """List all API routes by static analysis.

    Parses @router decorators from source files. Returns routes with method, path,
    function, file, and line.
    """
    result = list_project_routes_impl(ROOT, config=_config)
    return wrap_mcp_result(
        result,
        user_summary="Listed all API routes",
        tool_name="list_project_routes",
    )


@mcp.tool()
def trace_project_endpoint(
    endpoint: Annotated[
        str, "Fully qualified endpoint name (e.g., 'nomarr.interfaces.api.web.info_if.web_info')"
    ],
) -> CallToolResult:
    """Trace an API endpoint through FastAPI DI to service methods.

    Higher-level tool that:
    1. Finds the endpoint function
    2. Extracts Depends() injections and resolves service types
    3. Finds which methods are called on each injected service
    4. Traces the full call chain for each service method

    Use this for interface endpoints to get the complete picture without manual DI resolution.
    """
    result = trace_project_endpoint_impl(endpoint, ROOT, config=_config)
    return wrap_mcp_result(
        result,
        user_summary=f"Traced endpoint: {endpoint}",
        tool_name="trace_project_endpoint",
    )


@mcp.tool()
def analyze_project_api_coverage(
    filter_mode: Annotated[
        str | None,
        "Filter: 'used' (only used endpoints), 'unused' (only unused), or None (all)",
    ] = None,
    route_path: Annotated[
        str | None, "Specific route to check (e.g., '/api/web/libraries')"
    ] = None,
) -> CallToolResult:
    """Check which backend API endpoints are used by the frontend.

    Filter modes: 'used', 'unused', or None for all endpoints.
    """
    result = analyze_project_api_coverage_impl(
        filter_mode=filter_mode, route_path=route_path, config=_config
    )
    return wrap_mcp_result(
        result,
        user_summary="Analyzed API coverage",
        tool_name="analyze_project_api_coverage",
    )


@mcp.tool()
def lint_project_backend(
    path: Annotated[
        str | None, "Relative path to lint (e.g., 'nomarr/services'). Default: 'nomarr/'"
    ] = None,
    *,
    check_all: Annotated[
        bool,
        "If True, lint all files in path; if False, only lint modified and untracked files.",
    ] = False,
) -> CallToolResult:
    """Run backend linting tools on specified path.

    Runs ruff, mypy, and import-linter (for directories only).
    """
    result = lint_project_backend_impl(path, check_all)
    return wrap_mcp_result(
        result,
        user_summary=f"Linted backend: {path or 'nomarr/'}",
        tool_name="lint_project_backend",
    )


@mcp.tool()
def lint_project_frontend() -> CallToolResult:
    """Run frontend linting tools (ESLint and TypeScript)."""
    result = lint_project_frontend_impl()
    return wrap_mcp_result(
        result,
        user_summary="Linted frontend",
        tool_name="lint_project_frontend",
    )


@mcp.tool()
def read_file_line_range(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    start_line: Annotated[int, "Starting line number (1-indexed, inclusive)"],
    end_line: Annotated[
        int, "Ending line number (1-indexed, inclusive). Clamped to 100 lines max."
    ],
    *,
    include_imports: Annotated[
        bool,
        (
            "If True and file is Python, prepend imports block. "
            "Useful for debugging undefined symbols."
        ),
    ] = False,
) -> CallToolResult:
    """Read line range from non-Python files (YAML, TS, CSS, configs) or when Python AST
    tools cannot parse the file (syntax errors, malformed code).

    Returns requested range PLUS 2 lines of context before/after for replacement safety.
    Example: Request lines 10-20 → Returns lines 8-22 (if file has enough lines).

    Fallback tool for non-Python files. Maximum 100 lines per read (including context).
    Warns when used on Python files - prefer module_discover_api, module_get_source,
    or module_locate_symbol instead.
    """
    result = read_file_range_impl(
        file_path, start_line, end_line, ROOT, include_imports=include_imports
    )
    return wrap_mcp_result_with_file_link(
        result,
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        action="Read",
        tool_name="read_file_line_range",
    )


@mcp.tool()
def read_file_line(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    line_number: Annotated[int, "Line number to read (1-indexed)"],
    *,
    include_imports: Annotated[
        bool,
        (
            "If True and file is Python, prepend imports block. "
            "Useful for debugging undefined symbols."
        ),
    ] = False,
) -> CallToolResult:
    """Quick error context - returns target line with 2 lines before/after (5 lines total).

    Example: Request line 50 → Returns lines 48-52.
    Use file_symbol_at_line for complex errors.

    For Python files, prefer module_discover_api, module_get_source, or module_locate_symbol
    for structured navigation.
    """
    result = read_file_line_impl(file_path, line_number, ROOT, include_imports=include_imports)
    return wrap_mcp_result_with_file_link(
        result,
        file_path=file_path,
        start_line=line_number,
        end_line=line_number,
        action="Read",
        tool_name="read_file_line",
    )


@mcp.tool()
def search_file_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to search"],
    search_string: Annotated[str, "Exact text to search for (case-sensitive)"],
) -> CallToolResult:
    """Find exact text in non-Python files (configs, frontend, logs) and show 2-line context."""
    result = search_file_text_impl(file_path, search_string, ROOT)
    file_link = format_file_link(file_path, ROOT)
    return wrap_mcp_result(
        result,
        user_summary=f"Searched {file_link} for: {search_string}",
        tool_name="search_file_text",
    )


# ──────────────────────────────────────────────────────────────────────
# File Editing Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def edit_file_replace_string(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to edit"],
    replacements: Annotated[
        list[dict],
        "List of {old_string, new_string} dicts. Applied in order, each on result of previous.",
    ],
) -> CallToolResult:
    """Apply multiple string replacements atomically (single write).

    All replacements are applied in-memory before writing to disk.
    This avoids issues with auto-formatters running between edits.
    Each old_string must match exactly once (ambiguous matches are skipped).
    """
    result = edit_file_replace_string_impl(file_path, replacements, ROOT)
    file_link = format_file_link(file_path, ROOT)
    return wrap_mcp_result(
        result,
        user_summary=f"Edited {file_link}: {len(replacements)} replacements",
        tool_name="edit_file_replace_string",
    )


@mcp.tool()
def edit_file_move_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the source file"],
    source_start: Annotated[int, "First line to move (1-indexed, inclusive)"],
    source_end: Annotated[int, "Last line to move (1-indexed, inclusive)"],
    target_line: Annotated[int, "Line number to insert BEFORE (use line_count+1 to append)"],
    target_file: Annotated[
        str | None,
        "Target file for cross-file moves. If None, moves within the same file.",
    ] = None,
) -> CallToolResult:
    """Move lines within a file or between files.

    Same-file: Extracts source lines and inserts them before target_line.
    Cross-file: Removes lines from source file and inserts into target file.
    Atomic operation - each file is only written once after all changes computed.
    """
    result = edit_file_move_text_impl(
        file_path, source_start, source_end, target_line, ROOT, target_file
    )
    file_link = format_file_link(file_path, ROOT)
    return wrap_mcp_result(
        result,
        user_summary=f"Moved lines {source_start}-{source_end} in {file_link}",
        tool_name="edit_file_move_text",
    )


@mcp.tool()
def edit_file_replace_line_range(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to edit"],
    start_line: Annotated[int, "First line to replace (1-indexed, inclusive)"],
    end_line: Annotated[int, "Last line to replace (1-indexed, inclusive)"],
    new_content: Annotated[str, "New content to insert (can be multiple lines)"],
) -> CallToolResult:
    """Replace a line range with new content.

    Line-anchored replacement for deterministic edits when line numbers are known
    from prior read operations. Removes ambiguity of string matching and reduces
    blast radius compared to large block string replacements.

    Use when:
    - You just read a function with read_module_source and have exact line numbers
    - You want to rewrite a specific block without string matching
    - Formatters make string matching fragile
    Returns context showing 2 lines before/after replaced region.
    """
    result = edit_file_replace_line_range_impl(file_path, start_line, end_line, new_content, ROOT)
    file_link = format_file_range_link(file_path, start_line, end_line, ROOT)
    return wrap_mcp_result(
        result, user_summary=f"Replaced {file_link}", tool_name="edit_file_replace_line_range"
    )


# ──────────────────────────────────────────────────────────────────────
# Task Plan Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def plan_read(
    plan_name: Annotated[
        str, "Plan name (with or without .md extension), e.g., 'TASK-refactor-library'"
    ],
) -> CallToolResult:
    """Read a task plan and return structured JSON summary.

    Parses the entire plan markdown into a structured representation.
    Returns phases with steps, completion status, notes, and next step info.
    """
    result = plan_read_impl(plan_name, workspace_root=ROOT)
    return wrap_mcp_result(
        result,
        user_summary=f"Read plan: {plan_name}",
        tool_name="plan_read",
    )


@mcp.tool()
def plan_complete_step(
    plan_name: Annotated[str, "Plan name (with or without .md extension)"],
    step_id: Annotated[
        str, "Step ID in format P<phase>-S<step> (e.g., 'P1-S3' for Phase 1, Step 3)"
    ],
    annotation: Annotated[
        StepAnnotation | None,
        "Optional annotation to add under the step after marking complete.",
    ] = None,
) -> CallToolResult:
    """Mark a step as complete in a task plan.

    Idempotent: safe to call multiple times on the same step.
    Updates the plan file by checking the step's checkbox.
    Optionally adds an annotation block directly under the completed step.
    Returns the next incomplete step in the plan.
    """
    # Convert Pydantic model to dict for the implementation
    ann_dict = annotation.model_dump() if annotation else None
    result = plan_complete_step_impl(plan_name, step_id, workspace_root=ROOT, annotation=ann_dict)
    return wrap_mcp_result(
        result,
        user_summary=f"Completed step {step_id} in {plan_name}",
        tool_name="plan_complete_step",
    )


@mcp.tool()
def edit_file_create(
    files: Annotated[
        list[dict],
        "List of file dicts with 'path' (str) and 'content' (str, default=\"\")",
    ],
) -> CallToolResult:
    """Create new files atomically with automatic parent directory creation.

    Creates files in batch with mkdir -p behavior. Fails if any file exists.
    All files created or none (atomic rollback on any failure).
    Returns first 2 + last 2 lines of each created file for validation.
    """
    result = edit_file_create_impl(files, workspace_root=ROOT)
    user_summary = f"Created {len(files)} file(s)"
    return wrap_mcp_result(result, user_summary, tool_name="edit_file_create")


@mcp.tool()
def edit_file_replace_content(
    ops: Annotated[
        list[dict],
        "List of file dicts with 'path' (str) and 'content' (str)",
    ],
) -> CallToolResult:
    """Replace entire file contents atomically.

    Fails if any file doesn't exist. Overwrites entire contents.
    All files replaced or none (atomic rollback on any failure).
    Returns first 2 + last 2 lines for validation.
    """
    from .tools.edit_file_replace_content import (
        ReplaceOp,
    )
    from .tools.edit_file_replace_content import (
        edit_file_replace_content as edit_file_replace_content_impl,
    )

    parsed_ops = [ReplaceOp(**op) for op in ops]
    result = edit_file_replace_content_impl(parsed_ops, workspace_root=ROOT).model_dump(
        exclude_none=True
    )
    user_summary = f"Replaced content in {len(ops)} file(s)"
    return wrap_mcp_result(result, user_summary, tool_name="edit_file_replace_content")


@mcp.tool()
def edit_file_insert_text(
    ops: Annotated[
        list[dict],
        (
            "List of InsertOp dicts with 'path', 'content', 'at' (bof|eof|before_line|after_line), "
            "optional 'line' (int, required for before/after_line), "
            "optional 'col' (int, None=BOL, -1=EOL)"
        ),
    ],
) -> CallToolResult:
    """Insert text at specific positions without string matching.

    Supports 4 insertion modes: bof, eof, before_line, after_line.
    Line-only mode (col=None): Inserts as new lines.
    Row+col mode: Character-precise insertion.
    For same-file ops: coordinates refer to ORIGINAL state, applied bottom-to-top.
    """
    result = edit_file_insert_text_impl(ops, workspace_root=ROOT)
    user_summary = f"Inserted text in {len(ops)} location(s)"
    return wrap_mcp_result(result, user_summary, tool_name="edit_file_insert_text")


@mcp.tool()
def edit_file_copy_paste_text(
    ops: Annotated[
        list[dict],
        "List of CopyPasteOp dicts with source_path, source_start_line, source_end_line, "
        "target_path, target_line, optional source_start_col/source_end_col/target_col",
    ],
) -> CallToolResult:
    """Copy text from sources and paste to targets atomically.

    Sources read-only (cached per unique range). Targets must exist.
    Line-only mode (all col=None): Copy/paste full lines.
    Row+col mode: Character-precise copy/paste.
    For same-file targets: coordinates refer to ORIGINAL state.
    """
    result = edit_file_copy_paste_text_impl(ops, workspace_root=ROOT)
    user_summary = f"Copied and pasted text in {len(ops)} operation(s)"
    return wrap_mcp_result(result, user_summary, tool_name="edit_file_copy_paste_text")


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
