#!/usr/bin/env python3
"""
Nomarr Coding Tools MCP Server

Exposes code discovery tools to AI agents via MCP.
All tools use static analysis and return structured JSON.

Tools:
- discover_api: Show public API of any nomarr module (signatures, methods, constants)
- get_source: Get source code of a specific function/method/class
- get_symbol_body_at_line: Get source of symbol at line (one-step symbol inspection)
- locate_symbol: Find where a symbol is defined (by simple or partially qualified name)
- trace_calls: Trace call chains from entry point through layers
- trace_endpoint: Resolve FastAPI DI to trace full endpoint behavior
- list_routes: List all API routes by static analysis
- check_api_coverage: Check which backend endpoints are used by frontend
- lint_backend: Run ruff, mypy, and import-linter on specified path
- lint_frontend: Run ESLint and TypeScript type checking on frontend
- read_file: Read specific line range from any file (requires start/end lines for context management)
- read_line: Read single line with 2-line context (quick inspection for errors/search results)

Usage:
    python -m scripts.mcp.nomarr_dev_mcp
"""

import io
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Annotated

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

from mcp.server.fastmcp import FastMCP

# Initialize MCP server
mcp = FastMCP(
    "nomarr-coding-tools",
    instructions="""Tools for navigating nomarr codebase.
- discover_api: Returns module exports (classes, functions, signatures) in ~20 lines vs reading full files.
- get_source: Returns a single function/method/class with file path and line number - ideal for targeted edits.
- get_symbol_body_at_line: Get source of symbol at line (one-step symbol inspection from line number).
- locate_symbol: Find all definitions of a symbol by name (e.g., "ApplyCalibrationResponse" → file/line/length).
- list_routes: Static analysis of API routes without runtime.
- trace_calls: Follows call chains from entry points through layers.
- trace_endpoint: Resolves FastAPI DI to trace full endpoint behavior.
- check_api_coverage: Check frontend usage of backend API endpoints (used/unused/all).
- lint_backend: Run ruff, mypy, and import-linter on a specified path.
- lint_frontend: Run ESLint and TypeScript type checking on frontend.
- read_file: Read specific line range from any file (requires start/end lines for context management).
- read_line: Read single line with 2-line context (quick inspection for errors/search results).""",
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)
from scripts.mcp.check_api_coverage_ml import check_api_coverage as _check_api_coverage_impl
from scripts.mcp.discover_api_ml import discover_api as _discover_api_impl

# from scripts.mcp.find_symbol_at_line_ml import find_symbol_at_line as _find_symbol_at_line_impl  # DISABLED
from scripts.mcp.get_source_ml import get_source as _get_source_impl
from scripts.mcp.get_symbol_body_at_line_ml import get_symbol_body_at_line as _get_symbol_body_at_line_impl
from scripts.mcp.lint_backend_ml import lint_backend as _lint_backend_impl
from scripts.mcp.lint_frontend_ml import lint_frontend as _lint_frontend_impl
from scripts.mcp.list_routes_ml import list_routes as _list_routes_impl
from scripts.mcp.locate_symbol_ml import locate_symbol as _locate_symbol_impl
from scripts.mcp.read_file_ml import read_file as _read_file_impl
from scripts.mcp.read_line_ml import read_line as _read_line_impl
from scripts.mcp.trace_calls_ml import trace_calls as _trace_calls_impl
from scripts.mcp.trace_endpoint_ml import trace_endpoint as _trace_endpoint_impl


