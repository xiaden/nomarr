"""Atomic multi-replacement tool.

Apply multiple string replacements to a file in a single atomic write.
All replacements are validated upfront and applied only if ALL succeed.
"""

from pathlib import Path

from .file_helpers import (
    normalize_eol,
    read_file_with_metadata,
    resolve_file_path,
)

_PREVIEW_MAX_LEN = 50


def _validate_replacements(replacements: list[dict]) -> dict | None:
    """Validate replacement list structure. Returns error dict or None if valid."""
    if not replacements:
        return {"error": "No replacements provided"}

    for i, rep in enumerate(replacements):
        if "old_string" not in rep:
            return {"error": f"Replacement {i}: missing 'old_string'"}
        if "new_string" not in rep:
            return {"error": f"Replacement {i}: missing 'new_string'"}

    return None


def _find_all_matches(content: str, old_string: str) -> list[tuple[int, int]]:
    """Find all non-overlapping occurrences of old_string, return (start, end) spans."""
    matches = []
    start = 0
    while True:
        pos = content.find(old_string, start)
        if pos == -1:
            break
        matches.append((pos, pos + len(old_string)))
        start = pos + len(old_string)
    return matches


def _spans_overlap(span1: tuple[int, int], span2: tuple[int, int]) -> bool:
    """Check if two (start, end) spans overlap."""
    return span1[0] < span2[1] and span2[0] < span1[1]


def _preview(s: str) -> str:
    """Create a preview string for logging."""
    preview = s[:_PREVIEW_MAX_LEN] + "..." if len(s) > _PREVIEW_MAX_LEN else s
    return preview.replace("\n", "\\n").replace("\r", "\\r")


def _validate_all_replacements_upfront(
    content: str,
    replacements: list[dict],
    eol: str,
) -> tuple[list[tuple[int, int, str]], list[dict]] | dict:
    """Validate all replacements against original content.

    Returns (edits, details) where edits is list of (start, end, new_string),
    or an error dict if validation fails.

    Edits are validated for:
    - Exactly one match per old_string
    - No overlapping spans between different replacements

    Each new_string is normalized to match the document's EOL style.
    """
    edits: list[tuple[int, int, str]] = []
    details: list[dict] = []
    errors: list[str] = []

    for i, rep in enumerate(replacements):
        old_string = rep["old_string"]
        new_string = rep["new_string"]
        # Normalize old_string to match document EOL so LLM-provided strings match file content
        normalized_old = normalize_eol(old_string, eol)
        old_preview = _preview(old_string)

        matches = _find_all_matches(content, normalized_old)

        if len(matches) == 0:
            errors.append(f"Replacement {i}: not found: {old_preview}")
            details.append({"old_string_preview": old_preview, "status": "not_found"})
        elif len(matches) > 1:
            errors.append(f"Replacement {i}: ambiguous ({len(matches)} occurrences): {old_preview}")
            details.append(
                {
                    "old_string_preview": old_preview,
                    "status": f"ambiguous ({len(matches)} occurrences)",
                },
            )
        else:
            # Exactly one match - check for overlap with previous edits
            span = matches[0]
            overlap_idx = None
            for j, (prev_start, prev_end, _) in enumerate(edits):
                if _spans_overlap(span, (prev_start, prev_end)):
                    overlap_idx = j
                    break

            if overlap_idx is not None:
                errors.append(
                    f"Replacement {i} overlaps with replacement {overlap_idx}: {old_preview}",
                )
                details.append(
                    {
                        "old_string_preview": old_preview,
                        "status": f"overlaps with replacement {overlap_idx}",
                    },
                )
            else:
                # Normalize new_string to match document's EOL style
                normalized_new = normalize_eol(new_string, eol)
                edits.append((span[0], span[1], normalized_new))
                details.append({"old_string_preview": old_preview, "status": "valid"})

    if errors:
        return {
            "error": "Validation failed - no changes made",
            "validation_errors": errors,
            "details": details,
            "changed": False,
        }

    return edits, details


