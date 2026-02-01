#!/usr/bin/env python3
"""Nomarr Coding Tools MCP Server.

Exposes code discovery tools and resources to AI agents via MCP.
All tools use static analysis and return structured JSON.

Project navigation:
- project_list_dir: List directory contents with smart filtering
- project_list_routes: List all API routes by static analysis
- project_check_api_coverage: Check which backend endpoints are used by frontend

Python module navigation:
- module_discover_api: Show public API of any nomarr module (signatures, methods, constants)
- module_locate_symbol: Find where a symbol is defined (by simple or partially qualified name)
- module_get_source: Get source code of a specific function/method/class

File operations:
- file_symbol_at_line: Get full function/class containing a line (for contextual error fixes)
- file_read_range: Read line range from any file (YAML, TS, CSS, configs, etc.)
- file_read_line: Quick error context (1 line + 2 around) for trivial fixes
- file_search_text: Find exact text in files and show 2-line context

Call tracing:
- trace_calls: Trace call chains from entry point through layers
- trace_endpoint: Resolve FastAPI DI to trace full endpoint behavior

Quality validation:
- lint_backend: Run ruff, mypy, and import-linter on specified path
- lint_frontend: Run ESLint and TypeScript type checking on frontend

Task plan tools:
- plan_read: Read a task plan as structured JSON
- plan_complete_step: Mark a step complete and get next step

File editing tools:
- edit_atomic_replace: Apply multiple string replacements atomically (single write)
- edit_move_text: Move lines within a file or between files atomically

Usage:
    python -m scripts.mcp.nomarr_mcp
"""

import logging
import sys
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, Field

# Import tool implementations with _impl suffix to avoid name collision
# with MCP-decorated wrapper functions defined below
from .edit_atomic_replace import edit_atomic_replace as edit_atomic_replace_impl
from .edit_move_text import edit_move_text as edit_move_text_impl
from .file_read_line import file_read_line as file_read_line_impl
from .file_read_range import file_read_range as file_read_range_impl
from .file_search_text import file_search_text as file_search_text_impl
from .file_symbol_at_line import file_symbol_at_line as file_symbol_at_line_impl
from .helpers.config_loader import load_config
from .lint_backend import lint_backend as lint_backend_impl
from .lint_frontend import lint_frontend as lint_frontend_impl
from .module_discover_api import module_discover_api as module_discover_api_impl
from .module_get_source import module_get_source as module_get_source_impl
from .module_locate_symbol import module_locate_symbol as module_locate_symbol_impl
from .plan_complete_step import plan_complete_step as plan_complete_step_impl
from .plan_read import plan_read as plan_read_impl
from .project_check_api_coverage import (
    project_check_api_coverage as project_check_api_coverage_impl,
)
from .project_list_dir import project_list_dir as project_list_dir_impl
from .project_list_routes import project_list_routes as project_list_routes_impl
from .trace_calls import trace_calls as trace_calls_impl
from .trace_endpoint import trace_endpoint as trace_endpoint_impl

# Tool registry for programmatic access (replaces _ToolsNamespace)
TOOL_IMPLS: dict[str, object] = {
    "edit_atomic_replace": edit_atomic_replace_impl,
    "edit_move_text": edit_move_text_impl,
    "file_read_line": file_read_line_impl,
    "file_read_range": file_read_range_impl,
    "file_search_text": file_search_text_impl,
    "file_symbol_at_line": file_symbol_at_line_impl,
    "lint_backend": lint_backend_impl,
    "lint_frontend": lint_frontend_impl,
    "module_discover_api": module_discover_api_impl,
    "module_get_source": module_get_source_impl,
    "module_locate_symbol": module_locate_symbol_impl,
    "plan_complete_step": plan_complete_step_impl,
    "plan_read": plan_read_impl,
    "project_check_api_coverage": project_check_api_coverage_impl,
    "project_list_dir": project_list_dir_impl,
    "project_list_routes": project_list_routes_impl,
    "trace_calls": trace_calls_impl,
    "trace_endpoint": trace_endpoint_impl,
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

# Project root (parent of scripts/)
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))


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
        "Tool priority: project_list_dir → module_discover_api → module_locate_symbol → module_get_source → "
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
def project_list_dir(
    folder: Annotated[
        str,
        "Subfolder path relative to workspace root (empty for root). Useforward slashes: 'nomarr/services'",
    ] = "",
) -> dict:
    """List directory contents with smart filtering.

    Root call: shows only top-level files + folder tree (minimal tokens).
    Specific folder: shows files at that level.
    Excludes: .venv, node_modules, __pycache__, etc.
    """
    return project_list_dir_impl(folder, workspace_root=ROOT)


