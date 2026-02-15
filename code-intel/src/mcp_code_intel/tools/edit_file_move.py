"""Move/rename a file within the workspace.

Single-call file move: resolves old_path (must exist, must be a file) and
new_path (must not exist), creates parent directories for the target, and
performs the move. Uses shutil.move — same-filesystem moves are atomic renames,
cross-filesystem moves fall back to copy+delete.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..helpers.file_helpers import resolve_file_path, resolve_path_for_create


def edit_file_move(
    old_path: str,
    new_path: str,
    workspace_root: Path,
) -> dict:
    """Move or rename a file within the workspace.

    Uses shutil.move internally — same-filesystem moves are atomic renames,
    cross-filesystem moves fall back to copy+delete.

    Args:
        old_path: Workspace-relative or absolute path to the source file (must exist)
        new_path: Workspace-relative or absolute path to the destination (must not exist)
        workspace_root: Workspace root path for resolution and security

    Returns:
        dict with:
        - status: "moved" on success
        - old_path: Workspace-relative path of the source
        - new_path: Workspace-relative path of the destination
        - bytes: Size of the moved file
        - dirs_created: List of workspace-relative dirs created (empty if none)
        - error: Error message if operation fails
    """
    # Resolve and validate source path (must exist, must be a file)
    resolved_old = resolve_file_path(old_path, workspace_root)
    if isinstance(resolved_old, dict):
        return resolved_old  # contains 'error' key

    # Belt-and-suspenders: resolve_file_path enforces is_file() today,
    # but we don't want to silently broaden to directories if that changes.
    if not resolved_old.is_file():
        return {"error": f"Not a file: {old_path}"}

    # Resolve target path (workspace-bounded, must not be a directory)
    # resolve_path_for_create doesn't enforce non-existence — that's intentional
    # for tools that overwrite. We enforce it explicitly here.
    resolved_new = resolve_path_for_create(new_path, workspace_root)
    if isinstance(resolved_new, dict):
        return resolved_new  # contains 'error' key

    if resolved_new.exists():
        return {"error": f"Target already exists: {new_path}"}

    # Same path check
    if resolved_old == resolved_new:
        return {"error": "Source and target are the same path"}

    # Create parent directories for the target, tracking what was created
    dirs_to_create: list[Path] = []
    check = resolved_new.parent
    while not check.exists():
        dirs_to_create.append(check)
        check = check.parent
    try:
        resolved_new.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return {"error": f"Failed to create target directory: {e}"}

    # Get file size before move
    try:
        file_bytes = resolved_old.stat().st_size
    except OSError as e:
        return {"error": f"Failed to stat source file: {e}"}

    # Perform the move
    try:
        shutil.move(str(resolved_old), str(resolved_new))
    except (OSError, shutil.Error) as e:
        return {"error": f"Move failed: {e}"}

    # Return workspace-relative paths — the caller already knows the relative
    # paths it passed in, and absolute paths leak workstation layout needlessly.
    # The server wrapper uses these for wrap_mcp_result_with_file_link which
    # handles absolute resolution itself.
    rel_old = str(resolved_old.relative_to(workspace_root))
    rel_new = str(resolved_new.relative_to(workspace_root))
    dirs_created = [
        str(d.relative_to(workspace_root))
        for d in reversed(dirs_to_create)
    ]

    return {
        "status": "moved",
        "old_path": rel_old,
        "new_path": rel_new,
        "bytes": file_bytes,
        "dirs_created": dirs_created,
    }
