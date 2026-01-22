#!/usr/bin/env python3
"""AST-based checker for correct wall-clock vs monotonic time usage.

Detects semantic misuse where wall-clock time (now_ms, now_s) is used
for intervals/durations that should use monotonic time (internal_ms, internal_s).

Usage:
    python scripts/check_time_usage.py [--format=text|json] [path...]

Examples:
    python scripts/check_time_usage.py nomarr/
    python scripts/check_time_usage.py nomarr/services/infrastructure/
    python scripts/check_time_usage.py --format=json nomarr/
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

# Wall-clock functions (should be used for DB timestamps, user-facing times)
WALL_CLOCK_FUNCS = {"now_ms", "now_s"}

# Monotonic functions (should be used for intervals, timeouts, durations)
MONOTONIC_FUNCS = {"internal_ms", "internal_s"}

# Variable name patterns that suggest monotonic time usage (intervals/durations)
MONOTONIC_VAR_PATTERNS = {
    "start",
    "end",
    "begin",
    "deadline",
    "timeout",
    "elapsed",
    "duration",
    "last_check",
    "probe_start",
    "cache_ts",
    "last_poll",
    "last_frame",
    "last_staleness",
    "recovering_until",
    "backoff",
    "interval",
    "since",
    "age",
}

# Variable name patterns that suggest wall-clock time usage (timestamps)
WALL_CLOCK_VAR_PATTERNS = {
    "created_at",
    "updated_at",
    "scanned_at",
    "timestamp",
    "heartbeat",
    "claimed_at",
    "completed_at",
    "started_at",
    "generated_at",
    "scan_id",  # Often includes timestamp for uniqueness
}

# Dict key patterns that suggest wall-clock time
WALL_CLOCK_KEY_PATTERNS = {
    "created_at",
    "updated_at",
    "scanned_at",
    "timestamp",
    "last_heartbeat",
    "claimed_at",
    "completed_at",
    "started_at",
    "generated_at",
}


@dataclass
class TimeUsageIssue:
    """A detected time usage issue."""

    file: str
    line: int
    col: int
    func: str
    context: str
    reason: str
    severity: Literal["error", "warning"]


@dataclass
class CheckResult:
    """Result of checking a file."""

    file: str
    issues: list[TimeUsageIssue] = field(default_factory=list)


class TimeUsageChecker(ast.NodeVisitor):
    """AST visitor that checks for time function misuse."""

    def __init__(self, filename: str, source: str) -> None:
        self.filename = filename
        self.source_lines = source.splitlines()
        self.issues: list[TimeUsageIssue] = []
        self._current_func: str | None = None
        self._assignments: dict[str, str] = {}  # var_name -> time_func

    def _get_line(self, lineno: int) -> str:
        """Get source line (1-indexed)."""
        if 1 <= lineno <= len(self.source_lines):
            return self.source_lines[lineno - 1].strip()
        return ""

    def _is_wall_clock_call(self, node: ast.AST) -> str | None:
        """Check if node is a wall-clock time call. Returns func name or None."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in WALL_CLOCK_FUNCS:
                return node.func.id
            if isinstance(node.func, ast.Attribute) and node.func.attr in WALL_CLOCK_FUNCS:
                return node.func.attr
        return None

    def _is_monotonic_call(self, node: ast.AST) -> str | None:
        """Check if node is a monotonic time call. Returns func name or None."""
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in MONOTONIC_FUNCS:
                return node.func.id
            if isinstance(node.func, ast.Attribute) and node.func.attr in MONOTONIC_FUNCS:
                return node.func.attr
        return None

    def _var_suggests_monotonic(self, name: str) -> bool:
        """Check if variable name suggests monotonic time usage."""
        name_lower = name.lower()
        for pattern in MONOTONIC_VAR_PATTERNS:
            if pattern in name_lower:
                return True
        return False

    def _var_suggests_wall_clock(self, name: str) -> bool:
        """Check if variable name suggests wall-clock time usage."""
        name_lower = name.lower()
        for pattern in WALL_CLOCK_VAR_PATTERNS:
            if pattern in name_lower:
                return True
        return False

    def _key_suggests_wall_clock(self, key: str) -> bool:
        """Check if dict key suggests wall-clock time usage."""
        key_lower = key.lower()
        for pattern in WALL_CLOCK_KEY_PATTERNS:
            if pattern in key_lower:
                return True
        return False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track current function for context."""
        old_func = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = old_func

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track current function for context."""
        old_func = self._current_func
        self._current_func = node.name
        self.generic_visit(node)
        self._current_func = old_func

    def visit_Assign(self, node: ast.Assign) -> None:
        """Check assignments for misuse patterns."""
        # Check for wall-clock assigned to monotonic-like variable
        wall_func = self._is_wall_clock_call(node.value)
        if wall_func:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    self._assignments[var_name] = wall_func

                    if self._var_suggests_monotonic(var_name):
                        self.issues.append(
                            TimeUsageIssue(
                                file=self.filename,
                                line=node.lineno,
                                col=node.col_offset,
                                func=wall_func,
                                context=self._get_line(node.lineno),
                                reason=f"Variable '{var_name}' suggests interval/duration usage, but uses wall-clock {wall_func}(). Use internal_s() or internal_ms() instead.",
                                severity="error",
                            )
                        )

        # Check for monotonic assigned to wall-clock-like variable
        mono_func = self._is_monotonic_call(node.value)
        if mono_func:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    var_name = target.id
                    self._assignments[var_name] = mono_func

                    if self._var_suggests_wall_clock(var_name):
                        self.issues.append(
                            TimeUsageIssue(
                                file=self.filename,
                                line=node.lineno,
                                col=node.col_offset,
                                func=mono_func,
                                context=self._get_line(node.lineno),
                                reason=f"Variable '{var_name}' suggests timestamp storage, but uses monotonic {mono_func}(). Use now_ms() or now_s() instead.",
                                severity="error",
                            )
                        )

        self.generic_visit(node)

    def visit_BinOp(self, node: ast.BinOp) -> None:
        """Check subtraction patterns for elapsed time calculation."""
        if isinstance(node.op, ast.Sub):
            # Pattern: now_ms() - start (should be internal_ms() - start)
            wall_func = self._is_wall_clock_call(node.left)
            if wall_func:
                # Check if right side is a variable that was assigned wall-clock
                # This is fine: now_ms() - last_heartbeat (both wall-clock for staleness check in DB)
                # This is wrong: now_ms() - probe_start (duration measurement)
                if isinstance(node.right, ast.Name):
                    var_name = node.right.id
                    if self._var_suggests_monotonic(var_name):
                        self.issues.append(
                            TimeUsageIssue(
                                file=self.filename,
                                line=node.lineno,
                                col=node.col_offset,
                                func=wall_func,
                                context=self._get_line(node.lineno),
                                reason=f"Elapsed time calculation uses wall-clock {wall_func}(). Use internal_s() or internal_ms() for duration/interval measurements.",
                                severity="error",
                            )
                        )
                elif isinstance(node.right, ast.Attribute):
                    attr_name = node.right.attr
                    if self._var_suggests_monotonic(attr_name):
                        self.issues.append(
                            TimeUsageIssue(
                                file=self.filename,
                                line=node.lineno,
                                col=node.col_offset,
                                func=wall_func,
                                context=self._get_line(node.lineno),
                                reason=f"Elapsed time calculation uses wall-clock {wall_func}(). Use internal_s() or internal_ms() for duration/interval measurements.",
                                severity="error",
                            )
                        )

        self.generic_visit(node)

    def visit_Dict(self, node: ast.Dict) -> None:
        """Check dict literals for monotonic time used as timestamps."""
        for key, value in zip(node.keys, node.values):
            if key is None:
                continue

            # Get key name
            key_name: str | None = None
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                key_name = key.value

            if key_name and self._key_suggests_wall_clock(key_name):
                mono_func = self._is_monotonic_call(value)
                if mono_func:
                    self.issues.append(
                        TimeUsageIssue(
                            file=self.filename,
                            line=node.lineno,
                            col=node.col_offset,
                            func=mono_func,
                            context=self._get_line(node.lineno),
                            reason=f"Dict key '{key_name}' suggests DB timestamp, but uses monotonic {mono_func}(). Use now_ms() for persistence.",
                            severity="error",
                        )
                    )

        self.generic_visit(node)


