#!/usr/bin/env python3
"""
Automated Slop & Drift Detection

Uses existing tools to discover code quality issues:
- radon: Complexity metrics
- import-linter: Architecture violations
- flake8 + plugins: Code smells, overcomplicated patterns, commented code
- Custom analysis: AI slop patterns

Output is designed to TEACH you what patterns exist in your codebase.

Usage:
    python scripts/detect_slop.py                           # Scan entire nomarr/ directory
    python scripts/detect_slop.py nomarr/interfaces/        # Scan specific directory
    python scripts/detect_slop.py nomarr/app.py             # Scan specific file
    python scripts/detect_slop.py --format html             # Generate HTML report
    python scripts/detect_slop.py --format md               # Generate Markdown report
    python scripts/detect_slop.py --no-save --format html   # Print HTML to stdout
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parent.parent
NOMARR_DIR = ROOT / "nomarr"
REPORTS_DIR = ROOT / "qc_reports"


# ──────────────────────────────────────────────────────────────────────
# Data Structures
# ──────────────────────────────────────────────────────────────────────


@dataclass
class AnalysisResult:
    """Structured result from a single QC tool."""

    name: str  # Tool name (e.g., "Radon CC")
    command: str  # Full command executed
    stdout: str  # Raw stdout from tool
    stderr: str  # Raw stderr from tool
    returncode: int  # Exit code
    issues: list[str] = field(default_factory=list)  # Extracted issue descriptions
    severity: str = "low"  # "low", "medium", "high"
    summary: str = ""  # One-line summary of findings


# ──────────────────────────────────────────────────────────────────────
# Utility Functions
# ──────────────────────────────────────────────────────────────────────


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI color codes from text.

    Args:
        text: Text potentially containing ANSI escape sequences

    Returns:
        Clean text with all ANSI codes removed
    """
    # Pattern matches ANSI escape sequences like \x1b[31m, \x1b[0m, etc.
    ansi_pattern = re.compile(r"\x1b\[[0-9;]*m")
    return ansi_pattern.sub("", text)


# ──────────────────────────────────────────────────────────────────────
# Tool Output Normalizers (Parse raw output → structured issues)
# ──────────────────────────────────────────────────────────────────────


def normalize_radon_cc(stdout: str) -> tuple[list[str], str]:
    """Parse radon cc output to extract complex functions and errors.

    Args:
        stdout: Raw stdout from radon cc command

    Returns:
        Tuple of (issues list, summary string)
    """
    issues = []
    error_count = 0
    complexity_count = 0
    lines = stdout.strip().split("\n")

    for line in lines:
        # Capture radon analysis errors
        if "ERROR:" in line:
            issues.append(line.strip())
            error_count += 1
        # Match pattern like: "    M 85:4 ClassName.method_name - C (15)"
        elif " - " in line and any(grade in line for grade in [" - C ", " - D ", " - E ", " - F "]):
            issues.append(line.strip())
            complexity_count += 1

    if not issues:
        return [], "No complexity issues found"

    # Build summary based on what we found
    parts = []
    if complexity_count > 0:
        parts.append(f"{complexity_count} complex function(s)")
    if error_count > 0:
        parts.append(f"{error_count} radon analysis error(s)")

    summary = "Found " + " and ".join(parts)
    return issues, summary


def normalize_radon_mi(stdout: str) -> tuple[list[str], str]:
    """Parse radon mi output to extract low maintainability files and errors.

    Args:
        stdout: Raw stdout from radon mi command

    Returns:
        Tuple of (issues list, summary string)
    """
    import re

    issues = []
    error_count = 0
    mi_count = 0
    lines = stdout.strip().split("\n")

    for line in lines:
        # Capture radon analysis errors
        if "ERROR:" in line:
            issues.append(line.strip())
            error_count += 1
        # Match pattern like: "nomarr/file.py - C (12.34)"
        elif re.search(r" - [CDF] \([\d.]+\)", line):
            issues.append(line.strip())
            mi_count += 1

    if not issues:
        return [], "All files have good maintainability"

    # Build summary based on what we found
    parts = []
    if mi_count > 0:
        parts.append(f"{mi_count} file(s) with maintainability issues")
    if error_count > 0:
        parts.append(f"{error_count} radon analysis error(s)")

    summary = "Found " + " and ".join(parts)
    return issues, summary


