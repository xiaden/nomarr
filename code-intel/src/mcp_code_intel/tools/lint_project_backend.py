"""Backend linting tool for MCP server.

Runs ruff (check + format), mypy, import-linter, and pytest on specified path.
Returns structured JSON with errors or clean status.
"""

from __future__ import annotations

__all__ = ["lint_project_backend"]

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mcp_code_intel.helpers.config_loader import get_workspace_root, load_config

# DEBUG: Set to "ruff", "mypy", "import-linter", "mock", or None to run all
DEBUG_LINTER: str | None = None

# Use get_workspace_root() to find actual git/.git/pyproject.toml root
# This ensures paths work correctly whether code-intel is standalone or nested in monorepo
project_root = get_workspace_root()


def parse_raw_errors(stdout: str, stderr: str, tool: str) -> list[dict[str, Any]]:
    """Parse raw linter output into normalized error list.

    Returns list of dicts with: code, description, file, line, fix_available
    """
    errors: list[dict[str, Any]] = []

    if tool == "ruff":
        # Ruff JSON output format (requires --output-format=json)
        try:
            ruff_errors = json.loads(stdout)
            errors.extend(
                {
                    "code": error["code"],
                    "description": error["message"],
                    "file": error["filename"],
                    "line": error["location"]["row"],
                    "fix_available": error.get("fix") is not None,
                }
                for error in ruff_errors
            )
        except (json.JSONDecodeError, KeyError):
            # Fallback: ruff returned no errors or invalid JSON
            pass

    elif tool == "mypy":
        # Mypy JSON format: --output json (newline-delimited JSON, one object per line)
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                error = json.loads(line)
                # Skip if not a dict (non-JSON output parsed as string)
                if not isinstance(error, dict):
                    continue
                # Skip notes
                if error.get("severity") == "note":
                    continue

                errors.append(
                    {
                        "code": error.get("code") or "mypy-error",
                        "description": error.get("message", "").strip(),
                        "file": error.get("file"),
                        "line": error.get("line"),
                        "fix_available": False,
                    },
                )
            except (json.JSONDecodeError, KeyError):
                # Skip invalid lines
                continue

    elif tool == "import-linter":
        # Import-linter format: module.name imports module.other (broken contract)
        combined = stdout + "\n" + stderr
        pattern = r"(.+?)\s+imports\s+(.+?)\s+\(broken"
        for line in combined.splitlines():
            match = re.search(pattern, line)
            if match:
                importer, imported = match.groups()
                errors.append(
                    {
                        "code": "architecture",
                        "description": f"{importer} imports {imported} (architecture violation)",
                        "file": None,
                        "line": None,
                        "fix_available": False,
                    },
                )

    return errors


def _is_valid_mypy_json(stdout: str) -> bool:
    """Check if mypy output is valid JSON format.

    Mypy JSON output should be newline-delimited JSON objects.
    If we get plain text errors, it's likely a cache or config issue.
    """
    if not stdout.strip():
        return True  # Empty output is valid (no errors)

    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
            if not isinstance(parsed, dict):
                return False
        except json.JSONDecodeError:
            return False
    return True


