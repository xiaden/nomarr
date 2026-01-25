#!/usr/bin/env python3
"""
Generate API documentation from source code.

Uses scripts/discover_api.py as backend to extract API information,
then generates simple Markdown files for each architectural layer.

This is tooling only - does NOT import nomarr.* directly.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Any


def enumerate_modules(root_module: str) -> list[str]:
    """
    Enumerate all Python modules under a root package.

    Does NOT import nomarr.*; uses filesystem introspection only.

    Args:
        root_module: e.g. "nomarr.workflows"

    Returns:
        Sorted list of module names, e.g.:
        ["nomarr.workflows", "nomarr.workflows.processor", ...]
    """
    # Convert module name to filesystem path
    # e.g. "nomarr.workflows" -> "nomarr/workflows"
    parts = root_module.split(".")
    root_path = Path.cwd() / Path(*parts)

    if not root_path.exists():
        return []

    modules = []

    # Walk all .py files under the root
    for py_file in sorted(root_path.rglob("*.py")):
        # Skip __pycache__ and other special dirs
        if "__pycache__" in py_file.parts:
            continue

        # Build module name from relative path
        rel_path = py_file.relative_to(Path.cwd())
        module_parts = list(rel_path.parts[:-1])  # All dirs

        if py_file.name == "__init__.py":
            # Package module: use parent directory as module name
            if module_parts:
                module_name = ".".join(module_parts)
                modules.append(module_name)
        else:
            # Regular module: add filename without .py extension
            module_parts.append(py_file.stem)
            module_name = ".".join(module_parts)
            modules.append(module_name)

    return sorted(modules)


def discover_module(module_name: str) -> dict[str, Any] | None:
    """
    Run discover_api.py with --summary and parse JSON output.

    Returns None if module import fails.
    """
    try:
        result = subprocess.run(
            [sys.executable, "scripts/discover_api.py", module_name, "--summary"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

        # With resilient discover_api, returncode should always be 0
        # But check anyway for backward compat
        if result.returncode != 0:
            stderr_line = (
                result.stderr.strip().split("\n")[0] if result.stderr.strip() else "Unknown error"
            )
            print(f"[!] Skipping {module_name}: discovery subprocess failed")
            print(f"    Reason: {stderr_line}")
            return None

        # Parse JSON output
        api: dict[str, Any] = json.loads(result.stdout)

        # Check for error field in JSON
        if "error" in api:
            print(f"[!] {module_name}: import/discovery failed")
            print(f"    Error: {api['error']}")
            # Return None to skip this module (no API to document)
            return None

        return api

    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        print(f"[!] Skipping {module_name}: {e}")
        return None


def render_markdown(api: dict[str, Any]) -> str:
    """
    Convert API dict to Markdown.

    Returns complete Markdown document as string.
    """
    module_name = api.get("module", "Unknown")
    lines = [
        f"# {module_name}",
        "",
        f"API reference for `{module_name}`.",
        "",
        "---",
        "",
    ]

    # Classes
    classes = api.get("classes", {})
    if classes:
        lines.append("## Classes")
        lines.append("")

        for class_name, class_info in sorted(classes.items()):
            lines.append(f"### {class_name}")
            lines.append("")

            # Docstring (first line only)
            doc = class_info.get("doc", "").strip()
            if doc:
                first_line = doc.split("\n")[0]
                lines.append(first_line)
            else:
                lines.append(f"TODO: describe {class_name}")
            lines.append("")

            # Methods
            methods = class_info.get("methods", {})
            if methods:
                lines.append("**Methods:**")
                lines.append("")
                for method_name, signature in sorted(methods.items()):
                    lines.append(f"- `{method_name}{signature}`")
                lines.append("")

        lines.append("---")
        lines.append("")

    # Functions
    functions = api.get("functions", {})
    if functions:
        lines.append("## Functions")
        lines.append("")

        for func_name, func_info in sorted(functions.items()):
            signature = func_info.get("signature", "()")
            lines.append(f"### {func_name}{signature}")
            lines.append("")

            # Docstring (first line only)
            doc = func_info.get("doc", "").strip()
            if doc:
                first_line = doc.split("\n")[0]
                lines.append(first_line)
            else:
                lines.append(f"TODO: describe {func_name}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Constants
    constants = api.get("constants", {})
    if constants:
        lines.append("## Constants")
        lines.append("")

        for const_name, const_value in sorted(constants.items()):
            lines.append(f"### {const_name}")
            lines.append("")
            lines.append("```python")
            lines.append(f"{const_name} = {const_value}")
            lines.append("```")
            lines.append("")

        lines.append("---")
        lines.append("")

    return "\n".join(lines)


def generate_docs_for_module(module_name: str, output_dir: Path) -> bool:
    """
    Generate Markdown documentation for a single module.

    Writes to output_dir/<module_name_with_underscores>.md
    Returns True if successful, False otherwise.
    """
    print(f"Generating docs for {module_name}...")

    # Discover API
    api = discover_module(module_name)
    if api is None:
        return False

    # Skip if module has no public API
    if not any([api.get("classes"), api.get("functions"), api.get("constants")]):
        print("   [i] No public API found, skipping")
        return False

    # Render Markdown
    markdown = render_markdown(api)

    # Write file
    filename = module_name.replace(".", "_") + ".md"
    output_path = output_dir / filename
    output_path.write_text(markdown, encoding="utf-8")

    print(f"   [OK] Written to {output_path}")
    return True


def main() -> int:
    """
    Generate API documentation for all architectural layers.

    Uses architecture_manifest.LAYERS as source of truth.
    """
    # Import LAYERS from architecture manifest using importlib
    import importlib.util

    manifest_path = Path.cwd() / "scripts" / "configs" / "architecture_manifest.py"
    if not manifest_path.exists():
        print(f"[ERROR] architecture_manifest.py not found at {manifest_path}")
        print("   Make sure you're running from the project root.")
        return 1

    spec = importlib.util.spec_from_file_location("architecture_manifest", manifest_path)
    if spec is None or spec.loader is None:
        print(f"[ERROR] Failed to load architecture_manifest from {manifest_path}")
        return 1

    manifest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manifest)
    LAYERS: list[str] = manifest.LAYERS

    # Ensure output directory exists
    output_dir = Path("docs/api/modules")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating API documentation for {len(LAYERS)} layer roots...\n")

    # Generate docs for all modules under each layer root
    success_count = 0
    total_count = 0

    for root_module in LAYERS:
        print(f"Enumerating modules under {root_module}...")
        modules = enumerate_modules(root_module)

        if not modules:
            print(f"   [!] No modules found under {root_module}")
            continue

        print(f"   Found {len(modules)} module(s)")

        for module_name in modules:
            total_count += 1
            if generate_docs_for_module(module_name, output_dir):
                success_count += 1

    print(f"\n[OK] Generated {success_count}/{total_count} module docs")
    print(f"Output directory: {output_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
