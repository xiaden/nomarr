#!/usr/bin/env python3
"""
Move tag_normalization_comp.py from library to tagging domain.

This script:
1. Moves the file from components/library/ to components/tagging/
2. Updates __init__.py exports in both packages
3. Fixes imports across the codebase
"""

import shutil
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))


def main():
    # Paths
    src_file = project_root / "nomarr" / "components" / "library" / "tag_normalization_comp.py"
    dst_file = project_root / "nomarr" / "components" / "tagging" / "tag_normalization_comp.py"

    library_init = project_root / "nomarr" / "components" / "library" / "__init__.py"
    tagging_init = project_root / "nomarr" / "components" / "tagging" / "__init__.py"

    metadata_extraction = project_root / "nomarr" / "components" / "library" / "metadata_extraction_comp.py"

    print(f"Moving {src_file.name}...")

    # 1. Move the file
    if not src_file.exists():
        print(f"Error: Source file not found: {src_file}")
        return 1

    shutil.move(str(src_file), str(dst_file))
    print(f"✓ Moved to {dst_file.relative_to(project_root)}")

    # 2. Update library __init__.py (remove exports)
    print("\nUpdating library __init__.py...")
    with open(library_init, encoding='utf-8') as f:
        library_content = f.read()

    # Remove the normalization imports and exports
    library_content = library_content.replace(
        "from nomarr.components.library.tag_normalization_comp import (\n"
        "    normalize_id3_tags,\n"
        "    normalize_mp4_tags,\n"
        "    normalize_vorbis_tags,\n"
        ")\n",
        ""
    )

    # Remove from __all__
    library_content = library_content.replace(
        '    "normalize_mp4_tags",\n'
        '    "normalize_id3_tags",\n'
        '    "normalize_vorbis_tags",\n',
        ""
    )

    with open(library_init, 'w', encoding='utf-8') as f:
        f.write(library_content)
    print("✓ Removed exports from library __init__.py")

    # 3. Update tagging __init__.py (add exports)
    print("\nUpdating tagging __init__.py...")
    with open(tagging_init, encoding='utf-8') as f:
        tagging_content = f.read()

    # Find the imports section and add our imports
    import_section_end = tagging_content.find('\n\n__all__')
    if import_section_end == -1:
        print("Warning: Could not find __all__ in tagging __init__.py")
        import_section_end = len(tagging_content)

    new_import = (
        "from nomarr.components.tagging.tag_normalization_comp import (\n"
        "    normalize_id3_tags,\n"
        "    normalize_mp4_tags,\n"
        "    normalize_vorbis_tags,\n"
        ")\n"
    )

    tagging_content = (
        tagging_content[:import_section_end] +
        new_import +
        tagging_content[import_section_end:]
    )

    # Add to __all__
    all_start = tagging_content.find('__all__ = [')
    if all_start != -1:
        # Find the closing bracket
        all_end = tagging_content.find(']', all_start)
        # Insert before the closing bracket
        new_exports = (
            '    "normalize_mp4_tags",\n'
            '    "normalize_id3_tags",\n'
            '    "normalize_vorbis_tags",\n'
        )
        tagging_content = (
            tagging_content[:all_end] +
            new_exports +
            tagging_content[all_end:]
        )

    with open(tagging_init, 'w', encoding='utf-8') as f:
        f.write(tagging_content)
    print("✓ Added exports to tagging __init__.py")

    # 4. Fix import in metadata_extraction_comp.py
    print("\nUpdating metadata_extraction_comp.py imports...")
    with open(metadata_extraction, encoding='utf-8') as f:
        extraction_content = f.read()

    extraction_content = extraction_content.replace(
        "from nomarr.components.library.tag_normalization_comp import (",
        "from nomarr.components.tagging.tag_normalization_comp import ("
    )

    with open(metadata_extraction, 'w', encoding='utf-8') as f:
        f.write(extraction_content)
    print("✓ Updated import in metadata_extraction_comp.py")

    print("\n✓ Migration complete!")
    print("\nSummary:")
    print("  - Moved: tag_normalization_comp.py → components/tagging/")
    print("  - Updated: library/__init__.py (removed exports)")
    print("  - Updated: tagging/__init__.py (added exports)")
    print("  - Updated: metadata_extraction_comp.py (fixed import)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
