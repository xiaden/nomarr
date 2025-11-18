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

        if result.returncode != 0:
            print(f"⚠️  Skipping {module_name}: discovery failed")
            return None

        # Parse JSON output
        return json.loads(result.stdout)

    except (subprocess.SubprocessError, json.JSONDecodeError) as e:
        print(f"⚠️  Skipping {module_name}: {e}")
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
            if doc and doc != "No docstring":
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
    print(f"📄 Generating docs for {module_name}...")

    # Discover API
    api = discover_module(module_name)
    if api is None:
        return False

    # Skip if module has no public API
    if not any([api.get("classes"), api.get("functions"), api.get("constants")]):
        print("   ℹ️  No public API found, skipping")
        return False

    # Render Markdown
    markdown = render_markdown(api)

    # Write file
    filename = module_name.replace(".", "_") + ".md"
    output_path = output_dir / filename
    output_path.write_text(markdown, encoding="utf-8")

    print(f"   ✅ Written to {output_path}")
    return True


def main() -> int:
    """
    Generate API documentation for all architectural layers.

    Uses architecture_manifest.LAYERS as source of truth.
    """
    # Import LAYERS from architecture manifest
    try:
        sys.path.insert(0, str(Path.cwd()))
        from architecture_manifest import LAYERS
    except ImportError as e:
        print(f"❌ Failed to import architecture_manifest: {e}")
        print("   Make sure you're running from the project root.")
        return 1

    # Ensure output directory exists
    output_dir = Path("docs/api/modules")
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating API documentation for {len(LAYERS)} layers...\n")

    # Generate docs for each layer
    success_count = 0
    for module_name in LAYERS:
        if generate_docs_for_module(module_name, output_dir):
            success_count += 1

    print(f"\n✅ Generated {success_count}/{len(LAYERS)} module docs")
    print(f"📁 Output directory: {output_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
