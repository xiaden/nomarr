"""
Automated QC (Quality Control) runner.

Runs all automated code quality checks and generates a report.
Includes: naming conventions, linting, type checking, security scanning, dead code detection.
"""

import subprocess
import sys
from datetime import datetime
from pathlib import Path


def run_command(cmd: list[str], description: str) -> tuple[str, int]:
    """
    Run a command and capture output.

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


def main():
    """Run all QC checks and generate report."""
    # Create reports directory
    reports_dir = Path("qc_reports")
    reports_dir.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_file = reports_dir / f"{timestamp}_qc_report.txt"

    # Collect all results
    results = []
    results.append("=" * 80)
    results.append(f"Nomarr QC Report - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    results.append("=" * 80)
    results.append("")

    # 1. Naming conventions
    output, code = run_command([sys.executable, "scripts/check_naming.py"], "Naming Convention Check")
    results.append("## 1. Naming Conventions")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 2. Linting (ruff)
    output, code = run_command(["ruff", "check", "."], "Ruff Linting")
    results.append("## 2. Linting (Ruff)")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 3. Import organization
    output, code = run_command([sys.executable, "scripts/discover_imports.py"], "Import Analysis")
    results.append("## 3. Import Analysis")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 4. Type checking (mypy)
    output, code = run_command(["mypy", "nomarr/", "--ignore-missing-imports"], "Type Checking (mypy)")
    results.append("## 4. Type Checking (mypy)")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 5. Security scanning (bandit)
    output, code = run_command(["bandit", "-r", "nomarr/", "-f", "txt"], "Security Scan (bandit)")
    results.append("## 5. Security Scan (bandit)")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 6. Dead code detection (vulture)
    output, code = run_command(["vulture", "nomarr/", "--min-confidence", "80"], "Dead Code Detection (vulture)")
    results.append("## 6. Dead Code Detection (vulture)")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 7. Test discovery (count tests)
    output, code = run_command([sys.executable, "-m", "pytest", "--collect-only", "-q"], "Test Discovery")
    results.append("## 7. Test Discovery")
    results.append(output)
    results.append(f"Exit code: {code}")
    results.append("")

    # 8. File statistics
    results.append("## 8. Codebase Statistics")
    py_files = list(Path("nomarr").rglob("*.py"))
    test_files = list(Path("tests").rglob("*.py"))
    results.append(f"Python files in nomarr/: {len(py_files)}")
    results.append(f"Test files in tests/: {len(test_files)}")
    results.append("")

    # Write report
    report_content = "\n".join(results)
    report_file.write_text(report_content, encoding="utf-8")

    print("\n" + "=" * 80)
    print(f"QC Report saved to: {report_file}")
    print("=" * 80)

    # Summary
    print("\n## QC Summary")
    print("✅ Naming conventions check complete")
    print("✅ Linting check complete")
    print("✅ Import analysis complete")
    print("✅ Type checking complete")
    print("✅ Security scan complete")
    print("✅ Dead code detection complete")
    print("✅ Test discovery complete")
    print("\nReview the full report for details.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