# ──────────────────────────────────────────────────────────────────────
# Python Code Navigation Tools
# ──────────────────────────────────────────────────────────────────────

# Import ML-optimized tools (self-contained, no dependency on human scripts)


@mcp.tool()
def module_discover_api(
    module_name: Annotated[str, "Fully qualified module name (e.g., 'nomarr.components.ml')"],
) -> dict:
    """Discover the entire API of any Python module."""
    return module_discover_api_impl(module_name)


@mcp.tool()
def module_get_source(
    qualified_name: Annotated[
        str, "Python dotted path: 'module.function' or 'module.Class.method'"
    ],
    *,
    large_context: Annotated[bool, "If True, include 10 lines context (default: 2 lines)"] = False,
) -> dict:
    """Get source code of a Python function, method, or class by import path.

    Uses static AST parsing (no code execution). Always includes 2 lines of context
    before/after for edit operations. Set large_context=True for 10 lines.
    """
    return module_get_source_impl(qualified_name, large_context=large_context)


@mcp.tool()
def file_symbol_at_line(
    file_path: Annotated[str, "Absolute or relative path to Python file"],
    line_number: Annotated[int, "Line number (1-indexed) from error message or trace"],
) -> dict:
    """Get full function/method/class containing a line for contextual understanding.

    Use for: NameError, TypeError, logic errors, or understanding behavior at a specific line.
    Skip for: SyntaxError, simple typos.

    Returns the innermost containing symbol so you can reason about full context.
    """
    return file_symbol_at_line_impl(file_path, line_number, ROOT)


@mcp.tool()
def module_locate_symbol(
    symbol_name: Annotated[
        str,
        "Symbol name (simple or partially qualified): 'ApplyCalibrationResponse', "
        "'components.FolderScanPlan', 'ConfigService.get_config'",
    ],
) -> dict:
    """Find all definitions of a symbol by name across the codebase.

    Searches all Python files in nomarr/ for classes, functions, or variables.
    Supports partially qualified names for scoping (e.g., 'services.ConfigService').
    """
    return module_locate_symbol_impl(symbol_name)


@mcp.tool()
def trace_calls(
    function: Annotated[
        str,
        "Fully qualified function name (e.g., 'nomarr.services.domain.library_svc.LibraryService.start_scan')",
    ],
) -> dict:
    """Trace the call chain from a function down through the codebase.

    Shows every nomarr function it calls, recursively, with file paths and line numbers.
    """
    return trace_calls_impl(function, ROOT, config=_config)


@mcp.tool()
def project_list_routes() -> dict:
    """List all API routes by static analysis.

    Parses @router decorators from source files. Returns routes with method, path, function, file, and line.
    """
    return project_list_routes_impl(ROOT, config=_config)


@mcp.tool()
def trace_endpoint(
    endpoint: Annotated[
        str, "Fully qualified endpoint name (e.g., 'nomarr.interfaces.api.web.info_if.web_info')"
    ],
) -> dict:
    """Trace an API endpoint through FastAPI DI to service methods.

    Higher-level tool that:
    1. Finds the endpoint function
    2. Extracts Depends() injections and resolves service types
    3. Finds which methods are called on each injected service
    4. Traces the full call chain for each service method

    Use this for interface endpoints to get the complete picture without manual DI resolution.
    """
    return trace_endpoint_impl(endpoint, ROOT, config=_config)


@mcp.tool()
def project_check_api_coverage(
    filter_mode: Annotated[
        str | None,
        "Filter: 'used' (only used endpoints), 'unused' (only unused), or None (all)",
    ] = None,
    route_path: Annotated[
        str | None, "Specific route to check (e.g., '/api/web/libraries')"
    ] = None,
) -> dict:
    """Check which backend API endpoints are used by the frontend.

    Filter modes: 'used', 'unused', or None for all endpoints.
    """
    return project_check_api_coverage_impl(
        filter_mode=filter_mode, route_path=route_path, config=_config
    )


@mcp.tool()
def lint_backend(
    path: Annotated[
        str | None, "Relative path to lint (e.g., 'nomarr/services'). Default: 'nomarr/'"
    ] = None,
    *,
    check_all: Annotated[
        bool,
        "If True, lint all files in path; if False, only lint modified files (git diff).",
    ] = False,
) -> dict:
    """Run backend linting tools on specified path.

    Runs ruff, mypy, and import-linter (for directories only).
    """
    return lint_backend_impl(path, check_all)


