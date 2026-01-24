#!/usr/bin/env python3
"""Check naming conventions for components layer.

Rules:
- Component files must end in `_comp.py`
- Only ml/ml_backend_essentia_comp.py may import essentia
"""

import ast
import sys
from pathlib import Path

LAYER_PATH = Path("nomarr/components")
COMPONENT_SUFFIX = "_comp.py"
ALLOWED_FILES = {"__init__.py"}
ESSENTIA_ALLOWED_FILE = "ml_backend_essentia_comp.py"


def check_file_naming(file_path: Path) -> list[str]:
    """Check that file follows naming conventions."""
    errors: list[str] = []

    if file_path.name in ALLOWED_FILES:
        return errors

    if not file_path.name.endswith(COMPONENT_SUFFIX):
        errors.append(f"{file_path}: Component files must end with '{COMPONENT_SUFFIX}'")

    return errors


def check_essentia_imports(file_path: Path) -> list[str]:
    """Check that only ml_backend_essentia_comp.py imports essentia."""
    errors: list[str] = []

    if file_path.name == ESSENTIA_ALLOWED_FILE:
        return errors

    try:
        content = file_path.read_text(encoding="utf-8")
        tree = ast.parse(content, filename=str(file_path))
    except SyntaxError:
        return errors

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "essentia" in alias.name.lower():
                    errors.append(f"{file_path}: Essentia import only allowed in {ESSENTIA_ALLOWED_FILE}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and "essentia" in node.module.lower():
                errors.append(f"{file_path}: Essentia import only allowed in {ESSENTIA_ALLOWED_FILE}")

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
        errors.extend(check_essentia_imports(py_file))

    if errors:
        print("Naming violations found:\n")
        for error in errors:
            print(f"  {error}")
        return 1

    print("✅ All component files follow naming conventions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
