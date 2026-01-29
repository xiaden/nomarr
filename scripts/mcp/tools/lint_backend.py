"""Backend linting tool for MCP server.

Runs ruff, mypy, and import-linter on specified path.
Returns structured JSON with errors or clean status.
"""

from __future__ import annotations

__all__ = ["lint_backend"]

import re
import subprocess
import sys
from pathlib import Path
from typing import Any

project_root = Path(__file__).parent.parent.parent


def parse_ruff_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """Parse ruff output into structured errors."""
    errors = []

    # Ruff format: path/file.py:line:column: CODE message
    pattern = r"^(.+?):(\d+):(\d+):\s+([A-Z]\d+)\s+(.+?)(?:\s+\[(.+?)\])?$"

    for line in stdout.splitlines():
        match = re.match(pattern, line.strip())
        if match:
            file_path, line_num, column, code, message, fix_hint = match.groups()
            errors.append(
                {
                    "tool": "ruff",
                    "file": file_path,
                    "line": int(line_num),
                    "column": int(column),
                    "code": code,
                    "severity": "error",
                    "message": message.strip(),
                    "fix_available": fix_hint is not None or "[*]" in line,
                }
            )

    return errors


def parse_mypy_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """Parse mypy output into structured errors."""
    errors = []

    # Mypy format: path/file.py:line: error: message [error-code]
    pattern = r"^(.+?):(\d+):\s+(error|warning|note):\s+(.+?)(?:\s+\[(.+?)\])?$"

    for line in stdout.splitlines():
        match = re.match(pattern, line.strip())
        if match:
            file_path, line_num, severity, message, error_code = match.groups()
            if severity != "note":  # Skip notes
                errors.append(
                    {
                        "tool": "mypy",
                        "file": file_path,
                        "line": int(line_num),
                        "column": None,
                        "code": error_code or "mypy",
                        "severity": severity,
                        "message": message.strip(),
                        "fix_available": False,
                    }
                )

    return errors


def parse_import_linter_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """Parse import-linter output into structured errors."""
    errors = []
    combined = stdout + "\n" + stderr

    # Look for contract violations
    # Format: module.name imports module.other (broken contract)
    pattern = r"(.+?)\s+imports\s+(.+?)\s+\(broken"

    for line in combined.splitlines():
        match = re.search(pattern, line)
        if match:
            importer, imported = match.groups()
            errors.append(
                {
                    "tool": "import-linter",
                    "file": None,
                    "line": None,
                    "column": None,
                    "code": "architecture",
                    "severity": "error",
                    "message": f"{importer} imports {imported} (architecture violation)",
                    "fix_available": False,
                }
            )

    return errors


def lint_backend(path: str | None = None) -> dict[str, Any]:
    """
    Run backend linting tools on specified path.

    Args:
        path: Relative path to lint (default: "nomarr/")

    Returns:
        Structured JSON with errors or clean status
    """
    if path is None:
        path = "nomarr/"

    target_path = project_root / path
    if not target_path.exists():
        return {"status": "error", "summary": {"error": f"Path not found: {path}"}, "errors": []}

    all_errors = []
    tools_run = []

    # 1. Run ruff
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(target_path)],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=30,
        )
        tools_run.append("ruff")
        all_errors.extend(parse_ruff_output(result.stdout, result.stderr))
    except subprocess.TimeoutExpired:
        all_errors.append(
            {
                "tool": "ruff",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-timeout",
                "severity": "warning",
                "message": "ruff timed out after 30 seconds",
                "fix_available": False,
            }
        )
    except Exception as e:
        all_errors.append(
            {
                "tool": "ruff",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-error",
                "severity": "error",
                "message": f"Failed to run ruff: {e}",
                "fix_available": False,
            }
        )

    # 2. Run mypy
    try:
        result = subprocess.run(
            [sys.executable, "-m", "mypy", str(target_path)],
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=60,
        )
        tools_run.append("mypy")
        all_errors.extend(parse_mypy_output(result.stdout, result.stderr))
    except subprocess.TimeoutExpired:
        all_errors.append(
            {
                "tool": "mypy",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-timeout",
                "severity": "warning",
                "message": "mypy timed out after 60 seconds",
                "fix_available": False,
            }
        )
    except Exception as e:
        all_errors.append(
            {
                "tool": "mypy",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-error",
                "severity": "error",
                "message": f"Failed to run mypy: {e}",
                "fix_available": False,
            }
        )

    # 3. Run import-linter (only if linting a directory, not a single file)
    if target_path.is_dir():
        try:
            # Use venv path for lint-imports
            venv_script = project_root / ".venv" / "Scripts" / "lint-imports.exe"
            lint_imports_cmd = str(venv_script) if venv_script.exists() else "lint-imports"
            result = subprocess.run([lint_imports_cmd], capture_output=True, text=True, cwd=project_root, timeout=30)
            tools_run.append("import-linter")
            all_errors.extend(parse_import_linter_output(result.stdout, result.stderr))
        except subprocess.TimeoutExpired:
            all_errors.append(
                {
                    "tool": "import-linter",
                    "file": None,
                    "line": None,
                    "column": None,
                    "code": "tool-timeout",
                    "severity": "warning",
                    "message": "import-linter timed out after 30 seconds",
                    "fix_available": False,
                }
            )
        except Exception as e:
            all_errors.append(
                {
                    "tool": "import-linter",
                    "file": None,
                    "line": None,
                    "column": None,
                    "code": "tool-error",
                    "severity": "error",
                    "message": f"Failed to run import-linter: {e}",
                    "fix_available": False,
                }
            )

    # Count files checked (approximate from path)
    if target_path.is_file():
        files_checked = 1
    else:
        files_checked = len(list(target_path.rglob("*.py")))

    if all_errors:
        # Group errors by tool
        by_tool: dict[str, int] = {}
        for error in all_errors:
            tool = error["tool"]
            by_tool[tool] = by_tool.get(tool, 0) + 1

        return {
            "status": "errors",
            "summary": {"total_errors": len(all_errors), "by_tool": by_tool},
            "errors": all_errors,
        }
    else:
        return {"status": "clean", "summary": {"tools_run": tools_run, "files_checked": files_checked}}