@mcp.tool()
def lint_frontend() -> dict:
    """Run frontend linting tools (ESLint and TypeScript)."""
    return lint_frontend_impl()


@mcp.tool()
def file_read_range(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    start_line: Annotated[int, "Starting line number (1-indexed, inclusive)"],
    end_line: Annotated[
        int, "Ending line number (1-indexed, inclusive). Clamped to 100 lines max."
    ],
    *,
    include_imports: Annotated[
        bool,
        "If True and file is Python, prepend imports block. Useful for debugging undefined symbols.",
    ] = False,
) -> dict:
    """Read line range from non-Python files (YAML, TS, CSS, configs) or when Python tools return 'too large'.

    Fallback tool for non-Python files. Maximum 100 lines per read.
    Warns when used on Python files - prefer module_discover_api, module_get_source, or module_locate_symbol instead.
    """
    return file_read_range_impl(
        file_path, start_line, end_line, ROOT, include_imports=include_imports
    )


@mcp.tool()
def file_read_line(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to read"],
    line_number: Annotated[int, "Line number to read (1-indexed)"],
    *,
    include_imports: Annotated[
        bool,
        "If True and file is Python, prepend imports block. Useful for debugging undefined symbols.",
    ] = False,
) -> dict:
    """Quick error context (1 line + 2 around) for trivial fixes. Use file_symbol_at_line for complex errors.

    For Python files, prefer module_discover_api, module_get_source, or module_locate_symbol for structured navigation.
    """
    return file_read_line_impl(file_path, line_number, ROOT, include_imports=include_imports)


@mcp.tool()
def file_search_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to search"],
    search_string: Annotated[str, "Exact text to search for (case-sensitive)"],
) -> dict:
    """Find exact text in non-Python files (configs, frontend, logs) and show 2-line context."""
    return file_search_text_impl(file_path, search_string, ROOT)


# ──────────────────────────────────────────────────────────────────────
# File Editing Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def edit_atomic_replace(
    file_path: Annotated[str, "Workspace-relative or absolute path to the file to edit"],
    replacements: Annotated[
        list[dict],
        "List of {old_string, new_string} dicts. Applied in order, each on result of previous.",
    ],
) -> dict:
    """Apply multiple string replacements atomically (single write).

    All replacements are applied in-memory before writing to disk.
    This avoids issues with auto-formatters running between edits.
    Each old_string must match exactly once (ambiguous matches are skipped).
    """
    return edit_atomic_replace_impl(file_path, replacements, ROOT)


@mcp.tool()
def edit_move_text(
    file_path: Annotated[str, "Workspace-relative or absolute path to the source file"],
    source_start: Annotated[int, "First line to move (1-indexed, inclusive)"],
    source_end: Annotated[int, "Last line to move (1-indexed, inclusive)"],
    target_line: Annotated[int, "Line number to insert BEFORE (use line_count+1 to append)"],
    target_file: Annotated[
        str | None,
        "Target file for cross-file moves. If None, moves within the same file.",
    ] = None,
) -> dict:
    """Move lines within a file or between files.

    Same-file: Extracts source lines and inserts them before target_line.
    Cross-file: Removes lines from source file and inserts into target file.
    Atomic operation - each file is only written once after all changes computed.
    """
    return edit_move_text_impl(file_path, source_start, source_end, target_line, ROOT, target_file)


# ──────────────────────────────────────────────────────────────────────
# Task Plan Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def plan_read(
    plan_name: Annotated[
        str, "Plan name (with or without .md extension), e.g., 'TASK-refactor-library'"
    ],
) -> dict:
    """Read a task plan and return structured JSON summary.

    Parses the entire plan markdown into a structured representation.
    Returns phases with steps, completion status, notes, and next step info.
    """
    return plan_read_impl(plan_name, workspace_root=ROOT)


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
) -> dict:
    """Mark a step as complete in a task plan.

    Idempotent: safe to call multiple times on the same step.
    Updates the plan file by checking the step's checkbox.
    Optionally adds an annotation block directly under the completed step.
    Returns the next incomplete step in the plan.
    """
    # Convert Pydantic model to dict for the implementation
    ann_dict = annotation.model_dump() if annotation else None
    return plan_complete_step_impl(plan_name, step_id, workspace_root=ROOT, annotation=ann_dict)


def main() -> None:
    """Run the MCP server."""
    mcp.run()


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
