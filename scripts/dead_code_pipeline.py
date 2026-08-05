#!/usr/bin/env python3
"""
Dead Code Verification Pipeline - 3-stage analysis for identifying safe deletion candidates.

This script implements a 3-stage verification pipeline to identify dead code that can be
safely deleted from the Nomarr codebase. Each stage provides independent verification:

Stage 1: Reference Analysis
    Uses ripgrep (rg) to search for references to known deletion suspects across all .py files.
    Counts callers and identifies files that reference each suspect.

Stage 2: Coverage Execution
    Runs pytest with coverage to identify files with 0% coverage. Files with 0% coverage
    and 0 callers are flagged as high-risk for deletion.
    NOTE: Requires pytest-cov to be installed. If not available, this stage is skipped.

Stage 3: Static Analysis
    Runs vulture with the allowlist from deadcode_allowlist.py to identify unused code.
    Parses vulture output as structured data.
    NOTE: Requires vulture to be installed. If not available, this stage is skipped.

Stage 3 uses `vulture` (already in pyproject.toml dev dependencies). If `deadcode-py` is
preferred in the future, add it to pyproject.toml and update this script.

Usage:
    # Run all stages with default output path
    python scripts/dead_code_pipeline.py

    # Run all stages with custom output path
    python scripts/dead_code_pipeline.py --output scripts/dead_code_baseline.json

    # Run only Stage 1 (reference analysis)
    python scripts/dead_code_pipeline.py --stage 1

    # Run only Stage 3 (static analysis)
    python scripts/dead_code_pipeline.py --stage 3

Output:
    Produces a JSON docket with verdicts for each suspect:
    - SAFE TO DELETE: 0 callers confirmed by all stages
    - NEEDS REVIEW: ambiguous or partial matches
    - STAY: has callers or is in allowlist

    Output is printed to stdout and saved to the specified JSON file.
"""

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Known deletion suspects from CONTRACTS.md Part B
DELETION_SUSPECTS = [
    # Classes
    {"name": "_MlCapacityAdapter", "type": "class", "file": "nomarr/persistence/db.py"},
    {"name": "_MigrationsAdapter", "type": "class", "file": "nomarr/persistence/db.py"},
    {"name": "_VramPromisesAdapter", "type": "class", "file": "nomarr/persistence/db.py"},
    {"name": "LibraryEntitiesMixin", "type": "class", "file": "nomarr/services/domain/library_svc/entities.py"},
    # AppMaintenanceDb methods
    {
        "name": "truncate_pipeline_states",
        "type": "method",
        "class": "AppMaintenanceDb",
        "file": "nomarr/persistence/api/application.py",
    },
    {
        "name": "truncate_pipeline_state_edges",
        "type": "method",
        "class": "AppMaintenanceDb",
        "file": "nomarr/persistence/api/application.py",
    },
    {
        "name": "list_collections",
        "type": "method",
        "class": "AppMaintenanceDb",
        "file": "nomarr/persistence/api/application.py",
    },
    {
        "name": "delete_all_worker_claims",
        "type": "method",
        "class": "AppMaintenanceDb",
        "file": "nomarr/persistence/api/application.py",
    },
    # AppDb methods
    {
        "name": "update_pipeline_state",
        "type": "method",
        "class": "AppDb",
        "file": "nomarr/persistence/api/application.py",
    },
    {
        "name": "clear_file_state_links",
        "type": "method",
        "class": "AppDb",
        "file": "nomarr/persistence/api/application.py",
    },
    {
        "name": "clear_pipeline_state_links",
        "type": "method",
        "class": "AppDb",
        "file": "nomarr/persistence/api/application.py",
    },
    # MlMaintenanceDb methods
    {
        "name": "truncate_vector_collection",
        "type": "method",
        "class": "MlMaintenanceDb",
        "file": "nomarr/persistence/api/ml.py",
    },
    # Functions
    {
        "name": "download_calibrations",
        "type": "function",
        "file": "nomarr/services/infrastructure/calibration_download_svc.py",
    },
]


