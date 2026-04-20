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
- lint_project_backend: Run ruff (check + format) + mypy on modified files
  (or all with check_all=True), plus import-linter and pytest (always run)
- lint_project_frontend: Run ESLint, TypeScript type checking, and Vitest on frontend

Task plan tools:
- plan_read: Read a task plan as structured JSON
- plan_complete_step: Mark a step complete and get next step

File editing tools:
- edit_file_replace_string: Apply multiple string replacements atomically (single write)
- edit_file_replace_by_content: Replace content range by boundary text (no line numbers)
- edit_file_move: Move/rename a file within the workspace (single call)
- edit_file_move_by_content: Move text between locations using content boundaries
- edit_file_create: Create new files with mkdir -p behavior (atomic batch)
- edit_file_replace_content: Replace entire file contents atomically
- edit_file_insert_text: Insert text at precise positions (bof/eof/before_anchor/after_anchor)
- edit_file_copy_paste_text: Copy text from sources to targets (stamp decorator pattern)

Python introspection:
- py_introspect: Run whitelist-only Python introspection checks in isolated subprocess

Usage:
    python -m scripts.mcp.nomarr_mcp
"""

import logging
import sys
from pathlib import Path
from typing import Annotated, Any, Literal

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
from .tools.edit_file_create import CreateOp
from .tools.edit_file_create import edit_file_create as edit_file_create_impl
from .tools.edit_file_insert_text import InsertBoundaryOp, InsertLineOp
from .tools.edit_file_insert_text import edit_file_insert_text as edit_file_insert_text_impl
from .tools.edit_file_move import edit_file_move as edit_file_move_impl
from .tools.edit_file_move_by_content import (
    edit_file_move_by_content as edit_file_move_by_content_impl,
)
from .tools.edit_file_replace_by_content import (
    edit_file_replace_by_content as edit_file_replace_by_content_impl,
)
from .tools.edit_file_replace_content import (
    ReplaceOp,
)
from .tools.edit_file_replace_content import (
    edit_file_replace_content as edit_file_replace_content_impl,
)

# Import tool implementations with _impl suffix to avoid name collision
# with MCP-decorated wrapper functions defined below
from .tools.edit_file_replace_string import (
    ReplacementOp,
)
from .tools.edit_file_replace_string import (
    edit_file_replace_string as edit_file_replace_string_impl,
)
from .tools.lint_project_backend import lint_project_backend as lint_project_backend_impl
from .tools.lint_project_frontend import lint_project_frontend as lint_project_frontend_impl
from .tools.list_project_directory_tree import (
    list_project_directory_tree as list_project_directory_tree_impl,
)
from .tools.locate_module_symbol import locate_module_symbol as locate_module_symbol_impl
from .tools.log_read import log_read as log_read_impl
from .tools.log_write import log_write as log_write_impl
from .tools.plan_archive import plan_archive as plan_archive_impl
from .tools.plan_complete_step import plan_complete_step as plan_complete_step_impl
from .tools.plan_read import plan_read as plan_read_impl
from .tools.py_introspect import py_introspect as py_introspect_impl
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
    "log_read": log_read_impl,
    "log_write": log_write_impl,
    "plan_archive": plan_archive_impl,
    "edit_file_replace_string": edit_file_replace_string_impl,
    "edit_file_move": edit_file_move_impl,
    "edit_file_move_by_content": edit_file_move_by_content_impl,
    "edit_file_create": edit_file_create_impl,
    "edit_file_insert_text": edit_file_insert_text_impl,
    "read_file_line": read_file_line_impl,
    "read_file_line_range": read_file_range_impl,
    "edit_file_replace_content": edit_file_replace_content_impl,
    "edit_file_replace_by_content": edit_file_replace_by_content_impl,
    "search_file_text": search_file_text_impl,
    "read_file_symbol_at_line": read_file_symbol_at_line_impl,
    "lint_project_backend": lint_project_backend_impl,
    "lint_project_frontend": lint_project_frontend_impl,
    "read_module_api": read_module_api_impl,
    "read_module_source": read_module_source_impl,
    "locate_module_symbol": locate_module_symbol_impl,
    "plan_complete_step": plan_complete_step_impl,
    "plan_read": plan_read_impl,
    "list_project_directory_tree": list_project_directory_tree_impl,
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
logger.info("Workspace root: %s", ROOT)


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


# Initialize MCP server
mcp = FastMCP(
    name="coding-tools",
    instructions=(
        "Provides static analysis of files, and editing tools. "
        "Tool priority: project_list_dir → module_discover_api → "
        "module_locate_symbol → module_get_source → "
        "file_symbol_at_line → trace_calls/trace_endpoint. "
        "Use structured Python tools first; file_read_line/file_read_range/file_search_text are "
        "fallbacks for non-Python files or when structured tools fail. "
        "No tools execute code, modify files, or infer behavior beyond what is "
        "statically observable."
    ),
)


def _extract_tool_error(result: dict[str, Any]) -> str | None:
    """Extract error message from a tool result dict, if present.

    Tool impls use two patterns:
    - Artifact tools: {"error": "code", "message": "Human-readable text"}
    - Code tools: {"error": "Human-readable text"}

    Returns the human-readable message, or None if no error.
    """
    if "error" not in result:
        return None
    msg: str = result.get("message") or result["error"]
    return msg


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
    return ToolOutput(
        tool_name="list_project_directory_tree",
        breadcrumb=f"Listed directory: {folder or 'root'}",
        metadata=result,
    ).to_call_tool_result()


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
    """Get full function/method/class containing a line for contextual understanding.

    Use for: NameError, TypeError, logic errors, or understanding behavior at a specific line.
    Skip for: SyntaxError, simple typos.

    Returns the innermost containing symbol so you can reason about full context.
    """
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
    error = _extract_tool_error(result)
    matches = result.get("matches", [])
    file_links = None
    if matches:
        file_links = [
            FileLink(
                file_path=str(ROOT / m["file"]),
                start_line=m["line"],
                end_line=m.get("line") + m.get("length", 1) - 1,
                action="",
            )
            for m in matches
            if m.get("file") and m.get("line")
        ] or None
    return ToolOutput(
        tool_name="locate_module_symbol",
        breadcrumb=f"Located {symbol_name} at:",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


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
    error = _extract_tool_error(result)
    tree = result.get("tree", {})
    file_path = tree.get("file")
    line = tree.get("line")
    file_links = None
    if file_path and line:
        file_links = [
            FileLink(
                file_path=str(ROOT / file_path),
                start_line=line,
                action="",
            ),
        ]
    return ToolOutput(
        tool_name="trace_module_calls",
        breadcrumb=f"Traced calls from: {function} at:",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def trace_project_endpoint(
    endpoint: Annotated[
        str,
        "Fully qualified endpoint name (e.g., 'nomarr.interfaces.api.web.info_if.web_info')",
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
    error = _extract_tool_error(result)
    ep = result.get("endpoint", {})
    file_path = ep.get("file")
    line = ep.get("line")
    file_links = None
    if file_path and line:
        file_links = [
            FileLink(
                file_path=str(ROOT / file_path),
                start_line=line,
                action="",
            ),
        ]
    return ToolOutput(
        tool_name="trace_project_endpoint",
        breadcrumb=f"Traced endpoint: {endpoint} at:",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def lint_project_backend(
    path: Annotated[
        str | None, "Relative path to lint (e.g., 'nomarr/services'). Default: 'nomarr/'"
    ] = None,
    *,
    check_all: Annotated[
        bool,
        "If True, lint ALL files in path. "
        "If False (default), only lint git-modified and untracked files. "
        "import-linter and pytest always run regardless.",
    ] = False,
) -> CallToolResult:
    """Run backend linting tools on specified path.

    Runs ruff (check + format), mypy, import-linter, and pytest.
    Default: only git-modified/untracked files.
    With check_all=True: all files in path + import-linter contracts.
    """
    result = lint_project_backend_impl(path, check_all)
    summary = result.get("summary", {})
    is_clean = summary.get("clean", False)

    # Build file locations from errors (max 10)
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

    # Build file locations from errors (max 10)
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
    error = _extract_tool_error(result)

    # Keep warning in structured content for assistant; don't leak into user summary
    warning = result.pop("warning", None)
    if warning:
        result["_assistant_warning"] = warning

    # Extract text content for assistant
    assistant_content: list[str] = []
    requested = result.get("requested")
    if isinstance(requested, dict):
        content = requested.pop("content", None)
        if content:
            assistant_content.append(content)
    imports = result.get("imports")
    if isinstance(imports, dict):
        content = imports.pop("content", None)
        if content:
            assistant_content.append(content)

    return ToolOutput(
        tool_name="read_file_line_range",
        breadcrumb="Read",
        error=error,
        assistant_content=assistant_content or None,
        metadata=result,
        file_links=[
            FileLink(file_path=file_path, start_line=start_line, end_line=end_line, action=""),
        ],
    ).to_call_tool_result()


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
    error = _extract_tool_error(result)

    # Keep warning in structured content for assistant; don't leak into user summary
    warning = result.pop("warning", None)
    if warning:
        result["_assistant_warning"] = warning

    # Extract text content for assistant
    assistant_content: list[str] = []
    requested = result.get("requested")
    if isinstance(requested, dict):
        content = requested.pop("content", None)
        if content:
            assistant_content.append(content)
    imports = result.get("imports")
    if isinstance(imports, dict):
        content = imports.pop("content", None)
        if content:
            assistant_content.append(content)

    return ToolOutput(
        tool_name="read_file_line",
        breadcrumb="Read",
        error=error,
        assistant_content=assistant_content or None,
        metadata=result,
        file_links=[
            FileLink(file_path=file_path, start_line=line_number, end_line=line_number, action=""),
        ],
    ).to_call_tool_result()


@mcp.tool()
def search_file_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to search"],
    search_string: Annotated[str, "Exact text to search for (case-sensitive)"],
) -> CallToolResult:
    """Find exact text in non-Python files (configs, frontend, logs) and show 2-line context."""
    result = search_file_text_impl(file_path, search_string, ROOT)
    error = _extract_tool_error(result)
    matches = result.get("matches", [])

    # Extract content from each match for assistant-targeted content
    assistant_content: list[str] = []
    if matches and isinstance(result, dict) and "matches" in result:
        clean_matches = []
        for match in matches:
            if isinstance(match, dict):
                content = match.get("content")
                if content:
                    line_range = match.get("line_range", "")
                    assistant_content.append(f"Lines {line_range}:\n{content}")
                clean_match = {k: v for k, v in match.items() if k != "content"}
                clean_matches.append(clean_match)
        result["matches"] = clean_matches

    file_links = None
    if matches:
        file_links = [
            FileLink(
                file_path=file_path,
                start_line=m.get("line_number"),
                end_line=m.get("line_number"),
                action="",
            )
            for m in matches
            if m.get("line_number")
        ] or None
    match_count = len(file_links) if file_links else 0
    if match_count:
        breadcrumb = f"Found {match_count} instance(s) of '{search_string}':"
    else:
        breadcrumb = f"No matches for '{search_string}' in {file_path}"
    return ToolOutput(
        tool_name="search_file_text",
        breadcrumb=breadcrumb,
        error=error,
        assistant_content=assistant_content or None,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


# ──────────────────────────────────────────────────────────────────────
# File Editing Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def edit_file_replace_string(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to edit"],
    replacements: list[ReplacementOp],
) -> CallToolResult:
    """Apply multiple string replacements atomically (single write).

    Each replacement dict has: `old_string`, `new_string`, `expected_count`.
    All replacements are applied in-memory before writing to disk.
    Each old_string must match exactly expected_count times or the operation fails.
    """
    replacements_dicts = [rep.model_dump() for rep in replacements]
    result = edit_file_replace_string_impl(file_path, replacements_dicts, ROOT)
    total_replaced = result.get("replacements_applied", 0)

    # Build per-replacement file links from new_context line numbers
    file_links: list[FileLink] = []
    for detail in result.get("details", []):
        if detail.get("status") != "applied":
            continue
        new_context = detail.get("new_context", "")
        # Each context block separated by --- for multi-match replacements
        for block in new_context.split("\n---\n") if new_context else []:
            lines_with_nums = [ln for ln in block.splitlines() if "|" in ln]
            if lines_with_nums:
                first = int(lines_with_nums[0].split("|")[0].strip())
                last = int(lines_with_nums[-1].split("|")[0].strip())
                file_links.append(
                    FileLink(file_path=file_path, start_line=first, end_line=last, action=""),
                )

    return ToolOutput(
        tool_name="edit_file_replace_string",
        breadcrumb=f"Made {total_replaced} replacement(s):",
        metadata=result,
        file_links=file_links or None,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_move_by_content(
    file_path: Annotated[str, "Workspace-relative or absolute path to the source file"],
    start_boundary: Annotated[
        str,
        "Content marking the start of the range to move. "
        "Multi-line supported (\\n separated). Stripped substring match.",
    ],
    end_boundary: Annotated[
        str,
        "Content marking the end of the range to move. Same rules.",
    ],
    expected_line_count: Annotated[
        int,
        "Exact line count of the source range (inclusive). Safety check.",
    ],
    target_position: Annotated[
        str,
        "Insert 'before' or 'after' the target anchor line. Ignored when target_anchor is None.",
    ],
    target_anchor: Annotated[
        str | None,
        "Content line in the target file to anchor insertion. "
        "Must match exactly one line (stripped substring). "
        "Omit (None) when extracting to a new file — the moved "
        "block becomes the file content.",
    ] = None,
    target_file: Annotated[
        str | None,
        "Target file for cross-file moves. If None, moves within same file.",
    ] = None,
) -> CallToolResult:
    """Move text between locations using content boundaries, not line numbers.

    Source range is located by start/end boundary text with line count validation.
    Target is located by a content anchor line. Atomic per file.
    Fails on ambiguous matches (multiple boundary/anchor hits).

    When target_anchor is omitted (None) and target_file is set, the moved
    block becomes the entire content of a newly created file. Fails if the
    target file already exists.
    """
    result = edit_file_move_by_content_impl(
        file_path,
        start_boundary,
        end_boundary,
        expected_line_count,
        target_anchor,  # can be None
        target_position,
        ROOT,
        target_file,
    )
    return ToolOutput(
        tool_name="edit_file_move_by_content",
        breadcrumb=f"Moved content in {file_path}",
        metadata=result,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_move(
    old_path: Annotated[str, "Workspace-relative or absolute path to the source file (must exist)"],
    new_path: Annotated[
        str, "Workspace-relative or absolute path to the destination (must not exist)"
    ],
) -> CallToolResult:
    """Move or rename a file within the workspace.

    Single-call file move. Resolves both paths, creates target parent directories
    automatically, and performs the move. Fails if target already exists.
    """
    result = edit_file_move_impl(old_path, new_path, workspace_root=ROOT)
    error = result.get("error")
    file_links = None
    if not error:
        file_links = [FileLink(file_path=result["new_path"], action="")]
    return ToolOutput(
        tool_name="edit_file_move",
        breadcrumb=f"Move failed: {error}" if error else f"Moved {old_path} to",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_replace_by_content(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to edit"],
    start_boundary: Annotated[
        str,
        "Content that marks the beginning of the range to replace. "
        "Multi-line supported (separate lines with \\n). "
        "Each line is stripped and matched as a substring against file lines.",
    ],
    end_boundary: Annotated[
        str,
        "Content that marks the end of the range to replace. "
        "Same matching rules as start_boundary.",
    ],
    expected_line_count: Annotated[
        int,
        "Exact number of lines the matched range must span (inclusive of boundary lines). "
        "Acts as a safety check — the tool fails if the actual count differs.",
    ],
    new_content: Annotated[
        str,
        "Replacement text. Replaces the entire matched range including boundary lines. "
        "Include boundary text in new_content if you want to preserve it.",
    ],
) -> CallToolResult:
    """Replace a range of lines identified by content boundaries, not line numbers.

    Locates the range by finding start_boundary and end_boundary text in the file.
    Both boundaries are inclusive — they and everything between them are replaced.
    Fails if boundaries match zero or multiple ranges (ambiguity detection).
    Use expected_line_count to validate you're replacing the right amount of code.
    """
    result = edit_file_replace_by_content_impl(
        file_path, start_boundary, end_boundary, expected_line_count, new_content, ROOT
    )
    return ToolOutput(
        tool_name="edit_file_replace_by_content",
        breadcrumb=f"Replaced content range in {file_path}",
        metadata=result,
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
    """Create a new Design Document (DD) markdown file in artifacts/designs/pending/.

    Validates slug format and status. Generates structured markdown with standard sections.
    """
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
    """Read and parse an existing Design Document.

    Searches pending then completed directories. Returns structured document data.
    """
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
    """Preview an ADR without writing to disk.

    Returns the generated markdown for user review before committing.
    Validates status, tags, and required sections.
    """
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
        "If provided, all content is loaded from the staging draft file; "
        "other params become optional overrides.",
    ] = "",
    title: Annotated[str, "Title of the architecture decision (optional when draft_id given)"] = "",
    status: Annotated[
        str, "Status: Proposed, Accepted, Deprecated, or Superseded (optional when draft_id given)"
    ] = "",
    tags: Annotated[list[str], "Tags for categorization (optional when draft_id given)"] = [],  # noqa: B006  FastMCP reads this as a default annotation, not a mutable default
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
    """Write an approved ADR to disk in artifacts/decisions/.

    Primary workflow: call with draft_id after user reviews the adr_suggest output.
    The staging draft at artifacts/decisions/drafts/ is loaded, assigned a number,
    written to artifacts/decisions/, and deleted from staging.

    Fallback workflow: provide all content params explicitly (no draft required).
    Auto-numbers the ADR. Validates status, tags, and required sections.
    """
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
    """Read and parse an existing Architecture Decision Record.

    Resolves various name formats. Returns structured ADR data.
    """
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
    """Search Architecture Decision Records by tag, status, and/or text query.

    Returns results sorted by ADR number descending.
    """
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


# Architecturally Significant Requirement Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def asr_create(
    priority: Annotated[
        int,
        "Priority integer — non-negative; lower = higher importance. "
        "0 is most critical. Use multiples of 100 for new ASRs to allow insertions.",
    ],
    requirement: Annotated[
        str,
        "The requirement body — scoped, measurable, technology-independent, "
        "no implementation detail",
    ],
    notes: Annotated[
        str,
        "Optional notes — ADR references and background context only. "
        "No implementation detail. No tech names. (optional)",
    ] = "",
    status: Annotated[
        str,
        "Status: 'Active', 'Archived', or 'Superseded by ASR-NNNN'",
    ] = "Active",
) -> CallToolResult:
    """Create a new Architecturally Significant Requirement (ASR) in artifacts/requirements/.

    ASRs document the requirements that motivate architectural decisions.
    They are the 'why' behind ADRs.
    """
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
    """Read and parse an existing Architecturally Significant Requirement.

    Returns structured ASR data.
    """
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
    """Search Architecturally Significant Requirements by status, priority range, and/or text query.

    Returns results sorted by priority ascending (lowest number = highest priority first).
    """
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
    """Append an entry to an agent's log file in artifacts/logs/.

    Creates the log file on first call. Entries are append-only with auto-incrementing IDs.
    """
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
    agent: Annotated[str, "Agent name (lowercase, hyphens, e.g., 'rnd-ddauthor')"],
    category: Annotated[str, "Filter by exact category match (optional)"] = "",
    tag: Annotated[str, "Filter by tag, case-insensitive (optional)"] = "",
    title_query: Annotated[str, "Filter by case-insensitive substring in title (optional)"] = "",
    limit: Annotated[int, "Maximum entries to return (capped at 50)"] = 50,
) -> CallToolResult:
    """Read an agent's log entries, newest-first, with optional filters.

    Applies AND-combined filters for category, tag, and title query.
    """
    result = log_read_impl(
        agent=agent,
        category=category,
        tag=tag,
        title_query=title_query,
        limit=limit,
        workspace_root=ROOT,
    )
    error = _extract_tool_error(result)
    file_links = None
    if "agent" in result:
        log_path = ROOT / "artifacts" / "logs" / f"{agent}.log.md"
        if log_path.exists():
            file_links = [FileLink(file_path=log_path, action="")]
    return ToolOutput(
        tool_name="log_read",
        breadcrumb="Read log for",
        error=error,
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


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
    """Archive a completed task plan from pending to completed.

    Verifies all steps are checked complete. Warns on Blocked
    annotations unless ignore_blocked=True.
    """
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
    name: Annotated[
        str,
        "DD name — slug, filename, or DD-prefixed name",
    ],
) -> CallToolResult:
    """Archive a design document from pending to completed.

    Verifies all convention-linked plans (TASK-{slug}-*) are completed.
    Updates status to Completed before moving.
    """
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
        "Annotation marker word. Requires annotation_text, Required with annotation_text.",
    ] = None,
    annotation_text: Annotated[
        str | None,
        (
            "Text to add under the step. Requires annotation_marker, "
            "Required with annotation_marker"
            " Cannot contain bullets or step-like items."
        ),
    ] = None,
) -> CallToolResult:
    """Mark a step as complete in a task plan.

    Idempotent: safe to call multiple times on the same step.
    Updates the plan file by checking the step's checkbox.
    Optionally adds an annotation block directly under the completed step.
    Annotation text Cannot contain bullets or step-like items (e.g., ' - ', ' - [', or '1.').
    Returns the next incomplete step in the plan.
    """
    # Build annotation dict from separate parameters
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
    # Parse P<n>-S<m> into readable "Phase N Step M"
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


@mcp.tool()
def edit_file_create(
    files: list[CreateOp],
) -> CallToolResult:
    """Create new files atomically with automatic parent directory creation.

    Each file dict has: `path` (str), `content` (str, default="").
    Fails if any file exists. All created or none (atomic rollback).
    """
    files_dicts = [f.model_dump() for f in files]
    result = edit_file_create_impl(files_dicts, workspace_root=ROOT)
    applied_ops = result.get("applied_ops", [])
    file_links = [
        FileLink(
            file_path=op["filepath"],
            action="",
            line_count=op.get("end_line"),
        )
        for op in applied_ops
        if op.get("filepath")
    ] or None
    return ToolOutput(
        tool_name="edit_file_create",
        breadcrumb=f"Created {len(files)} file(s):",
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_replace_content(
    ops: list[ReplaceOp],
) -> CallToolResult:
    """Replace entire file contents atomically.

    Each op dict has: `path` (str), `content` (str).
    Fails if any file doesn't exist. All replaced or none (atomic rollback).
    """
    result = edit_file_replace_content_impl(ops, workspace_root=ROOT).model_dump(exclude_none=True)
    applied_ops = result.get("applied_ops", [])
    file_links = [
        FileLink(
            file_path=op["filepath"],
            action="",
            line_count=op.get("end_line"),
        )
        for op in applied_ops
        if op.get("filepath")
    ] or None
    return ToolOutput(
        tool_name="edit_file_replace_content",
        breadcrumb="Replaced:",
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_insert_at_boundary(
    position: Literal["bof", "eof"],
    ops: list[InsertBoundaryOp],
) -> CallToolResult:
    """Insert text at beginning or end of file(s).

    position: 'bof' (beginning of file) or 'eof' (end of file).
    Each op has: `path` (file path), `content` (text to insert).
    Content is inserted as new lines. Multiple ops are atomic.
    """
    ops_dicts = [{"path": op.path, "content": op.content, "at": position} for op in ops]
    result = edit_file_insert_text_impl(ops_dicts, workspace_root=ROOT)
    applied_ops = result.get("applied_ops", [])
    file_links = [
        FileLink(
            file_path=op["filepath"],
            start_line=op.get("start_line"),
            end_line=op.get("end_line"),
            action="",
        )
        for op in applied_ops
        if op.get("filepath")
    ] or None
    return ToolOutput(
        tool_name="edit_file_insert_at_boundary",
        breadcrumb=f"Inserted text at {position} in {len(ops)} file(s):",
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


@mcp.tool()
def edit_file_insert_at_line(
    ops: list[InsertLineOp],
) -> CallToolResult:
    """Insert text before or after a content anchor in file(s).

    Each op has: `path`, `content`, `anchor` (content substring, must match
    exactly one line), `position` ('before' or 'after').
    Content is inserted as new line(s). For same-file ops with multiple
    insertions, each anchor resolves against the current file state.
    """
    ops_dicts = [
        {
            "path": op.path,
            "content": op.content,
            "at": f"{op.position}_line",
            "anchor": op.anchor,
        }
        for op in ops
    ]
    result = edit_file_insert_text_impl(ops_dicts, workspace_root=ROOT)
    applied_ops = result.get("applied_ops", [])
    file_links = [
        FileLink(
            file_path=op["filepath"],
            start_line=op.get("start_line"),
            end_line=op.get("end_line"),
            action="",
        )
        for op in applied_ops
        if op.get("filepath")
    ] or None
    return ToolOutput(
        tool_name="edit_file_insert_at_line",
        breadcrumb=f"Inserted text at {len(ops)} anchor location(s):",
        metadata=result,
        file_links=file_links,
    ).to_call_tool_result()


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
    timeout_ms: Annotated[
        int,
        "Hard timeout for the subprocess in milliseconds (500-30000).",
    ] = 3000,
    max_source_chars: Annotated[
        int,
        "Max characters for source-text results like doc/getsource (100-50000).",
    ] = 2000,
) -> CallToolResult:
    """Run whitelist-only Python introspection checks in isolated subprocess.

    Check types: `mro`, `issubclass`, `signature`, `doc`, `getsource_contains`, `ast_raises`.
    Each check resolves a dotted import path and returns structured results.
    """
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
