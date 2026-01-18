"""Tag value parsing for file-sourced tags.

Parses raw tag values read from audio files into typed Python values.
"""

from __future__ import annotations

import json
from typing import Any


def parse_tag_values(tags: dict[str, Any]) -> dict[str, Any]:
    """
    Parse tag values from strings to appropriate types.

    Converts string tag values to their proper types:
    - JSON arrays (e.g., '["value1", "value2"]') -> list
    - Floats (e.g., "0.95") -> float
    - Integers (e.g., "120") -> int
    - Semicolon-delimited (e.g., "pop; rock") -> list
    - Everything else -> str

    Handles values that are already typed (passthrough).

    Args:
        tags: Dict of tag_key -> tag_value (strings from file or already typed)

    Returns:
        Dict with parsed values

    Example:
        >>> parse_tag_values({"tempo": "120", "score": "0.95", "tags": '["pop", "upbeat"]'})
        {"tempo": 120, "score": 0.95, "tags": ["pop", "upbeat"]}
    """
    parsed: dict[str, Any] = {}

    for key, value in tags.items():
        if not value:
            continue

        # If value is already typed (not a string), keep it as-is
        if not isinstance(value, str):
            parsed[key] = value
            continue

        # Try to parse as JSON (for arrays)
        if value.startswith("[") and value.endswith("]"):
            try:
                parsed_value = json.loads(value)
                if isinstance(parsed_value, list):
                    parsed[key] = parsed_value
                    continue
            except json.JSONDecodeError:
                pass

        # Handle semicolon-delimited multi-value tags
        # Some formats (MP3) don't support native multi-value
        if ";" in value:
            parsed[key] = [v.strip() for v in value.split(";") if v.strip()]
            continue

        # Try to parse as float
        try:
            if "." in value:
                parsed[key] = float(value)
                continue
        except ValueError:
            pass

        # Try to parse as int
        try:
            parsed[key] = int(value)
            continue
        except ValueError:
            pass

        # Keep as string
        parsed[key] = value

    return parsed
