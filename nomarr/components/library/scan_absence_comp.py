"""Corroborated-absence witness for library scans.

Part C of the canonical filesystem-access contract. This component is the sole
producer of an authorized ``absent``/``resource_missing`` fact: absence is
corroborated from the same-pass raw directory listings the scanner already
collected, never from a filesystem probe. The witness performs zero filesystem
syscalls — it is pure set membership over the pass's enumeration.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from nomarr.helpers.fs_contract import FsFact

if TYPE_CHECKING:
    from collections.abc import Collection, Iterator, Mapping

    from nomarr.helpers.dataclasses.library_dataclass import Library
    from nomarr.persistence import Database


def scope_uninspected(rel_path: str, uninspected_scope: Collection[str]) -> bool:
    """True when ``rel_path`` itself or any ancestor could not be inspected."""
    candidate = rel_path
    while True:
        if candidate in uninspected_scope:
            return True
        if not candidate:
            return False
        candidate = candidate.rsplit("/", 1)[0] if "/" in candidate else ""


def _folder_absent(
    folder_rel_path: str,
    reconciled_folders: Mapping[str, frozenset[str]],
    uninspected_scope: Collection[str],
) -> bool:
    """True when ``folder_rel_path`` is corroborated absent by enumeration.

    Walks up to the nearest enumerated ancestor. A folder is authoritatively
    absent only when that ancestor's raw listing omits the next path component;
    a folder that is itself enumerated is present, and a chain that reaches the
    root without an enumerated ancestor fails closed (returns ``False``).
    """
    current = folder_rel_path
    while current:
        if scope_uninspected(current, uninspected_scope):
            return False
        if current in reconciled_folders:
            return False
        parent = current.rsplit("/", 1)[0] if "/" in current else ""
        name = current.rsplit("/", 1)[-1]
        if not parent:
            root_names = reconciled_folders.get("")
            return root_names is not None and name not in root_names
        if parent in reconciled_folders:
            return name not in reconciled_folders[parent]
        current = parent
    return False


def _unknown_fact(absolute_path: str, *, vanished: bool) -> FsFact:
    return FsFact(
        presence="unknown",
        kind="unconfirmed_missing",
        errno=None,
        detail=f"{absolute_path}: absence not corroborated (vanished={vanished})",
    )


def authorize_absent(
    *,
    rel_path: str,
    absolute_path: str,
    reconciled_folders: Mapping[str, frozenset[str]],
    unreconciled_folders: Collection[str],
    vanished_folders: Collection[str],
    uninspected_scope: Collection[str],
) -> FsFact:
    """Authorize presence/absence for one song path from this pass's listings.

    ``reconciled_folders`` maps a successfully enumerated folder rel-path to that
    folder's raw listing names (key presence = reconciliation authority). ``absent``
    is produced iff the path's immediate parent was enumerated and the basename is
    absent from that folder's raw names, or the immediate parent folder itself is
    corroborated absent via the folder-level witness (a vanished folder or untracked
    orphan whose nearest enumerated ancestor omits it). Ordinary unreconciled scope
    is immediate-parent-only; discovery-uninspected scope is ancestry-aware. No
    filesystem call is issued.
    """
    parent = rel_path.rsplit("/", 1)[0] if "/" in rel_path else ""
    basename = rel_path.rsplit("/", 1)[-1]

    if scope_uninspected(parent, uninspected_scope) or parent in unreconciled_folders:
        return _unknown_fact(absolute_path, vanished=parent in vanished_folders)
    if parent in reconciled_folders:
        if basename in reconciled_folders[parent]:
            return FsFact(presence="present", kind=None, errno=None)
        return FsFact(presence="absent", kind="resource_missing", errno=None)
    if _folder_absent(parent, reconciled_folders, uninspected_scope):
        return FsFact(presence="absent", kind="resource_missing", errno=None)
    return _unknown_fact(absolute_path, vanished=parent in vanished_folders)


def iter_orphaned_absent_paths(
    db: Database,
    library: Library,
    *,
    reconciled_folders: Mapping[str, frozenset[str]],
    unreconciled_folders: Collection[str],
    vanished_folders: Collection[str],
    uninspected_scope: Collection[str],
    skip_parents: Collection[str],
    page_size: int = 500,
) -> Iterator[list[str]]:
    """Yield pages of song paths corroborated absent outside normal reconciliation.

    Pages the library's songs by natural key (``normalized_path``), one page in
    memory at a time. A song whose direct parent is in ``skip_parents`` (the
    ordinary reconciliation scope) is skipped; every other song is yielded only
    when ``authorize_absent`` corroborates it as ``absent``. Bounded memory; time
    is O(all songs) per full scan.
    """
    after: str | None = None
    while True:
        page = db.library.list_songs_after_normalized_path(
            library,
            after_normalized_path=after,
            limit=page_size,
        )
        if not page:
            break
        dead = [
            song.path
            for song in page
            if (song.normalized_path.rsplit("/", 1)[0] if "/" in song.normalized_path else "") not in skip_parents
            and authorize_absent(
                rel_path=song.normalized_path,
                absolute_path=song.path,
                reconciled_folders=reconciled_folders,
                unreconciled_folders=unreconciled_folders,
                vanished_folders=vanished_folders,
                uninspected_scope=uninspected_scope,
            ).presence
            == "absent"
        ]
        if dead:
            yield dead
        if len(page) < page_size:
            break
        after = page[-1].normalized_path
