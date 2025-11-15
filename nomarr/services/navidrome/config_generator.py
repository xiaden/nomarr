"""
Navidrome configuration generator.

Generates navidrome.toml custom tag configuration from library_tags data.
"""

from __future__ import annotations

import logging
from typing import Any

from nomarr.persistence.db import Database


def generate_navidrome_config(db: Database, namespace: str = "nom") -> str:
    """
    Generate Navidrome TOML configuration for custom tags.

    Queries the library_tags table to discover all tags, detects their types,
    and generates proper TOML configuration with all three tag format aliases.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        TOML configuration string ready to paste into navidrome.toml
    """
    logging.info("[navidrome] Generating Navidrome config from library tags")

    # Get all unique tag keys
    tag_keys = db.get_unique_tag_keys()

    if not tag_keys:
        return "# No tags found in library. Run a library scan first.\n"

    # Filter to only tags with the specified namespace
    namespace_prefix = f"{namespace}:"
    filtered_tags = [tag for tag in tag_keys if tag.startswith(namespace_prefix)]

    if not filtered_tags:
        return f"# No tags found with namespace '{namespace}:'. Check your tag namespace setting.\n"

    logging.info(f"[navidrome] Found {len(filtered_tags)} tags with namespace '{namespace}:'")

    # Generate config sections
    config_lines = [
        "# Navidrome Custom Tags Configuration",
        f"# Generated from library with {len(filtered_tags)} tags",
        "#",
        "# Add this to your navidrome.toml file, then run a FULL scan (not quick scan)",
        "",
    ]

    for tag_key in sorted(filtered_tags):
        # Get tag statistics
        stats = db.get_tag_type_stats(tag_key)

        # Convert tag key to Navidrome field name
        # nom:mood-strict -> mood_strict
        field_name = tag_key.replace(f"{namespace}:", "").replace("-", "_")

        # Generate the three alias formats
        aliases = _generate_aliases(tag_key, namespace)

        # Detect tag type
        tag_type = _detect_tag_type(stats)

        # Build TOML section
        config_lines.append(f"# {tag_key} ({stats['total_count']} files)")
        config_lines.append(f"Tags.{field_name}.Aliases = {aliases}")

        if tag_type != "string":
            config_lines.append(f'Tags.{field_name}.Type = "{tag_type}"')

        if stats["is_multivalue"]:
            config_lines.append(f'Tags.{field_name}.Split = ["; "]')

        config_lines.append("")

    config_lines.append("# End of generated configuration")

    return "\n".join(config_lines)


def _generate_aliases(tag_key: str, namespace: str) -> str:
    """
    Generate the three tag format aliases for a tag key.

    Args:
        tag_key: Full tag key (e.g., "nom:mood-strict")
        namespace: Namespace portion (e.g., "nom")

    Returns:
        JSON array string for TOML (e.g., '["nom:mood-strict", "----:com.apple.iTunes:nom:mood-strict", "NOM_MOOD_STRICT"]')
    """
    # 1. ID3v2/MP3 format: nom:mood-strict
    id3_alias = tag_key

    # 2. iTunes/M4A format: ----:com.apple.iTunes:nom:mood-strict
    itunes_alias = f"----:com.apple.iTunes:{tag_key}"

    # 3. Vorbis/FLAC/OGG format: NOM_MOOD_STRICT (uppercase, special chars -> underscores)
    # Extract the tag name portion (after namespace:)
    tag_name = tag_key.replace(f"{namespace}:", "")
    vorbis_alias = f"{namespace.upper()}_{tag_name.upper()}".replace("-", "_").replace(":", "_")

    return f'["{id3_alias}", "{itunes_alias}", "{vorbis_alias}"]'


def _detect_tag_type(stats: dict[str, Any]) -> str:
    """
    Detect the Navidrome tag type from tag statistics.

    Args:
        stats: Dict from get_tag_type_stats() with is_multivalue, sample_values, total_count

    Returns:
        One of: "string", "int", "float"
    """
    sample_values = stats.get("sample_values", [])

    if not sample_values:
        return "string"

    # Check a few sample values to determine type
    # (All values should have the same type from upsert_file_tags type detection)
    sample = sample_values[0]

    # Try to detect numeric types
    try:
        # Check if it's a float with decimal point
        if "." in sample:
            float(sample)
            return "float"
        # Check if it's an integer
        int(sample)
        return "int"
    except ValueError:
        pass

    return "string"


def preview_tag_stats(db: Database, namespace: str = "nom") -> dict[str, dict[str, Any]]:
    """
    Preview statistics for all tags in the library.

    Useful for debugging and understanding your tag data before generating config.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        Dict of tag_key -> stats dict (type, is_multivalue, summary, count)
    """
    import logging

    tag_keys = db.get_unique_tag_keys()
    namespace_prefix = f"{namespace}:"
    filtered_tags = [tag for tag in tag_keys if tag.startswith(namespace_prefix)]

    logging.info(f"[navidrome] Computing summaries for {len(filtered_tags)} tags...")

    stats_by_tag = {}

    for idx, tag_key in enumerate(filtered_tags, 1):
        try:
            if idx % 10 == 0:
                logging.info(f"[navidrome] Progress: {idx}/{len(filtered_tags)} tags processed...")

            summary = db.get_tag_summary(tag_key)

            stats_by_tag[tag_key] = {
                "type": summary["type"],
                "is_multivalue": summary["is_multivalue"],
                "summary": summary["summary"],
                "total_count": summary["total_count"],
            }
        except Exception as e:
            logging.error(f"[navidrome] Error computing summary for {tag_key}: {e}")
            # Provide fallback data so one error doesn't break everything
            stats_by_tag[tag_key] = {
                "type": "string",
                "is_multivalue": False,
                "summary": f"Error: {e!s}",
                "total_count": 0,
            }

    logging.info(f"[navidrome] Completed {len(stats_by_tag)} tag summaries")
    return stats_by_tag