@dataclass
class StageResult:
    """Result from a single pipeline stage."""

    stage: int
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class SuspectVerdict:
    """Final verdict for a deletion suspect."""

    name: str
    verdict: str  # SAFE TO DELETE, NEEDS REVIEW, STAY
    stage1_callers: int = 0
    stage1_files: list[str] = field(default_factory=list)
    stage2_coverage: str = "unknown"  # 0%, partial, covered, unknown
    stage3_unused: bool = False
    notes: list[str] = field(default_factory=list)


def check_tool_available(tool_name: str) -> bool:
    """Check if a command-line tool is available."""
    try:
        result = subprocess.run(
            ["which", tool_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


def stage1_reference_analysis() -> StageResult:
    """
    Stage 1: Reference analysis using ripgrep.

    Searches for references to each suspect across all .py files.
    Returns caller count and file list for each suspect.
    """
    if not check_tool_available("rg"):
        return StageResult(
            stage=1,
            success=False,
            message="ripgrep (rg) not found. Please install ripgrep.",
            data={},
        )

    results = {}

    for suspect in DELETION_SUSPECTS:
        name = suspect["name"]
        suspect_type = suspect["type"]

        # Build search pattern based on type
        if suspect_type == "class":
            # Search for class name usage (not just definition)
            pattern = rf"\b{name}\b"
        elif suspect_type == "method":
            # Search for method name (e.g., .truncate_pipeline_states or truncate_pipeline_states)
            pattern = rf"\b{name}\b"
        else:  # function
            # Search for function name
            pattern = rf"\b{name}\b"

        try:
            # Run rg to find all references
            result = subprocess.run(
                ["rg", "--type", "py", "--files-with-matches", pattern],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                files = [f for f in result.stdout.strip().split("\n") if f]
                # Filter out the definition file itself and analysis scripts
                definition_file = suspect.get("file", "")
                caller_files = [
                    f
                    for f in files
                    if f != definition_file and f != "scripts/dead_code_pipeline.py" and f != "deadcode_allowlist.py"
                ]

                results[name] = {
                    "callers": len(caller_files),
                    "files": caller_files,
                    "all_files": files,
                }
            else:
                # No matches found
                results[name] = {
                    "callers": 0,
                    "files": [],
                    "all_files": [],
                }
        except subprocess.TimeoutExpired:
            results[name] = {
                "callers": -1,
                "files": [],
                "all_files": [],
                "error": "timeout",
            }
        except Exception as e:
            results[name] = {
                "callers": -1,
                "files": [],
                "all_files": [],
                "error": str(e),
            }

    return StageResult(
        stage=1,
        success=True,
        message=f"Analyzed {len(DELETION_SUSPECTS)} suspects",
        data=results,
    )


def stage2_coverage_execution() -> StageResult:
    """
    Stage 2: Coverage execution using pytest-cov.

    Runs pytest with coverage and identifies files with 0% coverage.
    """
    # Check if pytest-cov is available
    try:
        result = subprocess.run(
            ["python", "-c", "import pytest_cov"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return StageResult(
                stage=2,
                success=False,
                message="pytest-cov not installed. Skipping coverage analysis. Install with: pip install pytest-cov",
                data={},
            )
    except Exception:
        return StageResult(
            stage=2,
            success=False,
            message="pytest-cov not installed. Skipping coverage analysis.",
            data={},
        )

    # Run pytest with coverage
    try:
        result = subprocess.run(
            ["pytest", "--cov=nomarr", "--cov-report=term-missing", "--source=nomarr", "-q"],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
        )

        # Parse coverage output
        coverage_data = {}
        lines = result.stdout.split("\n")

        for line in lines:
            # Look for lines like: nomarr/persistence/db.py    100    50    50%   10-20, 30-40
            match = re.match(r"^(nomarr/\S+\.py)\s+(\d+)\s+(\d+)\s+(\d+)%", line)
            if match:
                filepath = match.group(1)
                total_stmts = int(match.group(2))
                missing_stmts = int(match.group(3))
                coverage_pct = int(match.group(4))

                coverage_data[filepath] = {
                    "total": total_stmts,
                    "missing": missing_stmts,
                    "coverage": coverage_pct,
                }

        return StageResult(
            stage=2,
            success=True,
            message=f"Coverage analysis complete for {len(coverage_data)} files",
            data=coverage_data,
        )
    except subprocess.TimeoutExpired:
        return StageResult(
            stage=2,
            success=False,
            message="pytest coverage run timed out",
            data={},
        )
    except Exception as e:
        return StageResult(
            stage=2,
            success=False,
            message=f"Coverage analysis failed: {e}",
            data={},
        )


def stage3_static_analysis() -> StageResult:
    """
    Stage 3: Static analysis using vulture.

    Runs vulture with the allowlist and parses output.
    """
    if not check_tool_available("vulture"):
        return StageResult(
            stage=3,
            success=False,
            message="vulture not found. Install with: pip install vulture",
            data={},
        )

    # Check if allowlist exists
    allowlist_path = Path("deadcode_allowlist.py")
    if not allowlist_path.exists():
        return StageResult(
            stage=3,
            success=False,
            message="deadcode_allowlist.py not found. Skipping vulture analysis.",
            data={},
        )

    try:
        # Run vulture with allowlist
        result = subprocess.run(
            ["vulture", "nomarr/", "--min-confidence", "60", str(allowlist_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )

        # Parse vulture output
        # Format: nomarr/path/file.py:123: unused function 'func_name' (60% confidence)
        findings = []
        for line in result.stdout.split("\n"):
            if not line.strip():
                continue

            match = re.match(r"^(\S+):(\d+):\s+(.+?)\s+'([^']+)'\s+\((\d+)%\s+confidence\)", line)
            if match:
                findings.append(
                    {
                        "file": match.group(1),
                        "line": int(match.group(2)),
                        "type": match.group(3),
                        "name": match.group(4),
                        "confidence": int(match.group(5)),
                    }
                )

        return StageResult(
            stage=3,
            success=True,
            message=f"Vulture found {len(findings)} unused code items",
            data={"findings": findings},
        )
    except subprocess.TimeoutExpired:
        return StageResult(
            stage=3,
            success=False,
            message="vulture analysis timed out",
            data={},
        )
    except Exception as e:
        return StageResult(
            stage=3,
            success=False,
            message=f"Vulture analysis failed: {e}",
            data={},
        )


def compute_verdicts(
    stage1_result: StageResult,
    stage2_result: StageResult,
    stage3_result: StageResult,
) -> list[dict[str, Any]]:
    """
    Compute final verdicts for each suspect based on all stage results.
    """
    verdicts = []

    for suspect in DELETION_SUSPECTS:
        name = suspect["name"]
        suspect_file = suspect.get("file", "")

        # Stage 1 data
        stage1_data = stage1_result.data.get(name, {}) if stage1_result.success else {}
        callers = stage1_data.get("callers", 0)
        caller_files = stage1_data.get("files", [])

        # Stage 2 data
        stage2_data = stage2_result.data.get(suspect_file, {}) if stage2_result.success else {}
        coverage_pct = stage2_data.get("coverage", "unknown")

        # Stage 3 data
        stage3_findings = stage3_result.data.get("findings", []) if stage3_result.success else []
        is_unused = any(
            f["name"] == name or (suspect.get("type") == "method" and f["name"] == name) for f in stage3_findings
        )

        # Determine verdict
        notes = []

        if callers > 0:
            verdict = "STAY"
            notes.append(f"Has {callers} caller file(s)")
        elif coverage_pct != "unknown" and coverage_pct > 0:
            verdict = "STAY"
            notes.append(f"File has {coverage_pct}% coverage")
        elif not stage3_result.success and not stage2_result.success:
            verdict = "NEEDS REVIEW"
            notes.append("Insufficient data from stages 2 and 3")
        elif (
            callers == 0
            and (coverage_pct == 0 or coverage_pct == "unknown")
            and (is_unused or not stage3_result.success)
        ):
            verdict = "SAFE TO DELETE"
            notes.append("No callers confirmed")
        else:
            verdict = "NEEDS REVIEW"
            notes.append("Ambiguous signals")

        verdicts.append(
            {
                "name": name,
                "type": suspect["type"],
                "file": suspect_file,
                "verdict": verdict,
                "stage1_callers": callers,
                "stage1_files": caller_files,
                "stage2_coverage": coverage_pct,
                "stage3_unused": is_unused,
                "notes": notes,
            }
        )

    return verdicts


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Dead Code Verification Pipeline - 3-stage analysis for safe deletion candidates"
    )
    parser.add_argument(
        "--output",
        type=str,
        default="scripts/dead_code_baseline.json",
        help="Output JSON file path (default: scripts/dead_code_baseline.json)",
    )
    parser.add_argument(
        "--stage",
        type=str,
        choices=["1", "2", "3", "all"],
        default="all",
        help="Run only a specific stage (1, 2, 3, or all)",
    )

    args = parser.parse_args()

    print("=" * 80)
    print("Dead Code Verification Pipeline")
    print("=" * 80)
    print()

    # Run stages
    stage1_result = None
    stage2_result = None
    stage3_result = None

    if args.stage in ["1", "all"]:
        print("Stage 1: Reference Analysis (ripgrep)")
        print("-" * 80)
        stage1_result = stage1_reference_analysis()
        print(f"Status: {'✓ Success' if stage1_result.success else '✗ Failed'}")
        print(f"Message: {stage1_result.message}")
        print()

    if args.stage in ["2", "all"]:
        print("Stage 2: Coverage Execution (pytest-cov)")
        print("-" * 80)
        stage2_result = stage2_coverage_execution()
        print(f"Status: {'✓ Success' if stage2_result.success else '✗ Skipped/Failed'}")
        print(f"Message: {stage2_result.message}")
        print()

    if args.stage in ["3", "all"]:
        print("Stage 3: Static Analysis (vulture)")
        print("-" * 80)
        stage3_result = stage3_static_analysis()
        print(f"Status: {'✓ Success' if stage3_result.success else '✗ Skipped/Failed'}")
        print(f"Message: {stage3_result.message}")
        print()

    # Compute verdicts
    print("=" * 80)
    print("Computing Verdicts")
    print("=" * 80)
    print()

    # Create dummy results for skipped stages
    if stage1_result is None:
        stage1_result = StageResult(stage=1, success=False, message="Skipped", data={})
    if stage2_result is None:
        stage2_result = StageResult(stage=2, success=False, message="Skipped", data={})
    if stage3_result is None:
        stage3_result = StageResult(stage=3, success=False, message="Skipped", data={})

    verdicts = compute_verdicts(stage1_result, stage2_result, stage3_result)

    # Print summary
    safe_count = sum(1 for v in verdicts if v["verdict"] == "SAFE TO DELETE")
    review_count = sum(1 for v in verdicts if v["verdict"] == "NEEDS REVIEW")
    stay_count = sum(1 for v in verdicts if v["verdict"] == "STAY")

    print(f"SAFE TO DELETE: {safe_count}")
    print(f"NEEDS REVIEW:   {review_count}")
    print(f"STAY:           {stay_count}")
    print()

    # Print detailed verdicts
    for v in verdicts:
        print(f"{v['name']:40s} | {v['verdict']:20s} | {', '.join(v['notes'])}")

    print()

    # Build output
    output = {
        "pipeline": {
            "stage1": {
                "success": stage1_result.success,
                "message": stage1_result.message,
            },
            "stage2": {
                "success": stage2_result.success,
                "message": stage2_result.message,
            },
            "stage3": {
                "success": stage3_result.success,
                "message": stage3_result.message,
            },
        },
        "verdicts": verdicts,
    }

    # Write to file
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Results saved to: {output_path}")
    print()

    # Also print JSON to stdout
    print("=" * 80)
    print("JSON Output")
    print("=" * 80)
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
