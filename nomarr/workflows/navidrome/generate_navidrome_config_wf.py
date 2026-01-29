"""Navidrome configuration generation workflow.

Generates navidrome.toml custom tag configuration from tags data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def generate_navidrome_config_workflow(db: Database, namespace: str = "nom") -> str:
    """Generate Navidrome TOML configuration for custom tags.

    Queries the tags collection to discover all nomarr tags, detects their types,
    and generates proper TOML configuration with all three tag format aliases.

    Args:
        db: Database instance
        namespace: Tag namespace (default: "nom")

    Returns:
        TOML configuration string ready to paste into navidrome.toml

    USAGE:
        >>> from nomarr.persistence.db import Database
        >>> from nomarr.workflows.navidrome.generate_navidrome_config_wf import generate_navidrome_config_workflow
        >>> db = Database("/path/to/library.db")
        >>> toml_config = generate_navidrome_config_workflow(db=db, namespace="nom")
        >>> print(toml_config)

    """
    logging.info("[navidrome] Generating Navidrome config from library tags")

    # Get all unique nomarr rels
    all_rels = db.tags.get_unique_rels(nomarr_only=True)

    if not all_rels:
        return "# No tags found in library. Run a library scan first.\n"

    # Filter to only rels with "nom:" prefix
    filtered_rels = [rel for rel in all_rels if rel.startswith("nom:")]

    if not filtered_rels:
        return "# No tags found with 'nom:' prefix. Check your tag namespace setting.\n"

    logging.info(f"[navidrome] Found {len(filtered_rels)} tags with 'nom:' prefix")

    # Generate config sections
    config_lines = [
        "# Navidrome Custom Tags Configuration",
        f"# Generated from library with {len(filtered_rels)} tags",
        "#",
        "# Add this to your navidrome.toml file, then run a FULL scan (not quick scan)",
        "",
    ]

    for rel in sorted(filtered_rels):
        # Get tag value counts for type detection
        value_counts = db.tags.get_tag_value_counts(rel)
        total_count = sum(value_counts.values())

        # Convert rel to Navidrome field name
        # nom:mood-strict -> mood_strict
        field_name = rel.replace("nom:", "").replace("-", "_")

        # Generate the three alias formats
        aliases = _generate_aliases(rel, namespace)

        # Detect tag type from values
        stats = _compute_tag_stats(value_counts)

        # Build TOML section
        config_lines.append(f"# {rel} ({total_count} files)")
        config_lines.append(f"Tags.{field_name}.Aliases = {aliases}")

        if stats["type"] != "string":
            config_lines.append(f'Tags.{field_name}.Type = "{stats["type"]}"')

        if stats["is_multivalue"]:
            config_lines.append(f'Tags.{field_name}.Split = ["; "]')

        config_lines.append("")

    config_lines.append("# End of generated configuration")

    return "\n".join(config_lines)


def _compute_tag_stats(value_counts: dict[Any, int]) -> dict[str, Any]:
    """Compute tag statistics from value counts."""
    if not value_counts:
        return {"type": "string", "is_multivalue": False, "total_count": 0}

    first_value = next(iter(value_counts.keys()))
    if isinstance(first_value, float):
        tag_type = "number"
    elif isinstance(first_value, int):
        tag_type = "integer"
    else:
        tag_type = "string"

    return {
        "type": tag_type,
        "is_multivalue": len(value_counts) > 1,
        "total_count": sum(value_counts.values()),
    }


def _generate_aliases(tag_key: str, namespace: str) -> str:
    """Generate the three tag format aliases for a tag key.

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
