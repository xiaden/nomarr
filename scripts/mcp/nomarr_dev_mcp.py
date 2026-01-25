#!/usr/bin/env python3
"""
Nomarr Development MCP Server

Exposes code discovery tools to AI agents via MCP.
All tools use static analysis and return structured JSON.

Tools (4 focused tools):
- discover_api: Show public API of any nomarr module (signatures, methods, constants)
- get_source: Get source code of a specific function/method/class
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
mcp = FastMCP("nomarr-dev")


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)
from scripts.mcp.discover_api_ml import discover_api as _discover_api_impl
from scripts.mcp.get_source_ml import get_source as _get_source_impl
from scripts.mcp.list_routes_ml import list_routes as _list_routes_impl
from scripts.mcp.trace_calls_ml import trace_calls as _trace_calls_impl


@mcp.tool()
def discover_api(
    module_name: Annotated[
        str,
        "Fully qualified module name (e.g., 'nomarr.components.ml', 'nomarr.helpers')",
    ],
) -> dict:
    """
    Discover the public API of a nomarr module.

    Shows classes, functions, methods, and constants exported by a module.
    Use this BEFORE writing code that calls a module to understand what's available.

    PREFER THIS OVER read_file:
    - Returns ~20 lines of structured signatures vs 500+ lines of raw code
    - Shows WHAT you can call without loading implementation details
    - Use get_source() after to see specific implementations you need

    Examples:
        - discover_api("nomarr.components.ml") - See ML component exports
        - discover_api("nomarr.helpers") - See helper utilities
        - discover_api("nomarr.persistence.arango") - See DB access layer

    Returns structured JSON with:
        - module: Module name
        - classes: {name: {methods: {name: signature}, doc: str}}
        - functions: {name: {sig: str, doc: str}}
        - constants: {name: value}
        - error: Optional error message
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
        "Fully qualified name: 'module.Class.method' or 'module.function'",
    ],
) -> dict:
    """
    Get source code of a specific function, method, or class.

    Use after discover_api() when you need to see the actual implementation
    of a specific function/method/class.

    PREFER THIS OVER read_file:
    - Returns exactly ONE entity (4-50 lines) vs loading entire files (500+ lines)
    - Includes file path and line number for precise edits
    - Workflow: discover_api() -> see what exists -> get_source() -> see how it works

    Examples:
        - get_source("nomarr.persistence.db.Database.close") - Get method source
        - get_source("nomarr.helpers.time_helper.now_ms") - Get function source
        - get_source("nomarr.helpers.dto.library_dto.LibraryDict") - Get class source

    Returns structured JSON with:
        - name: The qualified name requested
        - type: "function", "method", or "class"
        - source: The source code
        - file: Source file path
        - line: Starting line number
        - line_count: Number of lines in the entity
        - error: Optional error message
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _get_source_impl(qualified_name)
    except Exception as e:
        return {"name": qualified_name, "error": f"{type(e).__name__}: {e}"}


@mcp.tool()
def trace_calls(
    function: Annotated[
        str,
        "Fully qualified function name (e.g., 'nomarr.interfaces.api.web.library_if.scan_library')",
    ],
) -> dict:
    """
    Trace the call chain from a function down through the layers.

    Starting from an entry point (like an API endpoint), shows every nomarr
    function it calls, recursively, with file paths and line numbers.

    USE THIS TO:
    - Understand what an endpoint does without reading entire files
    - Find buried methods when you know the origin call
    - Navigate from interface → service → workflow → component → persistence
    - Reduce token count vs loading multiple full files

    Examples:
        - trace_calls("nomarr.interfaces.api.web.library_if.scan_library")
        - trace_calls("nomarr.services.domain.library_svc.LibraryService.start_scan")

    Returns structured JSON with:
        - root: The starting function
        - tree: Nested call tree with file/line for each call
        - flat: Flattened list with indentation for easy reading
        - depth: Maximum call depth
        - call_count: Total unique calls traced
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

    Discovers routes without importing the FastAPI app (which hangs).
    Parses @router.get/post/etc decorators directly from source files.

    PREFER THIS for understanding the API surface:
    - Returns structured data: routes grouped by prefix
    - Includes function name, file path, and line number
    - No runtime dependencies - pure static analysis

    Returns structured JSON with:
        - routes: List of {method, path, function, file, line}
        - by_prefix: Routes grouped by 'integration', 'web', 'other'
        - total: Total route count
        - summary: Counts by prefix
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    try:
        with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
            return _list_routes_impl(ROOT)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
