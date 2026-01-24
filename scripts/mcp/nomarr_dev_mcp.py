#!/usr/bin/env python3
"""
Nomarr Development MCP Server

Exposes code discovery and quality analysis tools to AI agents via MCP.
Imports script functions directly to avoid subprocess issues with stdio.

Tools:
- discover_api: Show public API of any nomarr module
- discover_import_chains: Trace import chains and detect architecture violations
- check_naming: Check naming convention violations
- check_time_usage: Verify correct wall-clock vs monotonic time usage
- list_routes: List all API routes
- classify_dataclasses: Classify dataclasses by architecture rules
- run_qc: Run full QC suite

Usage:
    python -m scripts.mcp.nomarr_dev_mcp
"""

import io
import logging
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Annotated, Callable, TypeVar

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
# Stdout Capture Helper
# ──────────────────────────────────────────────────────────────────────
T = TypeVar("T")


def capture_stdout(fn: Callable[[], T]) -> tuple[T, str]:
    """
    Execute a callable while capturing stdout/stderr.

    MCP stdio transport uses stdout for JSON-RPC protocol.
    Any print() or logging to stdout from tool implementations
    corrupts the protocol and causes clients to hang.

    Returns:
        Tuple of (result, captured_output)
    """
    stdout_capture = io.StringIO()
    stderr_capture = io.StringIO()

    with redirect_stdout(stdout_capture), redirect_stderr(stderr_capture):
        result = fn()

    # Combine captured output (stderr is less critical but still capture)
    captured = stdout_capture.getvalue()
    if stderr_capture.getvalue():
        captured += f"\n[stderr]: {stderr_capture.getvalue()}"

    return result, captured.strip()


def run_tool(fn: Callable[[], str]) -> str:
    """
    Run a tool function with stdout capture.

    If the tool or any code it calls prints to stdout,
    the output is captured and prepended to the result
    instead of corrupting the MCP protocol.
    """
    # Flush any pending output before we start
    sys.stdout.flush()
    sys.stderr.flush()

    try:
        result, captured = capture_stdout(fn)

        if captured:
            # Prepend warning about captured output
            return f"[captured stdout/stderr]:\n{captured}\n\n---\n\n{result}"
        return result
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"
    finally:
        # Ensure nothing is left in buffers
        sys.stdout.flush()
        sys.stderr.flush()


# ──────────────────────────────────────────────────────────────────────
# Tools
# ──────────────────────────────────────────────────────────────────────


@mcp.tool()
def discover_api(
    module_name: Annotated[
        str,
        "Fully qualified module name (e.g., 'nomarr.components.ml', 'nomarr.helpers')",
    ],
) -> str:
    """
    Discover the public API of a nomarr module.

    Shows classes, functions, methods, and constants exported by a module.
    Use this BEFORE writing code that calls a module to understand what's available.

    Examples:
        - discover_api("nomarr.components.ml") - See ML component exports
        - discover_api("nomarr.helpers") - See helper utilities
        - discover_api("nomarr.persistence.arango") - See DB access layer
    """

    def _impl() -> str:
        from scripts.discover_api import discover_module_api

        api = discover_module_api(module_name)

        # Format output (replicating print_api logic without print)
        lines = []
        lines.append("=" * 80)
        lines.append(f"Module: {module_name}")
        lines.append("=" * 80)
        lines.append("")

        # Error handling
        if api.get("error"):
            lines.append(f"ERROR: {api['error']}")
            return "\n".join(lines)

        # Constants
        if api.get("constants"):
            lines.append("CONSTANTS:\n")
            for name, value in sorted(api["constants"].items()):
                lines.append(f"  {name} = {value}")
            lines.append("")

        # Classes
        if api.get("classes"):
            lines.append("CLASSES:\n")
            for class_name, class_info in sorted(api["classes"].items()):
                lines.append(f"  class {class_name}:")
                doc = class_info.get("doc", "").split("\n")[0][:60]
                if doc:
                    lines.append(f"    {doc}")
                methods = class_info.get("methods", {})
                if methods:
                    lines.append(f"\n    Methods ({len(methods)}):")
                    for method_name, sig in sorted(methods.items()):
                        lines.append(f"      • {method_name}{sig}")
                lines.append("")

        # Functions
        if api.get("functions"):
            lines.append("FUNCTIONS:\n")
            for func_name, func_info in sorted(api["functions"].items()):
                sig = func_info.get("signature", "(...)")
                lines.append(f"  def {func_name}{sig}:")
                doc = func_info.get("doc", "").split("\n")[0][:60]
                if doc:
                    lines.append(f"      {doc}")
                lines.append("")

        return "\n".join(lines) if lines else "(empty module)"

    return run_tool(_impl)


