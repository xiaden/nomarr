#!/usr/bin/env python3
"""Check naming conventions for persistence layer.

Rules:
- Database operation files must end in `_aql.py`
- Operations classes named `<Collection>Operations`
"""

import ast
import re
import sys
from pathlib import Path

LAYER_PATH = Path("nomarr/persistence")
AQL_SUFFIX = "_aql.py"
ALLOWED_FILES = {"__init__.py", "db.py", "arango_client.py"}
OPERATIONS_CLASS_PATTERN = re.compile(r"^[A-Z][a-zA-Z0-9]*Operations$")


def check_file_naming(file_path: Path) -> list[str]:
    """Check that file follows naming conventions."""
    errors: list[str] = []

    if file_path.name in ALLOWED_FILES:
        return errors

    # Only check files in database/ subdirectory
    if "database" not in file_path.parts:
        return errors

    if not file_path.name.endswith(AQL_SUFFIX):
        errors.append(f"{file_path}: Database files must end with '{AQL_SUFFIX}'")

    return errors


def check_operations_classes(file_path: Path) -> list[str]:
    """Check that operations classes follow naming convention."""
    errors: list[str] = []

    if file_path.name == "__init__.py":
        return errors

    if "database" not in file_path.parts:
        return errors

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return errors

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if not node.name.startswith("_"):
                if "Operations" in node.name and not OPERATIONS_CLASS_PATTERN.match(node.name):
                    errors.append(f"{file_path}: Class '{node.name}' should match pattern '<Collection>Operations'")

    return errors


def main() -> int:
    repo_root = Path(__file__).parent.parent.parent.parent.parent
    layer_path = repo_root / LAYER_PATH

    if not layer_path.exists():
        print(f"Layer path not found: {layer_path}", file=sys.stderr)
        return 1

    errors: list[str] = []

    for py_file in layer_path.rglob("*.py"):
        errors.extend(check_file_naming(py_file))
        errors.extend(check_operations_classes(py_file))

    if errors:
        print("Naming violations found:\n")
        for error in errors:
            print(f"  {error}")
        return 1

    print("✅ All persistence files follow naming conventions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
