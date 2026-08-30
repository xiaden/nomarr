"""Persistence-only mapping for library and scan rows."""

from __future__ import annotations

from typing import Any

from collections.abc import Mapping

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryScan, LibraryUpdate


def library_from_row(row: Mapping[str, Any]) -> Library:
    """Map a repository row to a storage-independent library."""
    return Library(
        name=row["name"],
        root_path=row["path"],
        is_enabled=row["library_type"] != "disabled",
        watch_mode=row.get("watch_mode") or ("event" if row.get("auto_tag") else "off"),
        file_write_mode=row.get("file_write_mode") or "full",
        library_auto_write=bool(row.get("auto_curate")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def library_insert_payload(library: Library) -> dict[str, Any]:
    """Map a domain library to repository insert fields."""
    return {
        "name": library.name,
        "path": library.root_path,
        "library_type": "music" if library.is_enabled else "disabled",
        "auto_tag": int(library.watch_mode != "off"),
        "auto_curate": int(library.library_auto_write),
        "watch_mode": library.watch_mode,
        "file_write_mode": library.file_write_mode,
        "created_at": library.created_at,
        "updated_at": library.updated_at,
    }


def library_update_payload(changes: LibraryUpdate) -> dict[str, Any]:
    """Map typed domain changes to repository update fields."""
    payload: dict[str, Any] = {}
    if changes.name is not None:
        payload["name"] = changes.name
    if changes.root_path is not None:
        payload["path"] = changes.root_path
    if changes.is_enabled is not None:
        payload["library_type"] = "music" if changes.is_enabled else "disabled"
    if changes.watch_mode is not None:
        payload["watch_mode"] = changes.watch_mode
        payload["auto_tag"] = int(changes.watch_mode != "off")
    if changes.file_write_mode is not None:
        payload["file_write_mode"] = changes.file_write_mode
    if changes.library_auto_write is not None:
        payload["auto_curate"] = int(changes.library_auto_write)
    if changes.updated_at is not None:
        payload["updated_at"] = changes.updated_at
    return payload


def scan_from_row(row: Mapping[str, Any]) -> LibraryScan:
    """Map a scan repository row without exposing row identifiers."""
    return LibraryScan(
        scan_type=row["scan_type"],
        status=row["status"],
        started_at=row["started_at"],
        heartbeat_at=row.get("heartbeat_at"),
        finished_at=row.get("finished_at"),
        files_found=row.get("files_found", 0),
        files_processed=row.get("files_processed", 0),
        error=row.get("error"),
    )
