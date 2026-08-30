"""Persistence-layer mappers for the library surface.

Ownership (per artifacts/designs/parts/library-domain-facades/CONTRACTS.md and
ADR-032/ADR-041): ``Library`` (in ``nomarr/helpers/dataclasses/library_dataclass.py``)
is the natural ``(name, root_path)`` domain object; this module lives in the
persistence layer and owns the row-to-domain and domain-to-storage-payload
conversions. It imports helpers dataclasses/DTOs only — never components,
services, workflows, or interfaces.

Storage aliases that stay inside persistence and are translated here:
- ``path``        -> ``root_path``
- ``library_type``-> ``is_enabled`` (``"music"``/``"disabled"`` are storage values)
- ``auto_tag``    -> derived ``watch_mode``: ``auto_tag = int(watch_mode != "off")``
- ``auto_curate`` -> ``library_auto_write``
Generated ``id`` and ``LibraryRow`` never cross this module's public boundary.

Timestamp convention (per Nomarr time-unit conventions and the existing facade):
``created_at``/``updated_at`` are epoch-millisecond integers. ``Library``
carries them as optional pre-persistence; the facade supplies ``now_ms()`` when
a created library has none, and persisted timestamps are always returned.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, cast

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryScan

if TYPE_CHECKING:
    from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryUpdate
    from nomarr.helpers.dto.repo_dto import LibraryRow, LibraryScanRow

__all__ = [
    "library_from_row",
    "library_insert_payload",
    "library_update_payload",
    "scan_from_row",
]


def library_from_row(row: LibraryRow) -> Library:
    """Map a storage ``LibraryRow`` to a domain ``Library``.

    Translation decisions:
    - ``path`` -> ``root_path``
    - ``library_type`` -> ``is_enabled`` (``"disabled"`` is the only disabled pole)
    - ``watch_mode`` -> ``watch_mode`` directly; when the stored ``watch_mode``
      is empty/legacy, fall back to ``"event"`` when ``auto_tag`` is truthy else
      ``"off"`` (mirrors the pre-facade ``_row_to_library_doc`` behavior).
    - ``auto_curate`` -> ``library_auto_write`` (int -> bool)
    - ``created_at``/``updated_at`` are carried through as persisted values.
    The generated ``id`` is dropped here.
    """
    auto_tag = bool(row.get("auto_tag"))
    watch_mode = cast(
        "Literal['off', 'event', 'poll']",
        row.get("watch_mode") or ("event" if auto_tag else "off"),
    )
    return Library(
        name=row["name"],
        root_path=row["path"],
        is_enabled=row.get("library_type") != "disabled",
        watch_mode=watch_mode,
        file_write_mode=cast("Literal['none', 'minimal', 'full']", row.get("file_write_mode") or "full"),
        library_auto_write=bool(row.get("auto_curate")),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


def library_insert_payload(library: Library) -> dict[str, Any]:
    """Translate a domain ``Library`` into the ``libraries`` insert payload.

    Storage-side derivations: ``path`` from ``root_path``, ``library_type`` from
    ``is_enabled``, ``auto_tag`` from ``watch_mode``, ``auto_curate`` from
    ``library_auto_write``. ``created_at``/``updated_at`` are passed through as
    the caller supplied them (the facade fills ``now_ms()`` when absent).
    """
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


def scan_from_row(row: LibraryScanRow) -> LibraryScan:
    """Map a storage ``LibraryScanRow`` to a domain ``LibraryScan``.

    The generated scan ``id`` and the storage ``library_id`` foreign key are
    dropped here — they never cross the facade boundary. ``files_found`` /
    ``files_processed`` map to the domain counters; timestamps are epoch-ms.
    """
    return LibraryScan(
        scan_type=row["scan_type"],
        status=row["status"],
        started_at=row["started_at"],
        heartbeat_at=row["heartbeat_at"],
        files_processed=row["files_processed"],
        files_found=row["files_found"],
        error=row["error"],
        finished_at=row["finished_at"],
    )


def library_update_payload(changes: LibraryUpdate) -> dict[str, Any]:
    """Translate a typed ``LibraryUpdate`` into a ``libraries`` column payload.

    Only the fields that are set (non-``None``) appear in the payload, mirroring
    the old ``update_library(fields)`` dict semantics. ``watch_mode`` also sets
    the derived ``auto_tag`` column; ``is_enabled`` maps to ``library_type``.
    """
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
