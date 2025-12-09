#!/usr/bin/env python3
"""
Auto-generate __init__.py files with proper __all__ exports.
Scans Python modules and generates clean __init__.py files.
"""

import ast
import subprocess
import sys
from pathlib import Path

import yaml


def load_config() -> dict:
    """Load configuration from YAML file."""
    config_path = Path(__file__).parent / "configs" / "generate_inits_config.yml"
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def get_public_names(file_path: Path, banned_exports: set[str]) -> set[str]:
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

    # Filter out banned exports
    names = {name for name in names if name not in banned_exports}

    return names


def generate_init_for_package(
    package_dir: Path, custom_exports: dict[str, list[str]] | None = None, config: dict | None = None
) -> str:
    """Generate __init__.py content for a package directory."""
    custom_exports = custom_exports or {}
    module_name = package_dir.name

    if config is None:
        config = load_config()

    banned_exports = set(config.get("banned_exports", []))
    max_line_length = config.get("max_import_line_length", 88)

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
        names = get_public_names(py_file, banned_exports)
        if names:
            all_exports[module_name_inner] = sorted(names)

    if not all_exports:
        return '"""Package."""\n'

    # Build imports (ruff-friendly formatting)
    lines = ['"""', f"{module_name.replace('_', ' ').title()} package.", '"""', ""]

    for module, names in sorted(all_exports.items()):
        if not names:  # Skip if no names to import
            continue

        # Build import line
        import_line = f"from .{module} import {', '.join(names)}"

        # If short enough, use single line; otherwise use multi-line
        if len(import_line) <= max_line_length:
            lines.append(import_line)
        else:
            # Multi-line import with parentheses (ruff/Black style)
            lines.append(f"from .{module} import (")
            for name in names:
                lines.append(f"    {name},")
            lines.append(")")

    # Build __all__ (sorted, filtered)
    all_names: list[str] = []
    for names in all_exports.values():
        all_names.extend(names)

    # Remove duplicates, sort, and filter banned exports
    all_names_sorted = sorted({name for name in all_names if name not in banned_exports})

    lines.append("")
    lines.append("__all__ = [")
    for name in all_names_sorted:
        lines.append(f'    "{name}",')
    lines.append("]")

    return "\n".join(lines) + "\n"


def is_manually_managed(init_file: Path, config: dict | None = None) -> bool:
    """Check if an __init__.py file is manually managed and should not be overwritten."""
    if not init_file.exists():
        return False

    if config is None:
        config = load_config()

    manual_indicators = config.get("manual_indicators", [])
    manual_marker = config.get("manual_init_marker", "# MANUAL_INIT")

    # Combine marker with other indicators
    all_indicators = [manual_marker, *manual_indicators]

    try:
        content = init_file.read_text(encoding="utf-8")
        # Check for any manual indicators
        return any(indicator in content for indicator in all_indicators)
    except Exception as e:
        print(f"Warning: Could not read {init_file}: {e}", file=sys.stderr)
        return False  # If we can't read it, assume it's safe to overwrite


def run_ruff_format(file_path: Path) -> None:
    """Run ruff format on a file. Best-effort, does not crash if ruff is unavailable."""
    try:
        subprocess.run(["ruff", "format", str(file_path)], check=False, capture_output=True)
    except FileNotFoundError:
        # ruff not installed, skip formatting
        pass
    except Exception as e:
        # Any other error, just log and continue
        print(f"Warning: Could not run ruff format on {file_path}: {e}", file=sys.stderr)


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
    config = load_config()
    base = Path.cwd()
    nomarr_root = base / "nomarr"

    if not nomarr_root.is_dir():
        print(f"Error: {nomarr_root} not found")
        return

    # Get excluded packages from config
    excluded_packages = set(config.get("excluded_packages", []))

    packages = find_all_packages(nomarr_root, excluded_packages)

    for package_dir in packages:
        init_file = package_dir / "__init__.py"

        # Check if __init__.py is manually managed
        if is_manually_managed(init_file, config):
            print(f"Skipping {init_file.relative_to(base)} (manually managed)")
            continue

        # Generate new content
        content = generate_init_for_package(package_dir, config=config)

        print(f"Generating {init_file.relative_to(base)}")
        with open(init_file, "w", encoding="utf-8") as f:
            f.write(content)

        # Run ruff format on the generated file (best-effort)
        run_ruff_format(init_file)

    print("\nDone! Review generated files before committing.")


if __name__ == "__main__":
    main()
