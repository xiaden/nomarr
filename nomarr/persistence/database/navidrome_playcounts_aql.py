"""Navidrome bucketed-playcount operations for ArangoDB.

Manages ``navidrome_playcounts`` vertex collection using a bucketed model
where each vertex represents a (playcount_value, user) pair, and ``has_plays``
edge collection linking tracks to playcount buckets.

Collection schemas:
    navidrome_playcounts:  {_key: "{playcount}:{userid}",
                            playcount: int, userid: str}
    has_plays:             {_from: "navidrome_tracks/{nd_id}",
                            _to: "navidrome_playcounts/{playcount}:{userid}",
                            last_played: int}

The compound index ``[userid, playcount]`` on vertices enables fast sorted
queries.  Edge direction is tracks → buckets so INBOUND traversal from a
bucket finds all tracks with that play count.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from nomarr.helpers.dto.navidrome_dto import TrackPlayData
from nomarr.persistence.arango_client import DatabaseLike

if TYPE_CHECKING:
    from arango.cursor import Cursor

logger = logging.getLogger(__name__)

_PLAYCOUNTS = "navidrome_playcounts"
_HAS_PLAYS = "has_plays"
_TRACKS = "navidrome_tracks"
_HAS_ND_ID = "has_nd_id"


def _bucket_key(playcount: int, user_id: str) -> str:
    """Build the ``_key`` for a playcount bucket vertex."""
    return f"{playcount}:{user_id}"


class NavidromePlaycountsOperations:
    """CRUD operations for bucketed navidrome_playcounts vertices and has_plays edges.

    Each vertex represents a (playcount, userid) pair.  Edges point from
    ``navidrome_tracks/{nd_id}`` to ``navidrome_playcounts/{playcount}:{userid}``
    with ``last_played`` on the edge.
    """

    def __init__(self, db: DatabaseLike) -> None:
        self.db = db

    # ── Single-track operations ──────────────────────────────────────

    def upsert_play(
        self,
        user_id: str,
        nd_id: str,
        playcount: int,
        last_played: int,
    ) -> None:
        """Ensure bucket vertex exists and upsert edge from track to bucket.

        Idempotent — safe to call repeatedly for the same (user, track, count).

        Args:
            user_id: Navidrome user identifier.
            nd_id: Navidrome track identifier.
            playcount: Current play count value.
            last_played: Epoch-millisecond timestamp of last play.
        """
        bkey = _bucket_key(playcount, user_id)
        bucket_id = f"{_PLAYCOUNTS}/{bkey}"
        track_id = f"{_TRACKS}/{nd_id}"

        query = """
        // Ensure bucket vertex
        UPSERT { _key: @bkey }
        INSERT { _key: @bkey, playcount: @playcount, userid: @user_id }
        UPDATE {}
        IN @@playcounts

        // Upsert edge from track → bucket
        UPSERT { _from: @track_id, _to: @bucket_id }
        INSERT { _from: @track_id, _to: @bucket_id, last_played: @last_played }
        UPDATE { last_played: @last_played }
        IN @@has_plays
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={
                "bkey": bkey,
                "playcount": playcount,  # type: ignore[dict-item]
                "user_id": user_id,
                "track_id": track_id,
                "bucket_id": bucket_id,
                "last_played": last_played,  # type: ignore[dict-item]
                "@playcounts": _PLAYCOUNTS,
                "@has_plays": _HAS_PLAYS,
            },
        )
        cursor.close(ignore_missing=True)

    def increment_play(
        self,
        user_id: str,
        nd_id: str,
        timestamp_ms: int,
    ) -> None:
        """Atomically increment play count by moving edge to next bucket.

        Finds the current bucket for (user, track).  If found, deletes the old
        edge and creates a new edge to bucket ``{old+1}:{userid}``.  If no edge
        exists, creates bucket ``1:{userid}`` and a fresh edge.

        Args:
            user_id: Navidrome user identifier.
            nd_id: Navidrome track identifier.
            timestamp_ms: Epoch-millisecond timestamp of the scrobble.
        """
        track_id = f"{_TRACKS}/{nd_id}"

        query = """
        LET existing = FIRST(
            FOR e IN @@has_plays
                FILTER e._from == @track_id
                LET bucket = DOCUMENT(e._to)
                FILTER bucket != null AND bucket.userid == @user_id
                RETURN { edge_key: e._key, old_count: bucket.playcount }
        )

        LET new_count = existing != null ? existing.old_count + 1 : 1
        LET new_bkey = CONCAT(TO_STRING(new_count), ":", @user_id)
        LET new_bucket_id = CONCAT(@playcounts_prefix, new_bkey)

        // Ensure new bucket vertex
        UPSERT { _key: new_bkey }
        INSERT { _key: new_bkey, playcount: new_count, userid: @user_id }
        UPDATE {}
        IN @@playcounts

        // Remove old edge if it existed
        LET _ = (
            existing != null
            ? (FOR x IN [1] REMOVE { _key: existing.edge_key } IN @@has_plays RETURN 1)
            : []
        )

        // Insert new edge to new bucket
        INSERT { _from: @track_id, _to: new_bucket_id, last_played: @timestamp_ms }
        IN @@has_plays

        RETURN { new_count: new_count }
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={
                "track_id": track_id,
                "user_id": user_id,
                "timestamp_ms": timestamp_ms,  # type: ignore[dict-item]
                "playcounts_prefix": f"{_PLAYCOUNTS}/",
                "@playcounts": _PLAYCOUNTS,
                "@has_plays": _HAS_PLAYS,
            },
        )
        cursor.close(ignore_missing=True)

    # ── Bulk sync operations ─────────────────────────────────────────

    def bulk_upsert_plays(
        self,
        user_id: str,
        plays: list[dict[str, Any]],
    ) -> int:
        """Wipe-and-rebuild play data for a user from a full sync.

        Deletes all existing ``has_plays`` edges belonging to *user_id*
        (found via bucket vertices), upserts all required bucket vertices,
        and inserts fresh edges.

        Each dict in *plays* must contain ``nd_id`` (str), ``playcount`` (int),
        and ``last_played`` (int).

        Args:
            user_id: Navidrome user identifier.
            plays: List of play data dicts.

        Returns:
            Number of edges inserted.
        """
        if not plays:
            return 0

        # Step 1: Delete existing edges for this user via bucket vertices
        delete_query = """
        FOR bucket IN @@playcounts
            FILTER bucket.userid == @user_id
            FOR e IN @@has_plays
                FILTER e._to == CONCAT(@playcounts_prefix, bucket._key)
                REMOVE e IN @@has_plays
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            delete_query,
            bind_vars={
                "user_id": user_id,
                "playcounts_prefix": f"{_PLAYCOUNTS}/",
                "@playcounts": _PLAYCOUNTS,
                "@has_plays": _HAS_PLAYS,
            },
        )
        cursor.close(ignore_missing=True)

        # Step 2: Delete orphaned bucket vertices for this user (they'll be recreated)
        cleanup_query = """
        FOR bucket IN @@playcounts
            FILTER bucket.userid == @user_id
            REMOVE bucket IN @@playcounts
        """
        cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            cleanup_query,
            bind_vars={"user_id": user_id, "@playcounts": _PLAYCOUNTS},
        )
        cursor.close(ignore_missing=True)

        # Step 3: Build bucket vertices and edges
        buckets: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        seen_buckets: set[str] = set()

        for p in plays:
            pc: int = p["playcount"]
            bkey = _bucket_key(pc, user_id)
            if bkey not in seen_buckets:
                buckets.append({"_key": bkey, "playcount": pc, "userid": user_id})
                seen_buckets.add(bkey)
            edges.append({
                "_from": f"{_TRACKS}/{p['nd_id']}",
                "_to": f"{_PLAYCOUNTS}/{bkey}",
                "last_played": p["last_played"],
            })

        # Step 4: Insert buckets
        if buckets:
            bucket_query = """
            FOR b IN @buckets
                UPSERT { _key: b._key }
                INSERT b
                UPDATE {}
                IN @@playcounts
            """
            cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
                bucket_query,
                bind_vars={"buckets": buckets, "@playcounts": _PLAYCOUNTS},  # type: ignore[dict-item]
            )
            cursor.close(ignore_missing=True)

        # Step 5: Insert edges
        if edges:
            edge_query = """
            FOR e IN @edges
                INSERT e IN @@has_plays
            """
            cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
                edge_query,
                bind_vars={"edges": edges, "@has_plays": _HAS_PLAYS},  # type: ignore[dict-item]
            )
            cursor.close(ignore_missing=True)

        logger.debug(
            "bulk_upsert_plays: user=%s buckets=%d edges=%d",
            user_id,
            len(buckets),
            len(edges),
        )
        return len(edges)

    # ── Graph traversal ─────────────────────────────────────────────

    def get_top_plays(
        self,
        user_id: str,
        top_n: int,
    ) -> list[TrackPlayData]:
        """Return the top-*top_n* most-played tracks for a user.

        Queries bucketed ``navidrome_playcounts`` vertices filtered by
        ``userid`` and sorted by ``playcount DESC`` (uses the compound
        ``[userid, playcount]`` index).  For each bucket, walks inbound
        ``has_plays`` edges to find tracks and their ``last_played``
        timestamps, then hops outbound via ``has_nd_id`` to resolve
        ``library_files`` IDs.

        Results are ordered by playcount DESC.  If multiple tracks share
        a bucket, they appear in insertion order within that bucket.

        Args:
            user_id: Navidrome user identifier.
            top_n: Maximum number of tracks to return.

        Returns:
            List of :class:`TrackPlayData` dicts sorted by playcount DESC.
        """
        query = """
        FOR bucket IN @@playcounts
            FILTER bucket.userid == @user_id
            SORT bucket.playcount DESC
            FOR track_v, edge IN 1..1 INBOUND bucket @@has_plays
                LET nd_id = track_v._key
                LET file_link = FIRST(
                    FOR link IN @@has_nd_id
                        FILTER link._from == track_v._id
                        LIMIT 1
                        RETURN link._to
                )
                LIMIT @top_n
                RETURN {
                    nd_id: nd_id,
                    file_id: file_link,
                    playcount: bucket.playcount,
                    last_played: edge.last_played
                }
        """
        cursor: Cursor = self.db.aql.execute(  # type: ignore[union-attr, assignment]
            query,
            bind_vars={
                "user_id": user_id,
                "top_n": top_n,  # type: ignore[dict-item]
                "@playcounts": _PLAYCOUNTS,
                "@has_plays": _HAS_PLAYS,
                "@has_nd_id": _HAS_ND_ID,
            },
        )
        result: list[TrackPlayData] = list(cursor)  # type: ignore[arg-type]
        cursor.close(ignore_missing=True)
        return result
