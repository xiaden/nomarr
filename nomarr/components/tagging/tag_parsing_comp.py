"""Tag value parsing for file-sourced tags.

Parses raw tag values read from audio files into typed Python values.
"""

from __future__ import annotations

import ast
import contextlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nomarr.helpers.dto.tags_dto import TagValue


def parse_tag_values(tags: dict[str, str | TagValue | list[TagValue]]) -> dict[str, list[TagValue]]:
    """Parse tag values from strings to typed values, always returning lists.

    Handles JSON arrays, Python tuples, floats, ints, semicolon-delimited lists,
    and typed values (passthrough). Non-parseable strings are kept as-is wrapped in a list.
    """
    parsed: dict[str, list[TagValue]] = {}

    for key, value in tags.items():
        if not value:
            continue

        # If value is already a list, keep it
        if isinstance(value, list):
            parsed[key] = value
            continue

        # If value is already typed (not a string), wrap in list
        if not isinstance(value, str):
            parsed[key] = [value]
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

        # Try to parse Python tuple strings (legacy format from str(tuple))
        # e.g., "('aggressive', 'party-like', 'peppy')"
        if value.startswith("(") and value.endswith(")"):
            try:
                # Use ast.literal_eval for safe parsing of tuple literals
                parsed_value = ast.literal_eval(value)
                if isinstance(parsed_value, tuple):
                    parsed[key] = list(parsed_value)
                    continue
            except (ValueError, SyntaxError):
                pass

        # Handle semicolon-delimited multi-value tags
        # Some formats (MP3) don't support native multi-value
        if ";" in value:
            parsed[key] = [v.strip() for v in value.split(";") if v.strip()]
            continue

        # Try to parse as float
        with contextlib.suppress(ValueError):
            if "." in value:
                parsed[key] = [float(value)]
                continue

        # Try to parse as int
        try:
            parsed[key] = [int(value)]
            continue
        except ValueError:
            pass

        # Keep as string, wrapped in list
        parsed[key] = [value]

    return parsed
