"""
Output and reporting utilities.
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from .model import DataclassInfo, ImportEdge, MissingDataclassCandidate


def write_json_output(
    dataclasses: list[DataclassInfo],
    suspect_imports: list[ImportEdge],
    missing_candidates: list[MissingDataclassCandidate],
    output_path: Path,
    project_root: Path,
) -> None:
    """
    Write classification results to JSON file and print to stdout.

    Args:
        dataclasses: List of classified DataclassInfo objects
        suspect_imports: List of suspect import edges
        missing_candidates: List of missing dataclass candidates
        output_path: Path to output JSON file
        project_root: Root directory of the project
    """
    data = {
        "dataclasses": [dc.to_dict(project_root) for dc in dataclasses],
        "suspect_imports": [edge.to_dict() for edge in suspect_imports],
        "missing_dataclasses": [candidate.to_dict(project_root) for candidate in missing_candidates],
        "summary": {
            "total_dataclasses": len(dataclasses),
            "total_suspect_imports": len(suspect_imports),
            "total_missing_dataclasses": len(missing_candidates),
            "by_classification": {},
        },
    }

    # Count by classification
    classification_counts: dict[str, int] = defaultdict(int)
    for dc in dataclasses:
        classification_counts[dc.classification] += 1

    data["summary"]["by_classification"] = classification_counts  # type: ignore[index]

    # Write to file
    json_output = json.dumps(data, indent=2)
    output_path.write_text(json_output, encoding="utf-8")

    # Print to stdout
    print(json_output)
    print(f"\nJSON output written to: {output_path}", file=sys.stderr)


def print_summary(
    dataclasses: list[DataclassInfo],
    suspect_imports: list[ImportEdge],
    missing_candidates: list[MissingDataclassCandidate],
) -> None:
    """
    Print human-readable summary to stdout.

    Args:
        dataclasses: List of classified DataclassInfo objects
        suspect_imports: List of suspect import edges
        missing_candidates: List of missing dataclass candidates
    """
    # Group by classification
    by_classification: dict[str, list[DataclassInfo]] = defaultdict(list)
    for dc in dataclasses:
        by_classification[dc.classification].append(dc)

    print("\n" + "=" * 80)
    print("DATACLASS CLASSIFICATION SUMMARY")
    print("=" * 80 + "\n")

    print(f"Total dataclasses found: {len(dataclasses)}\n")

    # Define display order
    classification_order = [
        "Cross-Layer DTO",
        "Service-Local Config",
        "Workflow-Local Helper",
        "Domain-Internal Helper",
        "Persistence Model",
        "Cross-Domain Helper",
        "Ambiguous",
        "Ignored",
    ]

    for classification in classification_order:
        items = by_classification.get(classification, [])
        if not items:
            continue

        print(f"\n{classification} ({len(items)}):")
        print("-" * 80)

        for dc in sorted(items, key=lambda x: x.name):
            print(f"\n  • {dc.name}")
            print(f"    Module: {dc.defining_module}")
            if dc.imported_by_modules:
                print(f"    Used by: {', '.join(sorted(dc.imported_by_packages))}")
                if dc.ignored_import_count > 0:
                    print(f"    (ignored {dc.ignored_import_count} import(s) from config)")
            else:
                if dc.ignored_import_count > 0:
                    print(f"    Used by: (none - ignored {dc.ignored_import_count} import(s) from config)")
                else:
                    print("    Used by: (none - local only)")
            print(f"    Suggested: {dc.suggested_target}")
            if dc.notes:
                print(f"    Notes: {dc.notes}")

    # Print suspect imports section
    print("\n" + "=" * 80)
    print("SUSPECT IMPORTS")
    print("=" * 80 + "\n")

    if suspect_imports:
        print(f"Found {len(suspect_imports)} suspect import(s) based on allowed_imports config:\n")
        for edge in suspect_imports:
            print(f"  • {edge.importer_module}")
            print(f"    [{edge.importer_layer}] → [{edge.imported_layer}]")
            print(f"    imports from: {edge.imported_module}\n")
    else:
        print("Suspect imports: none (or allowed_imports not configured)\n")

    # Print missing dataclass candidates section
    print("\n" + "=" * 80)
    print("MISSING DATACLASS / DTO CANDIDATES")
    print("=" * 80 + "\n")

    if missing_candidates:
        # Separate public and private functions
        public_candidates = [c for c in missing_candidates if not c.is_private]
        private_candidates = [c for c in missing_candidates if c.is_private]

        print(f"Found {len(missing_candidates)} function(s) that might benefit from dataclasses:\n")

        # Print public functions first
        if public_candidates:
            print(f"Public API suggestions ({len(public_candidates)}):")
            print("-" * 80 + "\n")
            for candidate in public_candidates:
                print(f"  • {candidate.module}.{candidate.function}")
                print(f"    Layer: {candidate.layer}, Domain: {candidate.domain}")
                print(f"    Reason: {candidate.reason}")
                print(f"    Suggested: {candidate.suggested_name}")
                if candidate.fields:
                    print(f"    Fields: {', '.join(candidate.fields)}")
                else:
                    print("    Fields: (none)")
                print()

        # Print private functions separately
        if private_candidates:
            print(f"\nPrivate helper suggestions ({len(private_candidates)}):")
            print("-" * 80 + "\n")
            for candidate in private_candidates:
                print(f"  • {candidate.module}.{candidate.function}")
                print(f"    Layer: {candidate.layer}, Domain: {candidate.domain}")
                print(f"    Reason: {candidate.reason}")
                print(f"    Suggested: {candidate.suggested_name}")
                if candidate.fields:
                    print(f"    Fields: {', '.join(candidate.fields)}")
                else:
                    print("    Fields: (none)")
                print()
    else:
        print("None detected.\n")

    print("=" * 80)
    print("END OF SUMMARY")
    print("=" * 80 + "\n")


def write_text_output(
    dataclasses: list[DataclassInfo],
    suspect_imports: list[ImportEdge],
    missing_candidates: list[MissingDataclassCandidate],
    output_path: Path,
) -> None:
    """
    Write human-readable summary to text file and print to stdout.

    Args:
        dataclasses: List of classified DataclassInfo objects
        suspect_imports: List of suspect import edges
        missing_candidates: List of missing dataclass candidates
        output_path: Path to output text file
    """
    # Print to stdout
    print_summary(dataclasses, suspect_imports, missing_candidates)

    # Also write to file
    original_stdout = sys.stdout
    with output_path.open("w", encoding="utf-8") as f:
        sys.stdout = f
        print_summary(dataclasses, suspect_imports, missing_candidates)
        sys.stdout = original_stdout
    print(f"\nText output written to: {output_path}", file=sys.stderr)
