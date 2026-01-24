#!/usr/bin/env python3
"""Check naming conventions for interfaces layer.

Rules:
- API route files must end in `_if.py`
- Router files can be `router.py`
- Dependencies can be `dependencies.py`
- Auth can be `auth.py`
"""

import sys
from pathlib import Path

LAYER_PATH = Path("nomarr/interfaces")
INTERFACE_SUFFIX = "_if.py"
ALLOWED_FILES = {"__init__.py", "router.py", "dependencies.py", "auth.py", "api_app.py", "id_codec.py"}


def check_file_naming(file_path: Path) -> list[str]:
    """Check that file follows naming conventions."""
    errors: list[str] = []

    if file_path.name in ALLOWED_FILES:
        return errors

    # Skip non-Python files
    if not file_path.suffix == ".py":
        return errors

    # Files in api/web/ and api/v1/ should end in _if.py
    if "api" in file_path.parts:
        if not file_path.name.endswith(INTERFACE_SUFFIX):
            # Allow types/ directory files
            if "types" not in file_path.parts:
                errors.append(f"{file_path}: Interface files must end with '{INTERFACE_SUFFIX}'")

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

    if errors:
        print("Naming violations found:\n")
        for error in errors:
            print(f"  {error}")
        return 1

    print("✅ All interface files follow naming conventions.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