def _apply_edits(content: str, edits: list[tuple[int, int, str]]) -> str:
    """Apply edits (start, end, new_string) to content.

    Edits are applied from end to start to preserve positions.
    """
    # Sort by start position descending so we apply from end first
    sorted_edits = sorted(edits, key=lambda e: e[0], reverse=True)

    for start, end, new_string in sorted_edits:
        content = content[:start] + new_string + content[end:]

    return content


def _write_and_build_result(
    target_path: Path,
    rel_path: str,
    content: str,
    new_content: str,
    original_mtime: float,
    details: list[dict],
    num_replacements: int,
) -> dict:
    """Check mtime, write if changed, and build result dict."""
    # Check mtime before write (detect concurrent modification)
    current_mtime = target_path.stat().st_mtime
    if current_mtime != original_mtime:
        return {
            "path": rel_path,
            "error": (
                f"MTIME MISMATCH: File may have changed during operation. "
                f"Expected mtime {original_mtime}, got {current_mtime}. "
                f"Aborting to prevent data loss - re-read and retry if needed."
            ),
            "changed": False,
            "details": details,
        }

    # Check if content actually changed
    if new_content == content:
        return {
            "path": rel_path,
            "changed": False,
            "replacements_applied": 0,
            "details": [{"old_string_preview": d["old_string_preview"], "status": "no_change"} for d in details],
            "note": "Replacements resulted in identical content",
        }

    # Write atomically
    target_path.write_bytes(new_content.encode("utf-8"))

    # Update details to show applied
    for d in details:
        d["status"] = "applied"

    return {
        "path": rel_path,
        "changed": True,
        "replacements_applied": num_replacements,
        "details": details,
    }


def edit_atomic_replace(
    file_path: str,
    replacements: list[dict],
    workspace_root: Path,
) -> dict:
    """Apply multiple string replacements atomically (single write).

    All replacements are validated against the ORIGINAL content before any
    changes are made. If ANY replacement fails validation, NO changes are
    written to disk.

    Validation checks:
    - Each old_string must match exactly once (not zero, not multiple)
    - No two replacements can have overlapping spans
    - File must be valid UTF-8
    - File must not contain tabs in leading whitespace

    Args:
        file_path: Workspace-relative or absolute path to the file
        replacements: List of dicts, each with:
            - old_string: Exact text to find and replace
            - new_string: Text to replace with
        workspace_root: Path to workspace root for security validation

    Returns:
        dict with:
        - path: The resolved workspace-relative path
        - changed: bool - whether file was modified
        - replacements_applied: Number of replacements (all or none)
        - details: List of {old_string_preview, status} for each replacement
        - error: Error message if operation fails
        - validation_errors: List of specific errors if validation failed

    """
    # Resolve and validate path
    resolved = resolve_file_path(file_path, workspace_root)
    if isinstance(resolved, dict):
        resolved["changed"] = False
        return resolved
    target_path = resolved
    rel_path = str(target_path.relative_to(workspace_root))

    # Validate replacements structure
    validation_error = _validate_replacements(replacements)
    if validation_error:
        validation_error["changed"] = False
        return validation_error

    # Read file with metadata
    file_data = read_file_with_metadata(target_path)
    if "error" in file_data:
        file_data["changed"] = False
        return file_data

    content = file_data["content"]
    original_mtime = file_data["mtime"]
    eol = file_data["eol"]

    # Validate all replacements upfront against original content
    validation_result = _validate_all_replacements_upfront(content, replacements, eol)
    if isinstance(validation_result, dict):
        validation_result["path"] = rel_path
        return validation_result

    edits, details = validation_result

    # Apply all edits
    new_content = _apply_edits(content, edits)

    # Write and build result (checks mtime, handles no-change case)
    return _write_and_build_result(
        target_path=target_path,
        rel_path=rel_path,
        content=content,
        new_content=new_content,
        original_mtime=original_mtime,
        details=details,
        num_replacements=len(replacements),
    )
