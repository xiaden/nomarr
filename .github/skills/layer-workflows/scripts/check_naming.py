#!/usr/bin/env python3
"""Check naming conventions for workflows layer.

Rules:
- Files must end in `_wf.py`
- One public workflow function per file (verb_object_workflow)
- File names describe one use case (verb_object pattern)
- Private helpers start with underscore
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

LAYER_PATH = Path("nomarr/workflows")
FILE_SUFFIX = "_wf.py"
WORKFLOW_FUNC_PATTERN = re.compile(r"^[a-z][a-z0-9_]*_workflow$")


def check_file_naming(file_path: Path) -> list[str]:
    """Check that file follows naming conventions."""
    errors: list[str] = []

    # Skip __init__.py and non-Python files
    if file_path.name == "__init__.py":
        return errors

    if not file_path.name.endswith(FILE_SUFFIX):
        errors.append(f"{file_path}: File must end with '{FILE_SUFFIX}'")

    return errors


def check_workflow_functions(file_path: Path) -> list[str]:
    """Check that file has exactly one public workflow function."""
    errors: list[str] = []

    if file_path.name == "__init__.py":
        return errors

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError as e:
        errors.append(f"{file_path}: Syntax error - {e}")
        return errors

    public_functions: list[str] = []
    workflow_functions: list[str] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            # Only top-level functions
            if not node.name.startswith("_"):
                public_functions.append(node.name)
                if WORKFLOW_FUNC_PATTERN.match(node.name):
                    workflow_functions.append(node.name)

    if len(workflow_functions) == 0:
        errors.append(f"{file_path}: No public *_workflow function found")
    elif len(workflow_functions) > 1:
        errors.append(f"{file_path}: Multiple workflow functions found: {workflow_functions}. One workflow per file.")

    # Check for non-workflow public functions (should be private)
    non_workflow_public = [f for f in public_functions if f not in workflow_functions]
    if non_workflow_public:
        errors.append(f"{file_path}: Non-workflow public functions should be private: {non_workflow_public}")

    return errors


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    layer_path = repo_root / LAYER_PATH

    if not layer_path.exists():
        print(f"Layer path not found: {layer_path}", file=sys.stderr)
        return 1

    all_errors: list[str] = []

    for py_file in layer_path.rglob("*.py"):
        all_errors.extend(check_file_naming(py_file))
        all_errors.extend(check_workflow_functions(py_file))

    if all_errors:
        print("Workflow naming violations:\n")
        for error in all_errors:
            print(f"  ❌ {error}")
        print(f"\n{len(all_errors)} error(s) found.")
        return 1

    print("✅ All workflow naming checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
