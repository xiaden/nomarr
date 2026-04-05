"""Frontend linting tool for MCP server.

Runs ESLint, TypeScript checking, and Vitest on frontend.
Returns structured JSON with errors or clean status.
"""

from __future__ import annotations

__all__ = ["lint_project_frontend"]

import re
import subprocess
from typing import Any

from mcp_code_intel.helpers.config_loader import get_workspace_root

project_root = get_workspace_root()
frontend_dir = project_root / "frontend"


def parse_eslint_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """Parse ESLint output into structured errors."""
    errors = []

    # ESLint format: /path/file.tsx
    #   line:col  severity  message  rule
    current_file = None

    for line in stdout.splitlines():
        # Check for file header
        if line.strip() and not line.startswith(" ") and ("/" in line or "\\" in line):
            current_file = line.strip()
            continue

        # Parse error line: "  123:45  error  Message  rule-name"
        match = re.match(
            r"\s+(\d+):(\d+)\s+(error|warning)\s+(.+?)\s+([a-z-]+(?:/[a-z-]+)?)\s*$",
            line,
        )
        if match and current_file:
            line_num, column, severity, message, rule = match.groups()
            errors.append(
                {
                    "tool": "eslint",
                    "file": current_file.replace(str(frontend_dir) + "\\", "frontend/").replace(
                        str(frontend_dir) + "/",
                        "frontend/",
                    ),
                    "line": int(line_num),
                    "column": int(column),
                    "code": rule,
                    "severity": severity,
                    "message": message.strip(),
                    "fix_available": False,
                },
            )

    return errors


def parse_typescript_output(stdout: str, stderr: str) -> list[dict[str, Any]]:
    """Parse TypeScript compiler output into structured errors."""
    errors = []
    combined = stdout + "\n" + stderr

    # TypeScript format: path/file.tsx(line,col): error TSXXXX: message
    pattern = r"(.+?)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.+)"

    for line in combined.splitlines():
        match = re.match(pattern, line.strip())
        if match:
            file_path, line_num, column, severity, code, message = match.groups()
            errors.append(
                {
                    "tool": "typescript",
                    "file": file_path.replace(str(frontend_dir) + "\\", "frontend/").replace(
                        str(frontend_dir) + "/",
                        "frontend/",
                    ),
                    "line": int(line_num),
                    "column": int(column),
                    "code": code,
                    "severity": severity,
                    "message": message.strip(),
                    "fix_available": False,
                },
            )

    return errors


def lint_project_frontend() -> dict[str, Any]:
    """Run frontend linting tools (ESLint, TypeScript, and Vitest).

    Returns:
        Structured JSON:
        {
          "status": "error",
          "summary": {"error": "Frontend directory not found"},
          "errors": []
        }

        Or, when lint/test issues are found:
        {
          "status": "errors",
          "summary": {
            "total_errors": N,
            "by_tool": {"eslint": N, "typescript": N, "vitest": N}
          },
          "errors": [
            {
              "tool": "eslint|typescript|vitest",
              "file": "frontend/..." | null,
              "line": N | null,
              "column": N | null,
              "code": "...",
              "severity": "error|warning",
              "message": "...",
              "fix_available": false
            }
          ]
        }

        Or, when all checks pass:
        {
          "status": "clean",
          "summary": {"tools_run": ["eslint", "typescript", "vitest"]}
        }

    """
    if not frontend_dir.exists():
        return {
            "status": "error",
            "summary": {"error": "Frontend directory not found"},
            "errors": [],
        }

    all_errors = []
    tools_run = []

    # 1. Run ESLint
    try:
        result = subprocess.run(
            ["npm", "run", "lint"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            stdin=subprocess.DEVNULL,
            shell=True,
        )
        tools_run.append("eslint")
        all_errors.extend(parse_eslint_output(result.stdout, result.stderr))
    except Exception as e:
        all_errors.append(
            {
                "tool": "eslint",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-error",
                "severity": "error",
                "message": f"Failed to run eslint: {e}",
                "fix_available": False,
            },
        )

    # 2. Run TypeScript type checking
    try:
        result = subprocess.run(
            ["npx", "tsc", "-b", "--noEmit"],
            capture_output=True,
            text=True,
            cwd=frontend_dir,
            stdin=subprocess.DEVNULL,
            shell=True,
        )
        tools_run.append("typescript")
        all_errors.extend(parse_typescript_output(result.stdout, result.stderr))
    except Exception as e:
        all_errors.append(
            {
                "tool": "typescript",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-error",
                "severity": "error",
                "message": f"Failed to run typescript: {e}",
                "fix_available": False,
            },
        )

    # 3. Run Vitest tests
    try:
        test_result = subprocess.run(
            ["npm", "run", "test"],
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            shell=True,
            cwd=frontend_dir,
        )
        tools_run.append("vitest")
        if test_result.returncode != 0:
            all_errors.append(
                {
                    "tool": "vitest",
                    "file": None,
                    "line": None,
                    "column": None,
                    "code": "test-failure",
                    "severity": "error",
                    "message": (test_result.stdout + test_result.stderr)[-2000:].strip(),
                    "fix_available": False,
                },
            )
    except Exception as e:
        all_errors.append(
            {
                "tool": "vitest",
                "file": None,
                "line": None,
                "column": None,
                "code": "tool-error",
                "severity": "error",
                "message": f"Failed to run vitest: {e}",
                "fix_available": False,
            },
        )

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
    return {"status": "clean", "summary": {"tools_run": tools_run}}
