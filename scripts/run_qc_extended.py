"""Extended QC checks that require ML dependencies.

Run this script INSIDE the Docker container where essentia-tensorflow is available.
Do NOT run on Windows dev machine (will fail due to missing essentia).

Usage:
  docker exec nomarr python3 scripts/run_qc_extended.py
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(cmd: list[str], description: str) -> tuple[str, int]:
    """Run a command and capture output.

    Args:
        cmd: Command and arguments
        description: Human-readable description

    Returns:
        Tuple of (output, return_code)

    """
    print(f"\n{'=' * 80}")
    print(f"Running: {description}")
    print(f"Command: {' '.join(cmd)}")
    print("=" * 80)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )

    output = result.stdout + result.stderr
    print(output)

    return output, result.returncode


def check_tool_available(tool: str) -> bool:
    """Check if a tool is available."""
    result = subprocess.run(
        [sys.executable, "-m", tool, "--version"],
        capture_output=True,
    )
    return result.returncode == 0


def main():
    """Run extended QC checks (requires ML dependencies)."""
    # Create reports directory
    reports_dir = Path("/app/qc_reports")
    reports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_file = reports_dir / f"{timestamp}_qc_extended.txt"

    # Collect all results
    results = []
    results.append("=" * 80)
    results.append(f"Nomarr Extended QC Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    results.append("Requires: essentia-tensorflow and all ML dependencies")
    results.append("=" * 80)
    results.append("")

    # 1. Type checking with mypy
    if check_tool_available("mypy"):
        output, code = run_command(
            [sys.executable, "-m", "mypy", "nomarr/", "--ignore-missing-imports"], "Type Checking (mypy)",
        )
        results.append("## 1. Type Checking (mypy)")
        results.append(output)
        results.append(f"Exit code: {code}")
        results.append("")
    else:
        results.append("## 1. Type Checking (mypy)")
        results.append("[WARNING] mypy not installed. Install with: pip install mypy")
        results.append("")

    # 2. Security scanning with bandit
    if check_tool_available("bandit"):
        output, code = run_command(
            [sys.executable, "-m", "bandit", "-r", "nomarr/", "-ll"], "Security Scanning (bandit)",
        )
        results.append("## 2. Security Scanning (bandit)")
        results.append(output)
        results.append(f"Exit code: {code}")
        results.append("")
    else:
        results.append("## 2. Security Scanning (bandit)")
        results.append("[WARNING] bandit not installed. Install with: pip install bandit")
        results.append("")

    # 3. Dead code detection with vulture
    if check_tool_available("vulture"):
        output, code = run_command(
            [sys.executable, "-m", "vulture", "nomarr/", "--min-confidence", "80"], "Dead Code Detection (vulture)",
        )
        results.append("## 3. Dead Code Detection (vulture)")
        results.append(output)
        results.append(f"Exit code: {code}")
        results.append("")
    else:
        results.append("## 3. Dead Code Detection (vulture)")
        results.append("[WARNING] vulture not installed. Install with: pip install vulture")
        results.append("")

    # 4. Test coverage
    output, code = run_command(
        [
            sys.executable,
            "-m",
            "pytest",
            "--cov=nomarr",
            "--cov-report=term",
            "-m",
            "not gpu_required and not container_only",
        ],
        "Test Coverage",
    )
    results.append("## 4. Test Coverage")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # Write report
    report_content = "\n".join(results)
    report_file.write_text(report_content, encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"Extended QC Report saved to: {report_file}")
    print("=" * 80)

    return 0


if __name__ == "__main__":
    # Verify we're in container
    if not Path("/app/nomarr").exists():
        print("ERROR: This script must be run inside the Docker container")
        print("Usage: docker exec nomarr python3 scripts/run_qc_extended.py")
        sys.exit(1)

    sys.exit(main())
