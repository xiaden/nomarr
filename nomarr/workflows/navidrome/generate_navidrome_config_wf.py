"""Navidrome configuration generation workflow.

Generates navidrome.toml custom tag configuration from tags data.
Uses short, user-friendly field names while preserving full versioned keys as aliases.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.components.navidrome.tag_query_comp import (
    get_nomarr_tag_rels,
    get_tag_value_counts,
)
from nomarr.helpers.tag_key_mapping import (
    is_versioned_ml_key,
    make_navidrome_field_name,
    make_short_tag_name,
)

logger = logging.getLogger(__name__)
if TYPE_CHECKING:
    from nomarr.persistence.db import Database


def generate_navidrome_config_workflow(db: Database, namespace: str = "nom") -> str:
    """Generate Navidrome TOML configuration for custom tags.

    Queries the tags collection to discover all nomarr tags, detects their types,
    and generates proper TOML configuration with user-friendly field names.

    The field names are short (e.g., nom_happy_raw) while the aliases point to
    the full versioned storage keys for all three tag formats (ID3, iTunes, Vorbis).

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
    logger.info("[navidrome] Generating Navidrome config from library tags")
    all_rels = get_nomarr_tag_rels(db)
    if not all_rels:
        return "# No tags found in library. Run a library scan first.\n"
    filtered_rels = [rel for rel in all_rels if rel.startswith("nom:")]
    if not filtered_rels:
        return "# No tags found with 'nom:' prefix. Check your tag namespace setting.\n"
    logger.info(f"[navidrome] Found {len(filtered_rels)} tags with 'nom:' prefix")

    config_lines = [
        "# Navidrome Custom Tags Configuration",
        f"# Generated from library with {len(filtered_rels)} tags",
        "#",
        "# Add this to your navidrome.toml file, then run a FULL scan (not quick scan)",
        "#",
        "# Field names are user-friendly short names.",
        "# Aliases map to the full versioned storage keys.",
        "",
    ]

    # Group by short name to detect collisions (multiple versions of same label)
    short_name_to_rels: dict[str, list[str]] = {}
    for rel in filtered_rels:
        value_counts = get_tag_value_counts(db, rel)
        is_numeric = _compute_tag_stats(value_counts)["type"] in ("number", "integer")
        short_name = make_short_tag_name(rel, is_numeric=is_numeric)
        if short_name not in short_name_to_rels:
            short_name_to_rels[short_name] = []
        short_name_to_rels[short_name].append(rel)

    # Sort by short name for consistent output
    for short_name in sorted(short_name_to_rels.keys()):
        rels = short_name_to_rels[short_name]
        field_name = make_navidrome_field_name(short_name)

        # Collect stats and aliases from all rels that share this short name
        total_count = 0
        aliases_list: list[str] = []
        tag_type = "string"
        is_multivalue = False

        for rel in rels:
            value_counts = get_tag_value_counts(db, rel)
            total_count += sum(value_counts.values())
            stats = _compute_tag_stats(value_counts)
            if stats["type"] != "string":
                tag_type = stats["type"]
            if stats["is_multivalue"]:
                is_multivalue = True
            # Generate aliases for this rel
            aliases_list.extend(_generate_alias_list(rel, namespace))

        # Deduplicate aliases while preserving order
        seen: set[str] = set()
        unique_aliases: list[str] = []
        for alias in aliases_list:
            if alias not in seen:
                seen.add(alias)
                unique_aliases.append(alias)

        aliases_json = _format_aliases_json(unique_aliases)

        # Comment showing mapped rels (helpful when short name maps to versioned key)
        if len(rels) == 1 and is_versioned_ml_key(rels[0]):
            config_lines.append(f"# {short_name} -> {rels[0]} ({total_count} files)")
        else:
            rel_list = ", ".join(rels)
            config_lines.append(f"# {short_name} ({total_count} files)")
            if len(rels) > 1:
                config_lines.append(f"#   Maps to: {rel_list}")

        config_lines.append(f"Tags.{field_name}.Aliases = {aliases_json}")
        if tag_type != "string":
            config_lines.append(f'Tags.{field_name}.Type = "{tag_type}"')
        if is_multivalue:
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


def _generate_alias_list(tag_key: str, namespace: str) -> list[str]:
    """Generate the three tag format aliases for a tag key.

    Args:
        tag_key: Full tag key (e.g., "nom:mood-strict")
        namespace: Namespace portion (e.g., "nom")

    Returns:
        List of three aliases: [ID3, iTunes, Vorbis]

    """
    id3_alias = tag_key
    itunes_alias = f"----:com.apple.iTunes:{tag_key}"
    tag_name = tag_key.replace(f"{namespace}:", "")
    vorbis_alias = f"{namespace.upper()}_{tag_name.upper()}".replace("-", "_").replace(":", "_")
    return [id3_alias, itunes_alias, vorbis_alias]


def _format_aliases_json(aliases: list[str]) -> str:
    """Format aliases list as JSON array for TOML."""
    escaped = [f'"{a}"' for a in aliases]
    return f"[{', '.join(escaped)}]"


# Legacy function for backwards compatibility
def _generate_aliases(tag_key: str, namespace: str) -> str:
    """Generate the three tag format aliases for a tag key.

    Args:
        tag_key: Full tag key (e.g., "nom:mood-strict")
        namespace: Namespace portion (e.g., "nom")

    Returns:
        JSON array string for TOML

    """
    return _format_aliases_json(_generate_alias_list(tag_key, namespace))