@mcp.tool()
def discover_import_chains(
    module: Annotated[
        str,
        "Module name or file path (e.g., 'nomarr.services.queue' or 'nomarr/services/queue.py')",
    ],
) -> str:
    """
    Trace import chains and detect architecture violations.

    Shows which modules a target imports, transitively, and flags any
    layer violations according to the architecture rules:
    - interfaces -> services -> workflows -> components -> persistence/helpers
    - Workflows must not import services or interfaces
    - Helpers must not import any nomarr.* modules

    Use this to understand module dependencies and catch forbidden imports.

    Examples:
        - discover_import_chains("nomarr.services.queue") - See service deps
        - discover_import_chains("nomarr/workflows/analysis_wf.py") - Check workflow
    """

    def _impl() -> str:
        from scripts.discover_import_chains import (
            discover_import_chains as _discover,
        )
        from scripts.discover_import_chains import (
            format_text_output,
            resolve_input_to_module,
        )

        # Resolve input (could be module name or file path)
        root_module = resolve_input_to_module(module, ROOT)
        if not root_module:
            return f"ERROR: Could not resolve '{module}' to a module"

        result = _discover(root_module, ROOT)
        return format_text_output(root_module, result)

    return run_tool(_impl)


@mcp.tool()
def check_naming(
    path: Annotated[
        str | None,
        "Path to check. Defaults to nomarr/ directory.",
    ] = None,
) -> str:
    """
    Check for naming convention violations in Python code.

    Detects anti-patterns like:
    - Forbidden prefixes/suffixes (e.g., 'utils_', '_helper')
    - Inconsistent naming styles
    - Violations of project naming rules

    Rules are defined in scripts/configs/naming_rules.yaml.
    """

    def _impl() -> str:
        from scripts.check_naming import check_file, find_python_files, load_naming_rules

        target_path = Path(path).resolve() if path else ROOT / "nomarr"
        config_path = ROOT / "scripts" / "configs" / "naming_rules.yaml"

        config = load_naming_rules(config_path)
        rules = config.get("rules", [])
        exclude_prefixes = config.get("exclude", [])
        exclude_extensions = config.get("exclude_extensions", [])

        py_files = find_python_files(target_path, exclude_prefixes, exclude_extensions)

        all_violations = []
        for py_file in py_files:
            violations = check_file(py_file, rules, exclude_prefixes, exclude_extensions)
            all_violations.extend(violations)

        # Format output
        lines = []
        if not all_violations:
            lines.append("✓ No naming violations found")
        else:
            lines.append(f"Found {len(all_violations)} naming violation(s):\n")
            for v in all_violations:
                lines.append(f"  {v['file']}:{v['line']}")
                lines.append(f"    Pattern: {v['pattern']}")
                lines.append(f"    Text: {v['text']}")
                lines.append(f"    Fix: {v['fix']}")
                lines.append("")

        return "\n".join(lines)

    return run_tool(_impl)


@mcp.tool()
def check_time_usage(
    paths: Annotated[
        list[str] | None,
        "Paths to check. Defaults to nomarr/ directory.",
    ] = None,
) -> str:
    """
    Check for correct wall-clock vs monotonic time usage.

    Detects common mistakes:
    - Using time.time() for measuring durations (should use time.monotonic())
    - Using time.monotonic() for timestamps (should use time.time())

    Performance measurements must use monotonic time to avoid clock skew.
    """

    def _impl() -> str:
        from scripts.check_time_usage import check_path, format_text

        target_paths = [Path(p) for p in paths] if paths else [ROOT / "nomarr"]

        all_results = []
        for p in target_paths:
            all_results.extend(check_path(p))

        return format_text(all_results)

    return run_tool(_impl)


