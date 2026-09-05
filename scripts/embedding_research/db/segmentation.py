"""Retained §B ready-row ``patch_count`` seam (Plan C, P1-S12).

The pre-compact segmentation vocabulary — the research ``seg_config`` / ``seg_meta`` /
``seg_membership`` tables, their ``seg_*_columns`` column-order tuples, the membership
duplicate / orphan / member-index guards and their typed error subtypes, and the
``SegMembershipRecord``-era write path — was retired at P1-S12.  The durable compact
catalog schema and its integrity guards now live in ``catalog_storage.py`` and are written
only to filesystem snapshots (``catalogs/<catalog-id>/catalog.duckdb``), never to the
research DuckDB.

The ONE seam retained here is the §B ready-row ``patch_count`` reader
(:func:`_verified_stream_patch_count`): it reads ``patch_count`` from the ``status='ready'``
``stream_registry`` row for a song/backbone.  That reader (and the ``STREAM_TABLE`` constant
it consumes, imported from ``streams.records``) survives through Plan C so Plan E can keep
relying on the ready-row handoff while it owns the stream/head registry cleanup.  Nothing
else in this module is retained.
"""

from __future__ import annotations

from scripts.embedding_research.streams.records import STREAM_TABLE

__all__ = [
    "SegStreamNotReadyError",
    "SegmentationError",
    "_verified_stream_patch_count",
]


class SegmentationError(RuntimeError):
    """Base for retained segmentation-catalog seam failures."""


class SegStreamNotReadyError(SegmentationError):
    """No verified ``ready`` source stream exists for the song/backbone a reader needs."""


def _verified_stream_patch_count(con, song_id: str, backbone: str) -> int:
    """Read ``patch_count`` from the ``status='ready'`` stream_registry row (§B seam).

    Retained through Plan C for Plan E's ready-row handoff.  Returns the frozen source
    stream's ``patch_count``; raises :class:`SegStreamNotReadyError` when no ``ready`` row
    exists for ``(song_id, backbone)``.
    """
    row = con.execute(
        f"SELECT patch_count FROM {STREAM_TABLE} WHERE song_id = ? AND backbone = ? AND status = 'ready' LIMIT 1",
        [song_id, backbone],
    ).fetchone()
    if row is None:
        raise SegStreamNotReadyError(
            f"no verified 'ready' frozen source stream for (song_id={song_id!r}, "
            f"backbone={backbone!r}); a ready-row patch_count read requires an immutable "
            "ready stream"
        )
    return int(row[0])