def normalize_import_linter(stdout: str, stderr: str) -> tuple[list[str], str]:
    """Parse import-linter output to extract violations."""
    issues = []

    # Strip ANSI color codes from the content
    content = strip_ansi_codes(stdout + "\n" + stderr)
    lines = content.split("\n")

    in_violation_section = False
    for line in lines:
        if "Contracts" in line and "broken" in line.lower():
            in_violation_section = True
        elif in_violation_section and line.strip() and not line.startswith("-"):
            issues.append(line.strip())

    # Also look for direct violation messages
    for line in lines:
        if "->" in line and ("imports" in line.lower() or "nomarr" in line):
            issues.append(line.strip())

    if not issues:
        return [], "No architecture violations found"

    return issues[:20], f"Found {len(issues)} architecture violation(s)"  # Limit to 20


def normalize_flake8(stdout: str, stderr: str, returncode: int) -> tuple[list[str], str]:
    """Parse flake8 output to extract code smell issues or tool failures.

    Args:
        stdout: Raw stdout from flake8 command
        stderr: Raw stderr from flake8 command
        returncode: Exit code from flake8 command

    Returns:
        Tuple of (issues list, summary string)
    """
    # Handle tool failures (plugin errors, config issues, etc.)
    if returncode != 0 and not stdout.strip():
        # Tool failed without producing normal output - likely a crash or config error
        issues = []
        stderr_clean = strip_ansi_codes(stderr)
        stderr_lines = [line.strip() for line in stderr_clean.split("\n") if line.strip()]

        # Extract last ~15 lines of stderr (traceback or error message)
        if stderr_lines:
            issues = stderr_lines[-15:]

        summary = f"Flake8 failed with exit code {returncode}; no results. Likely plugin or config error - see stderr."
        return issues, summary

    # Normal flake8 output - parse code smells
    issues = []
    lines = stdout.strip().split("\n")

    for line in lines:
        if line.strip() and ":" in line:
            issues.append(line.strip())

    if not issues:
        return [], "No code smells detected"

    return issues[:50], f"Found {len(issues)} code smell(s)"  # Limit to 50


def normalize_eradicate(stdout: str) -> tuple[list[str], str]:
    """Parse eradicate output to extract commented code."""
    issues = []
    lines = stdout.strip().split("\n")

    for line in lines:
        if line.strip() and ":" in line:
            issues.append(line.strip())

    if not issues:
        return [], "No commented-out code found"

    return issues[:30], f"Found {len(issues)} instance(s) of commented code"  # Limit to 30


# ──────────────────────────────────────────────────────────────────────
# Severity Calculator
# ──────────────────────────────────────────────────────────────────────


def calculate_severity(tool_name: str, issues: list[str], returncode: int) -> str:
    """Calculate severity based on tool output and issue count."""
    if returncode != 0 and not issues:
        # Tool failed but no issues parsed - likely execution error
        return "low"

    issue_count = len(issues)

    # Tool-specific severity rules
    if "radon cc" in tool_name.lower():
        # Complexity: More than 10 complex functions is high severity
        if issue_count > 10:
            return "high"
        elif issue_count > 3:
            return "medium"
        return "low"

    elif "radon mi" in tool_name.lower():
        # Maintainability: Any F grade is high, multiple C/D is medium
        has_f_grade = any(" - F " in issue for issue in issues)
        if has_f_grade:
            return "high"
        elif issue_count > 5:
            return "medium"
        return "low"

    elif "import linter" in tool_name.lower():
        # Architecture violations: Always high severity
        if issue_count > 0:
            return "high"
        return "low"

    elif "flake8" in tool_name.lower():
        # Code smells: Many issues = medium, few = low
        if "strict" in tool_name.lower():
            # Strict complexity check - more lenient on severity
            if issue_count > 20:
                return "medium"
            return "low"
        else:
            # General code smells
            if issue_count > 30:
                return "high"
            elif issue_count > 10:
                return "medium"
            return "low"

    elif "eradicate" in tool_name.lower():
        # Commented code: Low priority
        if issue_count > 20:
            return "medium"
        return "low"

    # Default: base on issue count
    if issue_count > 20:
        return "high"
    elif issue_count > 5:
        return "medium"
    return "low"


# ──────────────────────────────────────────────────────────────────────
# Output Renderers
# ──────────────────────────────────────────────────────────────────────