def check_file(filepath: Path) -> CheckResult:
    """Check a single file for time usage issues."""
    result = CheckResult(file=str(filepath))

    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        result.issues.append(
            TimeUsageIssue(
                file=str(filepath),
                line=0,
                col=0,
                func="",
                context="",
                reason=f"Could not parse file: {e}",
                severity="warning",
            )
        )
        return result

    checker = TimeUsageChecker(str(filepath), source)
    checker.visit(tree)
    result.issues = checker.issues

    return result


def check_path(path: Path) -> list[CheckResult]:
    """Check a file or directory recursively."""
    results: list[CheckResult] = []

    if path.is_file() and path.suffix == ".py":
        results.append(check_file(path))
    elif path.is_dir():
        for py_file in path.rglob("*.py"):
            # Skip test files, they may have legitimate test cases
            if "/tests/" in str(py_file) or "\\tests\\" in str(py_file):
                continue
            # Skip the time_helper itself
            if py_file.name == "time_helper.py":
                continue
            results.append(check_file(py_file))

    return results


def format_text(results: list[CheckResult]) -> str:
    """Format results as text."""
    lines: list[str] = []
    total_errors = 0
    total_warnings = 0

    for result in results:
        for issue in result.issues:
            if issue.severity == "error":
                total_errors += 1
                prefix = "ERROR"
            else:
                total_warnings += 1
                prefix = "WARNING"

            lines.append(f"{issue.file}:{issue.line}:{issue.col}: {prefix}: {issue.reason}")
            if issue.context:
                lines.append(f"    {issue.context}")
            lines.append("")

    if total_errors == 0 and total_warnings == 0:
        lines.append("No time usage issues found.")
    else:
        lines.append(f"Found {total_errors} error(s) and {total_warnings} warning(s).")

    return "\n".join(lines)


def format_json(results: list[CheckResult]) -> str:
    """Format results as JSON."""
    issues = []
    for result in results:
        for issue in result.issues:
            issues.append(
                {
                    "file": issue.file,
                    "line": issue.line,
                    "col": issue.col,
                    "func": issue.func,
                    "context": issue.context,
                    "reason": issue.reason,
                    "severity": issue.severity,
                }
            )

    return json.dumps({"issues": issues, "total": len(issues)}, indent=2)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Check for correct wall-clock vs monotonic time usage.")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["nomarr/"],
        help="Paths to check (default: nomarr/)",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )

    args = parser.parse_args()

    all_results: list[CheckResult] = []
    for path_str in args.paths:
        path = Path(path_str)
        if not path.exists():
            print(f"Path not found: {path}", file=sys.stderr)
            continue
        all_results.extend(check_path(path))

    if args.format == "json":
        print(format_json(all_results))
    else:
        print(format_text(all_results))

    # Exit with error code if any errors found
    error_count = sum(1 for r in all_results for i in r.issues if i.severity == "error")
    return 1 if error_count > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
