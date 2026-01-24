#!/usr/bin/env python3
"""Check naming conventions for helpers layer.

Rules:
- Files should end in `_helper.py` (except dto/, exceptions.py, dataclasses.py)
- DTOs go in dto/ subdirectory with `_dto.py` suffix
- Pure utility functions, no classes with state
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

LAYER_PATH = Path("nomarr/helpers")
HELPER_SUFFIX = "_helper.py"
DTO_SUFFIX = "_dto.py"
ALLOWED_NON_SUFFIX_FILES = {"__init__.py", "exceptions.py", "dataclasses.py"}


def check_file_naming(file_path: Path) -> list[str]:
    """Check that file follows naming conventions."""
    errors: list[str] = []

    if file_path.name in ALLOWED_NON_SUFFIX_FILES:
        return errors

    # Check if in dto directory
    if "dto" in file_path.parts:
        if not file_path.name.endswith(DTO_SUFFIX) and file_path.name != "__init__.py":
            errors.append(f"{file_path}: DTO files must end with '{DTO_SUFFIX}'")
    else:
        if not file_path.name.endswith(HELPER_SUFFIX):
            errors.append(f"{file_path}: Helper files must end with '{HELPER_SUFFIX}'")

    return errors


def check_no_stateful_classes(file_path: Path) -> list[str]:
    """Check that classes don't have __init__ that stores state (except dataclasses)."""
    errors: list[str] = []

    if file_path.name == "__init__.py":
        return errors

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return errors

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            # Check if it's a dataclass (has @dataclass decorator)
            is_dataclass = False
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Name) and decorator.id == "dataclass":
                    is_dataclass = True
                elif isinstance(decorator, ast.Call):
                    if isinstance(decorator.func, ast.Name) and decorator.func.id == "dataclass":
                        is_dataclass = True

            if is_dataclass:
                continue

            # Check for __init__ that assigns self attributes
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    for stmt in ast.walk(item):
                        if isinstance(stmt, ast.Assign):
                            for target in stmt.targets:
                                if isinstance(target, ast.Attribute):
                                    if isinstance(target.value, ast.Name) and target.value.id == "self":
                                        errors.append(
                                            f"{file_path}: Class '{node.name}' stores state. "
                                            "Helpers should be stateless utilities."
                                        )
                                        break

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
        all_errors.extend(check_no_stateful_classes(py_file))

    if all_errors:
        print("Helper naming violations:\n")
        for error in all_errors:
            print(f"  ❌ {error}")
        print(f"\n{len(all_errors)} error(s) found.")
        return 1

    print("✅ All helper naming checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
