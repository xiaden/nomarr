#!/usr/bin/env python3
"""Nomarr Coding Tools MCP Server.

Exposes code discovery tools and resources to AI agents via MCP.
All tools use static analysis and return structured JSON.

File system:
- list_dir: List directory contents with smart filtering

Python code navigation:
- discover_api: Show public API of any nomarr module (signatures, methods, constants)
- locate_symbol: Find where a symbol is defined (by simple or partially qualified name)
- get_source: Get source code of a specific function/method/class
- symbol_at_line: Get full function/class containing a line (for contextual error fixes)
- trace_calls: Trace call chains from entry point through layers
- trace_endpoint: Resolve FastAPI DI to trace full endpoint behavior

Nomarr-specific tools:
- list_routes: List all API routes by static analysis
- check_api_coverage: Check which backend endpoints are used by frontend
- lint_backend: Run ruff, mypy, and import-linter on specified path
- lint_frontend: Run ESLint and TypeScript type checking on frontend

Fallback utilities:
- search_text: Find exact text in files and show 2-line context
- read_line: Quick error context (1 line + 2 around) for trivial fixes
- read_file: Read line range from any file (YAML, TS, CSS, configs, etc.)

Usage:
    python -m scripts.mcp.nomarr_mcp
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from scripts.mcp import tools

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

# Project root (parent of scripts/)
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


# Initialize MCP server
mcp = FastMCP(
    name="nom:coding-tools",
    instructions=(
        "Provides read-only, static analysis access to the Nomarr codebase. "
        "Tool priority: list_dir → discover_api → locate_symbol → get_source → symbol_at_line → trace_calls/trace_endpoint. "
        "Use structured Python tools first; read_line/read_file/search_text are fallbacks for non-Python files or when structured tools fail. "
        "No tools execute code, modify files, or infer behavior beyond what is statically observable."
    ),
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def list_dir(
    folder: Annotated[
        str, "Subfolder path relative to workspace root (empty for root). Use forward slashes: 'nomarr/services'"
    ] = "",
) -> dict:
    """List directory contents with smart filtering.

    Root call: shows only top-level files + folder tree (minimal tokens).
    Specific folder: shows files at that level.
    Excludes: .venv, node_modules, __pycache__, etc.
    """
    return tools.list_dir(folder, workspace_root=ROOT)


# ──────────────────────────────────────────────────────────────────────
# Python Code Navigation Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)


@mcp.tool()
def discover_api(module_name: Annotated[str, "Fully qualified module name (e.g., 'nomarr.components.ml')"]) -> dict:
    """Discover the entire API of any Python module."""
    return tools.discover_api(module_name)


@mcp.tool()
def get_source(
    qualified_name: Annotated[str, "Python dotted path: 'module.function' or 'module.Class.method'"],
    context_lines: Annotated[int, "Lines to include before the entity (for edit context)"] = 0,
) -> dict:
    """Get source code of a Python function, method, or class by import path.

    Returns source with file path, line number, and optional preceding context for edits.
    """
    return tools.get_source(qualified_name, context_lines=context_lines)


@mcp.tool()
def symbol_at_line(
    file_path: Annotated[str, "Absolute or relative path to Python file"],
    line_number: Annotated[int, "Line number (1-indexed) from error message or trace"],
) -> dict:
    """Get full function/method/class containing a line for contextual understanding.

    Use for: NameError, TypeError, logic errors, or understanding behavior at a specific line.
    Skip for: SyntaxError, simple typos.

    Returns the innermost containing symbol so you can reason about full context.
    """
    return tools.symbol_at_line(file_path, line_number, ROOT)


@mcp.tool()
def locate_symbol(
    symbol_name: Annotated[
        str,
        "Symbol name (simple or partially qualified): 'ApplyCalibrationResponse', 'components.FolderScanPlan', 'ConfigService.get_config'",
    ],
) -> dict:
    """Find all definitions of a symbol by name across the codebase.

    Searches all Python files in nomarr/ for classes, functions, or variables.
    Supports partially qualified names for scoping (e.g., 'services.ConfigService').
    """
    return tools.locate_symbol(symbol_name)


@mcp.tool()
def trace_calls(
    function: Annotated[
        str, "Fully qualified function name (e.g., 'nomarr.services.domain.library_svc.LibraryService.start_scan')"
    ],
) -> dict:
    """Trace the call chain from a function down through the codebase.

    Shows every nomarr function it calls, recursively, with file paths and line numbers.
    """
    return tools.trace_calls(function, ROOT)


@mcp.tool()
def list_routes() -> dict:
    """List all API routes by static analysis.

    Parses @router decorators from source files. Returns routes with method, path, function, file, and line.
    """
    return tools.list_routes(ROOT)


@mcp.tool()
def trace_endpoint(
    endpoint: Annotated[str, "Fully qualified endpoint name (e.g., 'nomarr.interfaces.api.web.info_if.web_info')"],
) -> dict:
    """Trace an API endpoint through FastAPI DI to service methods.

    Higher-level tool that:
    1. Finds the endpoint function
    2. Extracts Depends() injections and resolves service types
    3. Finds which methods are called on each injected service
    4. Traces the full call chain for each service method

    Use this for interface endpoints to get the complete picture without manual DI resolution.
    """
    return tools.trace_endpoint(endpoint, ROOT)


@mcp.tool()
def check_api_coverage(
    filter_mode: Annotated[
        str | None, "Filter: 'used' (only used endpoints), 'unused' (only unused), or None (all)"
    ] = None,
    route_path: Annotated[str | None, "Specific route to check (e.g., '/api/web/libraries')"] = None,
) -> dict:
    """Check which backend API endpoints are used by the frontend.

    Filter modes: 'used', 'unused', or None for all endpoints.
    """
    return tools.check_api_coverage(filter_mode=filter_mode, route_path=route_path)


@mcp.tool()
def lint_backend(
    path: Annotated[
        str | None, "Relative path to lint (e.g., 'nomarr/services', 'nomarr/workflows/scan_wf.py'). Default: 'nomarr/'"
    ] = None,
) -> dict:
    """Run backend linting tools on specified path.

    Runs ruff, mypy, and import-linter (for directories only).
    """
    return tools.lint_backend(path)


@mcp.tool()
def lint_frontend() -> dict:
    """Run frontend linting tools (ESLint and TypeScript)."""
    return tools.lint_frontend()


@mcp.tool()
def read_file(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    start_line: Annotated[int, "Starting line number (1-indexed, inclusive)"],
    end_line: Annotated[int, "Ending line number (1-indexed, inclusive). Clamped to 100 lines max and file length."],
) -> dict:
    """Read line range from non-Python files (YAML, TS, CSS, configs) or when Python tools return 'too large'.

    Fallback tool for non-Python files. Maximum 100 lines per read.
    Warns when used on Python files - prefer discover_api, get_source, or locate_symbol instead.
    """
    return tools.read_file(file_path, start_line, end_line, ROOT)


@mcp.tool()
def read_line(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    line_number: Annotated[int, "Line number to read (1-indexed)"],
) -> dict:
    """Quick error context (1 line + 2 around) for trivial fixes. Use symbol_at_line for complex errors.

    For Python files, prefer discover_api, get_source, or locate_symbol for structured navigation.
    """
    return tools.read_line(file_path, line_number, ROOT)


@mcp.tool()
def search_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to search"],
    search_string: Annotated[str, "Exact text to search for (case-sensitive)"],
) -> dict:
    """Find exact text in non-Python files (configs, frontend, logs) and show 2-line context."""
    return tools.search_text(file_path, search_string, ROOT)


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