@mcp.tool()
def list_routes() -> str:
    """
    List all registered API routes in the application.

    Shows HTTP method, path, and handler function for each route.
    Use this to understand the API surface and find endpoints.

    NOTE: This tool requires running the app context and may not work
    in the MCP server. Use `python scripts/list_routes.py` directly instead.
    """
    # api_app import hangs in MCP subprocess context (waits for DB/async init)
    # Return helpful message instead of hanging forever
    return (
        "list_routes is not available via MCP - importing the FastAPI app hangs.\n\n"
        "Run directly instead:\n"
        "  python scripts/list_routes.py"
    )


@mcp.tool()
def classify_dataclasses() -> str:
    """
    Classify dataclasses according to architecture rules.

    Categorizes each dataclass by its role:
    - DTOs (Data Transfer Objects) - for API boundaries
    - Entities - domain objects with identity
    - Value Objects - immutable domain concepts
    - Config - configuration containers

    Use this to understand data model structure and identify misplaced types.
    """

    def _impl() -> str:
        # Add tools dir to path for the dataclass_classifier imports
        tools_dir = ROOT / "scripts" / "tools"
        if str(tools_dir) not in sys.path:
            sys.path.insert(0, str(tools_dir))

        from dataclass_classifier import (
            classify_all,
            discover_all_dataclasses,
            get_config_paths,
            load_config,
        )

        script_path = ROOT / "scripts" / "classify_dataclasses.py"
        outputs_dir, config_file, script_dir = get_config_paths(script_path)

        config = load_config(config_file)
        layer_map = config["layer_map"]
        domain_map = config["domain_map"]
        ignore_prefixes = config.get("ignore_prefixes", [])

        project_root_config = config.get("project_root", "../..")
        project_root = Path(project_root_config)
        if not project_root.is_absolute():
            project_root = (script_dir / project_root).resolve()

        # Resolve search_paths from config
        search_paths_config = config.get("search_paths", ["nomarr"])
        search_paths = []
        for path_str in search_paths_config:
            search_path = Path(path_str)
            if not search_path.is_absolute():
                search_path = (project_root / search_path).resolve()
            if search_path.exists():
                search_paths.append(search_path)

        dataclasses = discover_all_dataclasses(project_root, search_paths, layer_map, domain_map, ignore_prefixes)
        classify_all(dataclasses)

        # Format output
        lines = []
        lines.append(f"Found {len(dataclasses)} dataclasses:\n")

        by_layer: dict[str, list] = {}
        for dc in dataclasses:
            layer = dc.defining_layer or "unknown"
            if layer not in by_layer:
                by_layer[layer] = []
            by_layer[layer].append(dc)

        for layer in sorted(by_layer.keys()):
            lines.append(f"\n{layer.upper()} ({len(by_layer[layer])}):")
            for dc in sorted(by_layer[layer], key=lambda x: x.name):
                lines.append(f"  {dc.name} [{dc.classification}]")
                if dc.defining_domain:
                    lines.append(f"    domain: {dc.defining_domain}")

        return "\n".join(lines)

    return run_tool(_impl)


@mcp.tool()
def run_qc() -> str:
    """
    Run the complete Quality Control suite.

    Executes all automated quality checks:
    - Naming conventions (check_naming.py)
    - Ruff linting
    - Mypy type checking
    - Dead code detection
    - Security scanning

    Generates a timestamped report in qc_reports/ directory.
    Use this for comprehensive pre-commit validation.

    NOTE: This tool uses subprocess internally and hangs in MCP context.
    Run directly instead: python scripts/run_qc.py
    """
    # run_qc.py uses subprocess internally which hangs in MCP context
    return (
        "run_qc is not available via MCP - subprocess calls hang.\n\nRun directly instead:\n  python scripts/run_qc.py"
    )


# ──────────────────────────────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    mcp.run()
