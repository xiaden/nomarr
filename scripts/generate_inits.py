#!/usr/bin/env python3
"""
Auto-generate __init__.py files with proper __all__ exports.
Scans Python modules and generates clean __init__.py files.
"""

import ast
import sys
from pathlib import Path


def get_public_names(file_path: Path) -> set[str]:
    """Extract public class/function names from a Python file (top-level only)."""
    try:
        with open(file_path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=str(file_path))
    except Exception as e:
        print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
        return set()

    names = set()
    # Only look at top-level nodes (module body), not nested functions/classes
    for node in tree.body:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            if not node.name.startswith("_"):  # Skip private
                names.add(node.name)
        elif isinstance(node, ast.Assign):
            # Module-level constants (ALL_CAPS, but not private)
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.isupper() and not target.id.startswith("_"):
                    names.add(target.id)

    return names


def generate_init_for_package(package_dir: Path, custom_exports: dict[str, list[str]] | None = None) -> str:
    """Generate __init__.py content for a package directory."""
    custom_exports = custom_exports or {}
    module_name = package_dir.name

    # If custom exports defined, use them
    if str(package_dir.relative_to(Path.cwd())) in custom_exports:
        exports = custom_exports[str(package_dir.relative_to(Path.cwd()))]
        imports = []
        for export in sorted(exports):
            # Determine which module it comes from (simplified - assumes single source)
            imports.append(f"from .{export.lower()} import {export}")

        lines = ['"""', f"{module_name.replace('_', ' ').title()} package.", '"""', ""]
        lines.extend(imports)
        lines.append("")
        lines.append(f"__all__ = {sorted(exports)}")
        return "\n".join(lines) + "\n"

    # Otherwise, scan for public exports
    py_files = [f for f in package_dir.glob("*.py") if f.name != "__init__.py" and not f.name.startswith("_")]

    if not py_files:
        return '"""Package."""\n'

    all_exports = {}
    for py_file in py_files:
        module_name_inner = py_file.stem
        names = get_public_names(py_file)
        if names:
            all_exports[module_name_inner] = sorted(names)

    if not all_exports:
        return '"""Package."""\n'

    # Build imports
    lines = ['"""', f"{module_name.replace('_', ' ').title()} package.", '"""', ""]

    for module, names in sorted(all_exports.items()):
        lines.append(f"from .{module} import {', '.join(names)}")

    # Build __all__
    all_names = []
    for names in all_exports.values():
        all_names.extend(names)

    lines.append("")
    lines.append(f"__all__ = {sorted(set(all_names))}")

    return "\n".join(lines) + "\n"


def find_all_packages(root: Path, exclude: set[str] | None = None) -> list[Path]:
    """Recursively find all Python packages (directories with .py files)."""
    exclude = exclude or set()
    packages = []
    base = Path.cwd()

    for item in root.rglob("*"):
        if not item.is_dir():
            continue
        if any(part.startswith("_") and part != "__pycache__" for part in item.parts):
            continue

        # Check exclusions using relative path from cwd
        rel_path = str(item.relative_to(base)).replace("\\", "/")
        if rel_path in exclude:
            continue

        # Check if it's a package (has .py files, not just subdirs)
        py_files = list(item.glob("*.py"))
        if py_files and any(f.name != "__init__.py" for f in py_files):
            packages.append(item)

    return sorted(packages)


def main():
    """Generate __init__.py for all packages in nomarr/."""
    base = Path.cwd()
    nomarr_root = base / "nomarr"

    if not nomarr_root.is_dir():
        print(f"Error: {nomarr_root} not found")
        return

    # Exclude packages with custom __init__.py logic
    exclude = {
        "nomarr/interfaces/api",  # Has custom state re-exports
        "nomarr/interfaces/api/endpoints",  # Just router registration
        "nomarr/interfaces/cli",  # Excludes main.py to prevent runpy warning
    }

    packages = find_all_packages(nomarr_root, exclude)

    for package_dir in packages:
        init_file = package_dir / "__init__.py"
        content = generate_init_for_package(package_dir)

        print(f"Generating {init_file.relative_to(base)}")
        with open(init_file, "w", encoding="utf-8") as f:
            f.write(content)

    print("\nDone! Review generated files before committing.")


if __name__ == "__main__":
    main()