def _run_mypy(
    venv_mypy: Path,
    target_files: list[str],
    project_root: Path,
    clear_cache: bool = False,
) -> tuple[str, str]:
    """Run mypy and return stdout, stderr.

    If clear_cache=True, deletes .mypy_cache before running.
    """
    if clear_cache:
        cache_dir = project_root / ".mypy_cache"
        if cache_dir.exists():
            shutil.rmtree(cache_dir)

    try:
        result = subprocess.run(
            [
                str(venv_mypy),
                "--output",
                "json",
                "--explicit-package-bases",
                "--config-file",
                str(project_root / "pyproject.toml"),
                *target_files,
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
        )
        return result.stdout.decode(errors="replace"), result.stderr.decode(errors="replace")
    except subprocess.CalledProcessError as e:
        return e.stdout.decode(errors="replace"), e.stderr.decode(errors="replace")


def normalize_to_json_structure(errors: list[dict[str, Any]], tool: str) -> dict[str, Any]:
    """Convert error list to standardized JSON structure.

    Returns:
    {
      "CODE": {
        "description": "...",
        "fix_available": bool,
        "occurrences": [{"file": "...", "line": 123}, ...]
      }
    }

    """
    result = {}

    for error in errors:
        code = error["code"]
        if code not in result:
            result[code] = {
                "description": error["description"],
                "fix_available": error["fix_available"],
                "occurrences": [],
            }

        # Add occurrence (skip if no file/line for import-linter)
        if error["file"] is not None and error["line"] is not None:
            result[code]["occurrences"].append({"file": error["file"], "line": error["line"]})
        elif error["file"] is None and error["line"] is None and not result[code]["occurrences"]:
            # For import-linter violations without specific location
            result[code]["occurrences"].append({"file": None, "line": None})

    return result


def lint_project_backend(path: str | None = None, check_all: bool = False) -> dict[str, Any]:
    """Run backend linting tools on specified path.

    Default behavior: Only lints modified and untracked files in the scope.
    Use check_all=True to lint all files in the path.

    Args:
        path: Relative path to lint (defaults to config's backend_path or "."
              if not configured). Only files in this path are checked.
        check_all: If True, lint all files in path; if False (default),
                   only modified/untracked files. import-linter and pytest
                   always run regardless.

    Returns:
        Structured JSON:
        {
          "ruff": {"E501": {"description": "...", "fix_available": true, "occurrences": [...]}},
          "ruff-format": {
            "<file>": {"description": "...", "fix_available": true, "occurrences": [...]}
          },
          "mypy": {...},
          "import-linter": {
            "architecture": {"description": "...", "fix_available": false, "occurrences": [...]}
          },
          "pytest": {"status": "pass|fail|skipped|error", "passed": N, "failed": N},
          "summary": {"total_errors": 3, "clean": false, "files_checked": 5}
        }

    """
    # Track if caller explicitly provided a path (affects git-diff scope behavior)
    path_explicit = path is not None

    # Mock mode for testing return without running linters
    if DEBUG_LINTER == "mock":
        return {
            "ruff": {
                "E501": {
                    "description": "Line too long (88 > 79 characters)",
                    "fix_available": False,
                    "occurrences": [{"file": "nomarr/services/test.py", "line": 42}],
                },
            },
            "mypy": {
                "arg-type": {
                    "description": "Argument 1 has incompatible type",
                    "fix_available": False,
                    "occurrences": [{"file": "nomarr/workflows/test_wf.py", "line": 15}],
                },
            },
            "summary": {"total_errors": 2, "clean": False, "files_checked": 10},
        }

    # Determine target path
    if path is None:
        # Use config's backend_path if available, otherwise current directory
        config = load_config(project_root)
        backend_path = config.get("project", {}).get("backend_path")
        if backend_path:
            path = backend_path
        else:
            # Default to current directory when no config available
            path = "."

    target_path = project_root / path if path else project_root

    if not target_path.exists():
        raise FileNotFoundError(f"Path not found: {path}")

    # Get files to lint
    if check_all or path_explicit:
        target_files = [str(target_path)]
    else:
        # Get modified tracked files
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", "HEAD"],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
        )
        modified = result.stdout.decode().strip().split("\n")

        # Get untracked files (new files not yet added)
        result = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            check=True,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            cwd=project_root,
        )
        untracked = result.stdout.decode().strip().split("\n")

        # Combine and filter for Python files in specified path
        all_files = modified + untracked
        # Normalize path for comparison (handle both absolute and relative)
        target_path_str = str(target_path.relative_to(project_root))
        modified_py = [
            f
            for f in all_files
            if f
            and f.endswith(".py")
            and (Path(f).is_relative_to(Path(target_path_str)) if target_path_str != "." else True)
        ]

        if not modified_py:
            return {"summary": {"total_errors": 0, "clean": True, "files_checked": 0}}

        target_files = [str(project_root / f) for f in modified_py]

    # Initialize result structure
    result_json: dict[str, Any] = {}
    total_errors = 0

    # Run ruff
    if DEBUG_LINTER is None or DEBUG_LINTER == "ruff":
        venv_ruff = project_root / ".venv" / "Scripts" / "ruff.exe"
        try:
            result = subprocess.run(
                [str(venv_ruff), "check", "--no-fix", "--output-format=json", *target_files],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=project_root,
            )
            stdout = result.stdout.decode(errors="replace")
            stderr = result.stderr.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            stdout = e.stdout.decode(errors="replace")
            stderr = e.stderr.decode(errors="replace")

        raw_errors = parse_raw_errors(stdout, stderr, "ruff")
        if raw_errors:
            result_json["ruff"] = normalize_to_json_structure(raw_errors, "ruff")
            total_errors += sum(len(v["occurrences"]) for v in result_json["ruff"].values())

        # Run ruff format check
        try:
            fmt_result = subprocess.run(
                [str(venv_ruff), "format", "--check", *target_files],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=project_root,
            )
            fmt_stdout = fmt_result.stdout.decode(errors="replace")
            fmt_stderr = fmt_result.stderr.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            fmt_stdout = e.stdout.decode(errors="replace")
            fmt_stderr = e.stderr.decode(errors="replace")

        # ruff format --check outputs "Would reformat: /path/to/file.py" lines
        format_violations: list[dict[str, Any]] = []
        combined_fmt = fmt_stdout + "\n" + fmt_stderr
        for fmt_line in combined_fmt.splitlines():
            m = re.match(r"Would reformat:\s+(.+)", fmt_line.strip())
            if m:
                format_violations.append(
                    {
                        "code": "format",
                        "description": "File would be reformatted by ruff format",
                        "file": m.group(1).strip(),
                        "line": None,
                        "fix_available": True,
                    }
                )

        if format_violations:
            fmt_dict: dict[str, Any] = {}
            for v in format_violations:
                fmt_dict[v["file"]] = {
                    "description": v["description"],
                    "fix_available": True,
                    "occurrences": [{"file": v["file"], "line": None}],
                }
            result_json["ruff-format"] = fmt_dict
            total_errors += len(format_violations)

    # Run mypy
    if DEBUG_LINTER is None or DEBUG_LINTER == "mypy":
        venv_mypy = project_root / ".venv" / "Scripts" / "mypy.exe"
        stdout, stderr = _run_mypy(venv_mypy, target_files, project_root)

        # Check if output is valid JSON; if not, likely cache issue
        if not _is_valid_mypy_json(stdout):
            # Retry with cache cleared
            stdout, stderr = _run_mypy(venv_mypy, target_files, project_root, clear_cache=True)

            if not _is_valid_mypy_json(stdout):
                # Still not JSON - this is a real error
                combined_output = f"stdout: {stdout}\nstderr: {stderr}"
                raise RuntimeError(
                    f"mypy failed to produce JSON output after cache clear. "
                    f"This may indicate a configuration or module resolution issue."
                    f"\n{combined_output}",
                )

        raw_errors = parse_raw_errors(stdout, stderr, "mypy")
        if raw_errors:
            result_json["mypy"] = normalize_to_json_structure(raw_errors, "mypy")
            total_errors += sum(len(v["occurrences"]) for v in result_json["mypy"].values())

    # Run import-linter (always run — matches CI which runs on every push)
    if DEBUG_LINTER is None or DEBUG_LINTER == "import-linter":
        venv_lint_imports = project_root / ".venv" / "Scripts" / "lint-imports.exe"
        try:
            result = subprocess.run(
                [str(venv_lint_imports)],
                capture_output=True,
                stdin=subprocess.DEVNULL,
                cwd=project_root,
            )
            stdout = result.stdout.decode(errors="replace")
            stderr = result.stderr.decode(errors="replace")
        except subprocess.CalledProcessError as e:
            stdout = e.stdout.decode(errors="replace")
            stderr = e.stderr.decode(errors="replace")

        raw_errors = parse_raw_errors(stdout, stderr, "import-linter")
        if raw_errors:
            result_json["import-linter"] = normalize_to_json_structure(raw_errors, "import-linter")
            total_errors += sum(
                len(v["occurrences"]) for v in result_json["import-linter"].values()
            )

    # Run pytest (always run — matches CI which runs tests on every push)
    if DEBUG_LINTER is None:
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
        test_dir = project_root / "tests"
        if test_dir.exists() and venv_python.exists():
            try:
                pytest_result = subprocess.run(
                    [
                        str(venv_python),
                        "-m",
                        "pytest",
                        "tests/",
                        "-v",
                        "-m",
                        "not container_only and not requires_database and not code_smell",
                        "--tb=short",
                    ],
                    capture_output=True,
                    stdin=subprocess.DEVNULL,
                    cwd=project_root,
                )
                pytest_stdout = pytest_result.stdout.decode(errors="replace")
                pytest_stderr = pytest_result.stderr.decode(errors="replace")
                pytest_passed = pytest_result.returncode == 0

                # Parse summary line: "X passed, Y failed, Z error in Ns"
                summary_match = re.search(
                    r"(\d+) passed(?:,\s*(\d+) failed)?(?:,\s*(\d+) error(?:s)?)?\s+in",
                    pytest_stdout + pytest_stderr,
                )
                pytest_summary: dict[str, Any] = {
                    "status": "pass" if pytest_passed else "fail",
                    "passed": int(summary_match.group(1)) if summary_match else None,
                    "failed": int(summary_match.group(2) or 0) if summary_match else None,
                }
                if not pytest_passed:
                    # Include last 100 lines of output on failure
                    combined_lines = (pytest_stdout + pytest_stderr).splitlines()
                    pytest_summary["output"] = "\n".join(combined_lines[-100:])
                    failed_count = pytest_summary.get("failed") or 0
                    total_errors += failed_count

                result_json["pytest"] = pytest_summary

            except Exception as e:
                result_json["pytest"] = {"status": "error", "error": str(e)}
        else:
            if not test_dir.exists():
                result_json["pytest"] = {
                    "status": "skipped",
                    "reason": "tests/ directory not found",
                }
            elif not venv_python.exists():
                result_json["pytest"] = {"status": "skipped", "reason": "venv python not found"}

    # Add summary
    result_json["summary"] = {
        "total_errors": total_errors,
        "clean": total_errors == 0,
        "files_checked": len(target_files),
    }

    # Validate JSON serialization
    try:
        json.dumps(result_json)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Failed to serialize lint results to JSON: {e}") from e

    return result_json