@mcp.tool()
def discover_api(
    module_name: Annotated[
        str,
        "Fully qualified module name (e.g., 'nomarr.components.ml')",
    ],
) -> dict:
    """
    Discover the public API of a nomarr module.

    Shows classes, functions, methods, and constants exported by a module.
    """
    # Run with stdout capture (in case any imports print)
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _discover_api_impl(module_name)
    except Exception as e:
        return {"module": module_name, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def get_source(
    qualified_name: Annotated[
        str,
        "Python dotted path: 'module.function' or 'module.Class.method'",
    ],
    context_lines: Annotated[
        int,
        "Lines to include before the entity (for edit context)",
    ] = 0,
) -> dict:
    """
    Get source code of a Python function, method, or class by import path.

    Returns source with file path, line number, and optional preceding context for edits.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _get_source_impl(qualified_name, context_lines=context_lines)
    except Exception as e:
        return {"name": qualified_name, "error": f"{type(e).__name__}: {e}"}


# @mcp.tool()
# def find_symbol_at_line(
#     file_path: Annotated[
#         str,
#         "Absolute or relative path to Python file",
#     ],
#     line_number: Annotated[
#         int,
#         "Line number (1-indexed) to find containing symbol for",
#     ],
# ) -> dict:
#     """
#     Find which Python symbol (function/class/method) contains a specific line number.
#
#     Returns the qualified name suitable for use with get_source().
#     Use this when you know a file and line number but need the function/method name for editing.
#
#     DISABLED: Use get_symbol_body_at_line instead - returns source in one step.
#     """
#     stdout_capture = io.StringIO()
#     stderr_capture = io.StringIO()
#
#     try:
#         with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
#             return _find_symbol_at_line_impl(file_path, line_number)
#     except Exception as e:
#         return {"file": file_path, "line": line_number, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def get_symbol_body_at_line(
    file_path: Annotated[
        str,
        "Absolute or relative path to Python file",
    ],
    line_number: Annotated[
        int,
        "Line number (1-indexed) to find containing symbol for",
    ],
) -> dict:
    """
    Get the source code of the symbol containing a specific line number.

    Convenience tool that combines find_symbol_at_line + get_source into one operation.
    Returns the innermost containing symbol (function/method/class).

    Use this when you have a line number (from error, search result, etc.) and want
    to see the full symbol containing it without two separate calls.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _get_symbol_body_at_line_impl(file_path, line_number, ROOT)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def locate_symbol(
    symbol_name: Annotated[
        str,
        "Symbol name (simple or partially qualified): 'ApplyCalibrationResponse', 'components.FolderScanPlan', 'ConfigService.get_config'",
    ],
) -> dict:
    """
    Find all definitions of a symbol by name across the codebase.

    Searches all Python files in nomarr/ for classes, functions, or variables.
    Supports partially qualified names for scoping (e.g., 'services.ConfigService').

    Returns:
    - file: Relative path from project root
    - line: Start line number
    - length: Number of lines
    - kind: Class/Function/Variable/etc
    - qualified_name: Full dotted name for use with get_source
    - warning: Present if > 5 matches (symbol too common)

    Use this when you know the symbol name but don't know where it's defined.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _locate_symbol_impl(symbol_name)
    except Exception as e:
        return {"query": symbol_name, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def trace_calls(
    function: Annotated[
        str,
        "Fully qualified function name (e.g., 'nomarr.services.domain.library_svc.LibraryService.start_scan')",
    ],
) -> dict:
    """
    Trace the call chain from a function down through the codebase.

    Shows every nomarr function it calls, recursively, with file paths and line numbers.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _trace_calls_impl(function, ROOT)
    except Exception as e:
        return {"function": function, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def list_routes() -> dict:
    """
    List all API routes by static analysis.

    Parses @router decorators from source files. Returns routes with method, path, function, file, and line.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _list_routes_impl(ROOT)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def trace_endpoint(
    endpoint: Annotated[
        str,
        "Fully qualified endpoint name (e.g., 'nomarr.interfaces.api.web.info_if.web_info')",
    ],
) -> dict:
    """
    Trace an API endpoint through FastAPI DI to service methods.

    Higher-level tool that:
    1. Finds the endpoint function
    2. Extracts Depends() injections and resolves service types
    3. Finds which methods are called on each injected service
    4. Traces the full call chain for each service method

    Use this for interface endpoints to get the complete picture without manual DI resolution.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _trace_endpoint_impl(endpoint, ROOT)
    except Exception as e:
        return {"endpoint": endpoint, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def check_api_coverage(
    filter_mode: Annotated[
        str | None,
        "Filter: 'used' (only used endpoints), 'unused' (only unused), or None (all)",
    ] = None,
    route_path: Annotated[
        str | None,
        "Specific route to check (e.g., '/api/web/libraries')",
    ] = None,
) -> dict:
    """
    Check which backend API endpoints are used by the frontend.

    Returns structured data showing:
    - Each endpoint (method + path)
    - Whether it's used in frontend code
    - Locations where it's called (file + line number)
    - Coverage statistics

    Filter modes:
    - 'used': Show only endpoints that ARE called by frontend
    - 'unused': Show only endpoints NOT called by frontend
    - None: Show all endpoints

    Example usage:
    - check_api_coverage() → All endpoints with usage status
    - check_api_coverage(filter_mode='unused') → Only unused endpoints
    - check_api_coverage(route_path='/api/web/libraries') → Check specific route
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _check_api_coverage_impl(filter_mode=filter_mode, route_path=route_path)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def lint_backend(
    path: Annotated[
        str | None,
        "Relative path to lint (e.g., 'nomarr/services', 'nomarr/workflows/scan_wf.py'). Default: 'nomarr/'",
    ] = None,
) -> dict:
    """
    Run backend linting tools on specified path.

    Runs ruff, mypy, and import-linter (for directories only).
    Returns structured JSON with errors or clean status.

    Output format (errors):
    {
      "status": "errors",
      "summary": {"total_errors": 3, "by_tool": {"ruff": 2, "mypy": 1}},
      "errors": [
        {
          "tool": "ruff",
          "file": "nomarr/services/library_svc.py",
          "line": 123,
          "column": 5,
          "code": "E501",
          "severity": "error",
          "message": "Line too long (125 > 120 characters)",
          "fix_available": true
        }
      ]
    }

    Output format (clean):
    {
      "status": "clean",
      "summary": {"tools_run": ["ruff", "mypy", "import-linter"], "files_checked": 45}
    }
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _lint_backend_impl(path)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "status": "error"}


@mcp.tool()
def lint_frontend() -> dict:
    """
    Run frontend linting tools (ESLint and TypeScript).

    Runs ESLint and tsc type checking on the frontend directory.
    Returns structured JSON with errors or clean status.

    Output format (errors):
    {
      "status": "errors",
      "summary": {"total_errors": 5, "by_tool": {"eslint": 3, "typescript": 2}},
      "errors": [
        {
          "tool": "eslint",
          "file": "frontend/src/App.tsx",
          "line": 42,
          "column": 10,
          "code": "react-hooks/exhaustive-deps",
          "severity": "warning",
          "message": "React Hook useEffect has a missing dependency",
          "fix_available": false
        }
      ]
    }

    Output format (clean):
    {
      "status": "clean",
      "summary": {"tools_run": ["eslint", "typescript"], "files_checked": 87}
    }
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _lint_frontend_impl()
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}", "status": "error"}


