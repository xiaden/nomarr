#!/usr/bin/env python3
"""
Nomarr Development MCP Server

Exposes code discovery tools to AI agents via MCP.
All tools use static analysis and return structured JSON.

Tools (5 focused tools):
- discover_api: Show public API of any nomarr module (signatures, methods, constants)
- get_source: Get source code of a specific function/method/class
- find_symbol_at_line: Find which function/class contains a given line number
- trace_calls: Trace call chains from entry point through layers
- list_routes: List all API routes by static analysis

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
    "nomarr-dev",
    instructions="""Tools for navigating nomarr codebase.
- discover_api: Returns module exports (classes, functions, signatures) in ~20 lines vs reading full files.
- get_source: Returns a single function/method/class with file path and line number - ideal for targeted edits.
- find_symbol_at_line: Find which function/class/method contains a specific line number (useful for error messages/stack traces).
- list_routes: Static analysis of API routes without runtime.
- trace_calls: Follows call chains from entry points through layers.
- trace_endpoint: Resolves FastAPI DI to trace full endpoint behavior.""",
)


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)
from scripts.mcp.discover_api_ml import discover_api as _discover_api_impl
from scripts.mcp.find_symbol_at_line_ml import find_symbol_at_line as _find_symbol_at_line_impl
from scripts.mcp.get_source_ml import get_source as _get_source_impl
from scripts.mcp.list_routes_ml import list_routes as _list_routes_impl
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


@mcp.tool()
def find_symbol_at_line(
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
    Find which Python symbol (function/class/method) contains a specific line number.

    Returns the qualified name suitable for use with get_source().
    Use this when you know a file and line number but need the function/method name for editing.
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _find_symbol_at_line_impl(file_path, line_number)
    except Exception as e:
        return {"file": file_path, "line": line_number, "error": f"{type(e).__name__}: {e}"}


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


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