def render_html(results: list[AnalysisResult], timestamp: str, target: str) -> str:
    """Render results as HTML with summary table and collapsible details."""
    import html as html_module

    # Calculate overall stats
    total_issues = sum(len(r.issues) for r in results)
    high_severity = sum(1 for r in results if r.severity == "high")
    medium_severity = sum(1 for r in results if r.severity == "medium")
    low_severity = sum(1 for r in results if r.severity == "low")

    # Severity badge colors
    def severity_badge(severity: str) -> str:
        colors = {
            "high": "#dc3545",
            "medium": "#fd7e14",
            "low": "#28a745",
        }
        color = colors.get(severity, "#6c757d")
        return f'<span style="background: {color}; color: white; padding: 2px 8px; border-radius: 3px; font-weight: bold;">{severity.upper()}</span>'

    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Code Quality Report - {html_module.escape(target)}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; border-bottom: 3px solid #007bff; padding-bottom: 10px; }}
        h2 {{ color: #555; margin-top: 30px; }}
        .meta {{ color: #666; font-size: 0.9em; margin-bottom: 20px; }}
        .summary-table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        .summary-table th, .summary-table td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        .summary-table th {{ background: #f8f9fa; font-weight: 600; }}
        .summary-table tr:hover {{ background: #f8f9fa; }}
        .stats {{ display: flex; gap: 20px; margin: 20px 0; }}
        .stat-card {{ flex: 1; padding: 20px; border-radius: 6px; text-align: center; }}
        .stat-card.total {{ background: #e7f3ff; border: 2px solid #007bff; }}
        .stat-card.high {{ background: #ffe5e7; border: 2px solid #dc3545; }}
        .stat-card.medium {{ background: #fff3e0; border: 2px solid #fd7e14; }}
        .stat-card.low {{ background: #e8f5e9; border: 2px solid #28a745; }}
        .stat-value {{ font-size: 2em; font-weight: bold; margin-bottom: 5px; }}
        .stat-label {{ font-size: 0.9em; color: #666; }}
        details {{ margin: 15px 0; border: 1px solid #ddd; border-radius: 4px; }}
        summary {{ padding: 12px; background: #f8f9fa; cursor: pointer; font-weight: 500; }}
        summary:hover {{ background: #e9ecef; }}
        .tool-output {{ padding: 15px; background: #f8f9fa; border-radius: 4px; margin: 10px 0; }}
        pre {{ background: #2d2d2d; color: #f8f8f2; padding: 15px; border-radius: 4px; overflow-x: auto; font-size: 0.85em; }}
        .issue-list {{ margin: 10px 0; padding-left: 20px; }}
        .issue-list li {{ margin: 5px 0; font-family: monospace; font-size: 0.9em; }}
        .no-issues {{ color: #28a745; font-weight: 500; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔍 Code Quality Report</h1>
        <div class="meta">
            <strong>Generated:</strong> {html_module.escape(timestamp)}<br>
            <strong>Target:</strong> {html_module.escape(target)}
        </div>

        <div class="stats">
            <div class="stat-card total">
                <div class="stat-value">{total_issues}</div>
                <div class="stat-label">Total Issues</div>
            </div>
            <div class="stat-card high">
                <div class="stat-value">{high_severity}</div>
                <div class="stat-label">High Severity</div>
            </div>
            <div class="stat-card medium">
                <div class="stat-value">{medium_severity}</div>
                <div class="stat-label">Medium Severity</div>
            </div>
            <div class="stat-card low">
                <div class="stat-value">{low_severity}</div>
                <div class="stat-label">Low Severity</div>
            </div>
        </div>

        <h2>Summary</h2>
        <table class="summary-table">
            <thead>
                <tr>
                    <th>Tool</th>
                    <th>Severity</th>
                    <th>Issues</th>
                    <th>Summary</th>
                </tr>
            </thead>
            <tbody>
"""

    for result in results:
        html_content += f"""                <tr>
                    <td><strong>{html_module.escape(result.name)}</strong></td>
                    <td>{severity_badge(result.severity)}</td>
                    <td>{len(result.issues)}</td>
                    <td>{html_module.escape(result.summary)}</td>
                </tr>
"""

    html_content += """            </tbody>
        </table>

        <h2>Detailed Results</h2>
"""

    for result in results:
        issue_list_html = ""
        if result.issues:
            issue_list_html = "<ul class='issue-list'>\n"
            for issue in result.issues:
                issue_list_html += f"                    <li>{html_module.escape(issue)}</li>\n"
            issue_list_html += "                </ul>"
        else:
            issue_list_html = "<p class='no-issues'>✅ No issues found</p>"

        html_content += f"""
        <details>
            <summary>{html_module.escape(result.name)} - {severity_badge(result.severity)} ({len(result.issues)} issues)</summary>
            <div class="tool-output">
                <p><strong>Summary:</strong> {html_module.escape(result.summary)}</p>
                <p><strong>Command:</strong> <code>{html_module.escape(result.command)}</code></p>
                <p><strong>Exit Code:</strong> {result.returncode}</p>

                <h3>Issues</h3>
{issue_list_html}

                <details>
                    <summary>Raw Output (STDOUT)</summary>
                    <pre>{html_module.escape(strip_ansi_codes(result.stdout)) if result.stdout.strip() else "(empty)"}</pre>
                </details>

                <details>
                    <summary>Raw Output (STDERR)</summary>
                    <pre>{html_module.escape(strip_ansi_codes(result.stderr)) if result.stderr.strip() else "(empty)"}</pre>
                </details>
            </div>
        </details>
"""

    html_content += """
    </div>
</body>
</html>"""

    return html_content


def render_markdown(results: list[AnalysisResult], timestamp: str, target: str) -> str:
    """Render results as Markdown."""
    total_issues = sum(len(r.issues) for r in results)
    high_severity = sum(1 for r in results if r.severity == "high")
    medium_severity = sum(1 for r in results if r.severity == "medium")
    low_severity = sum(1 for r in results if r.severity == "low")

    md_content = f"""# 🔍 Code Quality Report

**Generated:** {timestamp}
**Target:** {target}

## Summary Statistics

- **Total Issues:** {total_issues}
- **High Severity:** {high_severity}
- **Medium Severity:** {medium_severity}
- **Low Severity:** {low_severity}

## Summary Table

| Tool | Severity | Issues | Summary |
|------|----------|--------|---------|
"""

    for result in results:
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(result.severity, "⚪")
        md_content += f"| {result.name} | {severity_emoji} {result.severity.upper()} | {len(result.issues)} | {result.summary} |\n"

    md_content += "\n## Detailed Results\n\n"

    for result in results:
        severity_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(result.severity, "⚪")
        md_content += f"### {result.name} - {severity_emoji} {result.severity.upper()}\n\n"
        md_content += f"**Summary:** {result.summary}  \n"
        md_content += f"**Command:** `{result.command}`  \n"
        md_content += f"**Exit Code:** {result.returncode}  \n\n"

        if result.issues:
            md_content += f"**Issues Found ({len(result.issues)}):**\n\n"
            for issue in result.issues[:20]:  # Limit in markdown
                md_content += f"- `{issue}`\n"
            if len(result.issues) > 20:
                md_content += f"\n... and {len(result.issues) - 20} more\n"
        else:
            md_content += "[OK] **No issues found**\n"

        md_content += "\n<details>\n<summary>Raw Output</summary>\n\n"
        md_content += "**STDOUT:**\n```\n"
        md_content += strip_ansi_codes(result.stdout) if result.stdout.strip() else "(empty)"
        md_content += "\n```\n\n**STDERR:**\n```\n"
        md_content += strip_ansi_codes(result.stderr) if result.stderr.strip() else "(empty)"
        md_content += "\n```\n</details>\n\n"

    return md_content


def render_json(results: list[AnalysisResult], timestamp: str, target: str) -> str:
    """Render results as JSON."""
    data = {
        "timestamp": timestamp,
        "target": target,
        "summary": {
            "total_issues": sum(len(r.issues) for r in results),
            "high_severity": sum(1 for r in results if r.severity == "high"),
            "medium_severity": sum(1 for r in results if r.severity == "medium"),
            "low_severity": sum(1 for r in results if r.severity == "low"),
        },
        "results": [
            {
                "name": r.name,
                "command": r.command,
                "returncode": r.returncode,
                "severity": r.severity,
                "summary": r.summary,
                "issue_count": len(r.issues),
                "issues": r.issues,
                "stdout": strip_ansi_codes(r.stdout),
                "stderr": strip_ansi_codes(r.stderr),
            }
            for r in results
        ],
    }
    return json.dumps(data, indent=2)


def print_summary_table(results: list[AnalysisResult]) -> None:
    """Print a concise summary table to stdout (for --no-save mode)."""
    print("\n" + "=" * 80)
    print("CODE QUALITY SUMMARY")
    print("=" * 80)

    # Stats
    total_issues = sum(len(r.issues) for r in results)
    high_severity = sum(1 for r in results if r.severity == "high")
    medium_severity = sum(1 for r in results if r.severity == "medium")
    low_severity = sum(1 for r in results if r.severity == "low")

    # Use ASCII-safe output for Windows console compatibility
    print("\nStatistics:")
    print(f"  Total Issues: {total_issues}")
    print(f"  High Severity: {high_severity}")
    print(f"  Medium Severity: {medium_severity}")
    print(f"  Low Severity: {low_severity}\n")

    # Table header
    print(f"{'Tool':<35} {'Severity':<12} {'Issues':<8} Summary")
    print("-" * 80)

    # Table rows
    for result in results:
        severity_indicator = {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(result.severity, "UNKNOWN")
        print(f"{result.name:<35} {severity_indicator:<12} {len(result.issues):<8} {result.summary}")

    print("=" * 80 + "\n")


# ──────────────────────────────────────────────────────────────────────
# Core Functions
# ──────────────────────────────────────────────────────────────────────


def run_command(cmd: list[str], description: str, tool_id: str = "") -> dict[str, Any]:
    """Run a command and capture output.

    Args:
        cmd: Command and arguments to execute
        description: Human-readable description of what the command does
        tool_id: Stable identifier for tool-specific parsing (e.g., "radon_cc", "flake8")

    Returns:
        Dictionary with command results and metadata
    """
    print(f"\n{'=' * 60}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print(f"{'=' * 60}\n")

    # Force UTF-8 encoding for subprocess output
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"  # Enable Python UTF-8 mode for child processes (Python 3.7+)
    env["PYTHONIOENCODING"] = "utf-8"

    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=120,
        )

        return {
            "tool": tool_id,
            "description": description,
            "command": " ".join(cmd),
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "success": result.returncode == 0,
        }
    except subprocess.TimeoutExpired:
        return {
            "tool": tool_id,
            "description": description,
            "command": " ".join(cmd),
            "returncode": -1,
            "stdout": "",
            "stderr": "Command timed out after 120 seconds",
            "success": False,
        }
    except Exception as e:
        return {
            "tool": tool_id,
            "description": description,
            "command": " ".join(cmd),
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "success": False,
        }


def main():
    """Run all slop/drift detection tools."""
    parser = argparse.ArgumentParser(description="Detect code quality issues (slop/drift)")
    parser.add_argument(
        "target",
        nargs="?",
        default=None,
        help="File or directory to scan (default: nomarr/)",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print to stdout only, don't save report files",
    )
    parser.add_argument(
        "--format",
        choices=["html", "md", "json"],
        default="html",
        help="Output format (default: html)",
    )
    args = parser.parse_args()

    # Determine target path
    if args.target:
        target_path = Path(args.target)
        if not target_path.is_absolute():
            target_path = ROOT / target_path
        if not target_path.exists():
            print(f"[ERROR] Error: Target does not exist: {target_path}")
            return 1
    else:
        target_path = NOMARR_DIR

    # Skip import-linter for single files (it's a whole-project check)
    run_import_linter = target_path.is_dir()

    if not args.no_save:
        REPORTS_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_name = (
        target_path.name if target_path.is_file() else target_path.relative_to(ROOT).as_posix().replace("/", "_")
    )

    # Use ASCII-safe output for Windows console compatibility
    print("Slop & Drift Detection")
    print(f"Timestamp: {timestamp}")
    print(f"Target: {target_path.relative_to(ROOT) if target_path.is_relative_to(ROOT) else target_path}")
    print(f"Format: {args.format}")

    # Collect raw command outputs
    raw_results = []

    # 1. Radon - Cyclomatic Complexity
    raw_results.append(
        run_command(
            [sys.executable, "-m", "radon", "cc", str(target_path), "-a", "-s"],
            "Radon: Cyclomatic Complexity",
            tool_id="radon_cc",
        )
    )

    # 2. Radon - Maintainability Index
    raw_results.append(
        run_command(
            [sys.executable, "-m", "radon", "mi", str(target_path), "-s"],
            "Radon: Maintainability Index",
            tool_id="radon_mi",
        )
    )

    # 3. Radon - Raw Metrics
    raw_results.append(
        run_command(
            [sys.executable, "-m", "radon", "raw", str(target_path), "-s"],
            "Radon: Raw Metrics",
            tool_id="radon_raw",
        )
    )

    # 4. Import Linter - Architecture Violations
    if run_import_linter:
        raw_results.append(
            run_command(
                ["lint-imports"],
                "Import Linter: Architecture violations",
                tool_id="import_linter",
            )
        )

    # 5. Flake8 - Code Smells
    raw_results.append(
        run_command(
            [
                sys.executable,
                "-m",
                "flake8",
                str(target_path),
                "--max-complexity",
                "20",
                "--max-cognitive-complexity",
                "20",
                "--extend-ignore",
                "E501,W503,E203",
            ],
            "Flake8: Code smells",
            tool_id="flake8",
        )
    )

    # 6. Flake8 - Strict Complexity
    raw_results.append(
        run_command(
            [
                sys.executable,
                "-m",
                "flake8",
                str(target_path),
                "--max-complexity",
                "15",
                "--max-cognitive-complexity",
                "15",
                "--select",
                "C901,CCR001",
                "--extend-ignore",
                "E501,W503,E203",
            ],
            "Flake8: Strict complexity check",
            tool_id="flake8_strict",
        )
    )

    # 7. Eradicate - Commented Code
    raw_results.append(
        run_command(
            [sys.executable, "-m", "eradicate", str(target_path), "--recursive"]
            if target_path.is_dir()
            else [sys.executable, "-m", "eradicate", str(target_path)],
            "Eradicate: Commented-out code",
            tool_id="eradicate",
        )
    )

    # Normalize raw results into structured AnalysisResult objects
    analyzed_results: list[AnalysisResult] = []

    for raw in raw_results:
        tool = raw.get("tool", "")
        name = raw["description"]
        stdout = raw["stdout"]
        stderr = raw["stderr"]
        returncode = raw["returncode"]

        # Dispatch on stable tool identifier instead of fuzzy name matching
        if tool == "radon_cc":
            issues, summary = normalize_radon_cc(stdout)
        elif tool == "radon_mi":
            issues, summary = normalize_radon_mi(stdout)
        elif tool == "radon_raw":
            # Raw metrics - just informational, no issues
            issues, summary = [], "Raw code metrics (informational)"
        elif tool == "import_linter":
            issues, summary = normalize_import_linter(stdout, stderr)
        elif tool == "flake8" or tool == "flake8_strict":
            issues, summary = normalize_flake8(stdout, stderr, returncode)
        elif tool == "eradicate":
            issues, summary = normalize_eradicate(stdout)
        else:
            # Unknown tool - generic handling
            issues, summary = [], "No issues detected"

        # Calculate severity
        severity = calculate_severity(name, issues, returncode)

        # Override severity for flake8 tool failures - these are high priority
        # because they indicate the quality signal is completely missing
        if (tool == "flake8" or tool == "flake8_strict") and returncode != 0 and not stdout.strip():
            severity = "high"

        analyzed_results.append(
            AnalysisResult(
                name=name,
                command=raw["command"],
                stdout=stdout,
                stderr=stderr,
                returncode=returncode,
                issues=issues,
                severity=severity,
                summary=summary,
            )
        )

    # Render output based on format
    if args.format == "html":
        output_content = render_html(analyzed_results, timestamp, str(target_path))
        file_ext = "html"
    elif args.format == "md":
        output_content = render_markdown(analyzed_results, timestamp, str(target_path))
        file_ext = "md"
    else:  # json
        output_content = render_json(analyzed_results, timestamp, str(target_path))
        file_ext = "json"

    # Output results
    if args.no_save:
        # Print summary table + content to stdout
        print_summary_table(analyzed_results)
        if args.format == "json":
            print(output_content)
        else:
            print("\nFull report:")
            print("=" * 80)
            # For console output, encode safely for Windows terminals
            try:
                print(output_content)
            except UnicodeEncodeError:
                # Fallback: replace emoji with ASCII equivalents
                safe_output = (
                    output_content.replace("🔴", "[HIGH]")
                    .replace("🟡", "[MEDIUM]")
                    .replace("🟢", "[LOW]")
                    .replace("⚪", "[UNKNOWN]")
                    .replace("✅", "[OK]")
                    .replace("📊", "Stats:")
                    .replace("🔍", "Report:")
                )
                print(safe_output)
    else:
        # Save to file
        report_file = REPORTS_DIR / f"slop_{target_name}_{timestamp}.{file_ext}"

        with open(report_file, "w", encoding="utf-8") as f:
            f.write(output_content)

        print(f"\n{'=' * 80}")
        print(f"[OK] Report saved to: {report_file}")
        print(f"{'=' * 80}\n")

        # Print summary
        print_summary_table(analyzed_results)

    # Return exit code based on high-severity issues
    high_severity_count = sum(1 for r in analyzed_results if r.severity == "high")
    if high_severity_count > 0:
        print(f"\nFound {high_severity_count} high-severity issue(s)")
        return 1

    print("\nNo high-severity issues found!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