@mcp.tool()
def read_file(
    file_path: Annotated[
        str,
        "Workspace-relative or absolute path to the file to read",
    ],
    start_line: Annotated[
        int,
        "Starting line number (1-indexed, inclusive)",
    ],
    end_line: Annotated[
        int,
        "Ending line number (1-indexed, inclusive). Clamped to 100 lines max and file length.",
    ],
) -> dict:
    """
    Read a specific line range from any file in the workspace.

    Fallback tool for non-Python files or when AST-based tools fail.
    Returns raw file contents without parsing.

    Maximum 100 lines per read. Warns when used on Python files.

    Returns:
    - path: The resolved workspace-relative path
    - content: The requested lines as a string
    - end: Only present when clamped/EOF (e.g., "249(clamped)" or "270(EOF)")
    - warning: If lines were reversed or Python file detected
    - error: Error message if reading fails
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _read_file_impl(file_path, start_line, end_line, ROOT)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def read_line(
    file_path: Annotated[
        str,
        "Workspace-relative or absolute path to the file to read",
    ],
    line_number: Annotated[
        int,
        "Line number to read (1-indexed)",
    ],
) -> dict:
    """
    Read a single line with 2 lines of context before and after.

    Quick inspection tool for error messages, search results, and spot checks.
    For Python code analysis, prefer discover_api, get_source, or locate_symbol.

    Returns:
    - path: The resolved workspace-relative path
    - content: 5 lines (2 before, target, 2 after) or fewer at file boundaries
    - line_range: Actual range returned (e.g., "48-52" or "1-3(start)" or "268-270(EOF)")
    - warning: If Python file detected
    - error: Error message if reading fails
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _read_line_impl(file_path, line_number, ROOT)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
