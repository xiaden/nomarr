from __future__ import annotations

import hashlib
from typing import Any, cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


def _edge_key(left_id: str, right_id: str) -> str:
    return hashlib.sha256(f"{left_id}:{right_id}".encode()).hexdigest()[:16]


class NavidromeAqlOperations:
    """Thin Tier 2 bindings for Navidrome track mapping records."""

    TRACK_COLLECTION = "navidrome_tracks"
    ND_ID_EDGE_COLLECTION = "has_nd_id"
    PLAY_EDGE_COLLECTION = "has_plays"
    PLAYCOUNT_COLLECTION = "navidrome_playcounts"

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_nd_track(self, track_id: str) -> Document | None:
        results = primitives.execute(
            self._db,
            """
            FOR track IN @@collection
                FILTER track._key == @track_key
                LET file_id = FIRST(
                    FOR edge IN @@edge_collection
                        FILTER edge._from == track._id
                        LIMIT 1
                        RETURN edge._to
                )
                RETURN MERGE(track, { file_id: file_id })
            """,
            {
                "@collection": self.TRACK_COLLECTION,
                "@edge_collection": self.ND_ID_EDGE_COLLECTION,
                "track_key": _extract_key(track_id),
            },
        )
        return results[0] if results else None

    def list_nd_track_keys(self) -> list[str]:
        cursor = self._db.aql.execute(
            """
            FOR track IN @@collection
                SORT track._key
                RETURN track._key
            """,
            bind_vars={"@collection": self.TRACK_COLLECTION},
        )
        return [row for row in cursor if isinstance(row, str)]

    def upsert_nd_track(self, payload: dict[str, Any]) -> None:
        track_key = self._resolve_track_key(payload)
        cursor = self._db.aql.execute(
            """
            UPSERT { _key: @track_key }
                INSERT MERGE(@payload, { _key: @track_key })
                UPDATE @payload
                IN @@collection
                RETURN NEW._id
            """,
            bind_vars={"@collection": self.TRACK_COLLECTION, "track_key": track_key, "payload": payload},
        )
        results = list(cursor)
        track_doc_id = cast("str", results[0])

        file_id = payload.get("file_id")
        if isinstance(file_id, str) and file_id:
            self.ensure_nd_file_link(track_doc_id, file_id)

    def bulk_upsert_nd_tracks(self, nd_ids: list[str]) -> int:
        track_keys = [_extract_key(nd_id) for nd_id in nd_ids if _extract_key(nd_id)]
        if not track_keys:
            return 0
        rows = primitives.execute(
            self._db,
            """
            FOR track_key IN @track_keys
                UPSERT { _key: track_key }
                    INSERT { _key: track_key }
                    UPDATE {}
                    IN @@collection
                RETURN 1
            """,
            {"@collection": self.TRACK_COLLECTION, "track_keys": track_keys},
        )
        return len(rows)

    def delete_nd_tracks_for_file(self, file_id: str) -> None:
        self._db.aql.execute(
            """
            LET track_ids = (
                FOR edge IN @@nd_edge_collection
                    FILTER edge._to == @file_id
                    RETURN edge._from
            )
            LET playcount_ids = UNIQUE(
                FOR edge IN @@play_edge_collection
                    FILTER edge._from IN track_ids
                    RETURN edge._to
            )
            FOR edge IN @@play_edge_collection
                FILTER edge._from IN track_ids
                REMOVE edge IN @@play_edge_collection
            FOR playcount_id IN playcount_ids
                FILTER LENGTH(
                    FOR edge IN @@play_edge_collection
                        FILTER edge._to == playcount_id
                        LIMIT 1
                        RETURN 1
                ) == 0
                REMOVE playcount_id IN @@playcount_collection
                OPTIONS { ignoreErrors: true }
            FOR edge IN @@nd_edge_collection
                FILTER edge._to == @file_id
                REMOVE edge IN @@nd_edge_collection
            FOR track_id IN track_ids
                REMOVE track_id IN @@track_collection
                OPTIONS { ignoreErrors: true }
            """,
            bind_vars={
                "@nd_edge_collection": self.ND_ID_EDGE_COLLECTION,
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "@playcount_collection": self.PLAYCOUNT_COLLECTION,
                "@track_collection": self.TRACK_COLLECTION,
                "file_id": _as_document_id("library_files", file_id),
            },
        )

    def delete_nd_tracks_cascade(self, nd_ids: list[str]) -> int:
        track_keys = [_extract_key(nd_id) for nd_id in nd_ids if _extract_key(nd_id)]
        if not track_keys:
            return 0
        rows = primitives.execute(
            self._db,
            """
            LET track_ids = (
                FOR track_key IN @track_keys
                    RETURN CONCAT(@track_collection_name, "/", track_key)
            )
            LET deleted_count = LENGTH(
                FOR track IN @@track_collection
                    FILTER track._id IN track_ids
                    RETURN 1
            )
            LET playcount_ids = UNIQUE(
                FOR edge IN @@play_edge_collection
                    FILTER edge._from IN track_ids
                    RETURN edge._to
            )
            FOR edge IN @@nd_edge_collection
                FILTER edge._from IN track_ids
                REMOVE edge IN @@nd_edge_collection
            FOR edge IN @@play_edge_collection
                FILTER edge._from IN track_ids
                REMOVE edge IN @@play_edge_collection
            FOR playcount_id IN playcount_ids
                FILTER LENGTH(
                    FOR edge IN @@play_edge_collection
                        FILTER edge._to == playcount_id
                        LIMIT 1
                        RETURN 1
                ) == 0
                REMOVE playcount_id IN @@playcount_collection
                OPTIONS { ignoreErrors: true }
            FOR track_id IN track_ids
                REMOVE track_id IN @@track_collection
                OPTIONS { ignoreErrors: true }
            RETURN deleted_count
            """,
            {
                "@track_collection": self.TRACK_COLLECTION,
                "@nd_edge_collection": self.ND_ID_EDGE_COLLECTION,
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "@playcount_collection": self.PLAYCOUNT_COLLECTION,
                "track_collection_name": self.TRACK_COLLECTION,
                "track_keys": track_keys,
            },
        )
        return int(cast("int", rows[0])) if rows else 0

    def ensure_nd_file_link(self, nd_id: str, file_id: str) -> None:
        track_id = _as_document_id(self.TRACK_COLLECTION, nd_id)
        normalized_file_id = _as_document_id("library_files", file_id)
        primitives.execute(
            self._db,
            """
            UPSERT { _from: @track_id, _to: @file_id }
                INSERT { _key: @edge_key, _from: @track_id, _to: @file_id }
                UPDATE {}
                IN @@collection
            """,
            {
                "@collection": self.ND_ID_EDGE_COLLECTION,
                "track_id": track_id,
                "file_id": normalized_file_id,
                "edge_key": _edge_key(track_id, normalized_file_id),
            },
        )

    def bulk_ensure_nd_file_links(self, mappings: list[dict[str, Any]]) -> int:
        normalized_mappings = [
            {
                "_key": _edge_key(
                    _as_document_id(self.TRACK_COLLECTION, cast("str", mapping["nd_id"])),
                    _as_document_id("library_files", cast("str", mapping["file_id"])),
                ),
                "_from": _as_document_id(self.TRACK_COLLECTION, cast("str", mapping["nd_id"])),
                "_to": _as_document_id("library_files", cast("str", mapping["file_id"])),
            }
            for mapping in mappings
            if isinstance(mapping.get("nd_id"), str) and isinstance(mapping.get("file_id"), str)
        ]
        if not normalized_mappings:
            return 0
        track_ids = sorted({mapping["_from"] for mapping in normalized_mappings})
        rows = primitives.execute(
            self._db,
            """
            LET existing_pairs = UNIQUE(
                FOR edge IN @@collection
                    FILTER edge._from IN @track_ids
                    RETURN CONCAT(edge._from, "|", edge._to)
            )
            FOR mapping IN @mappings
                FILTER CONCAT(mapping._from, "|", mapping._to) NOT IN existing_pairs
                INSERT mapping INTO @@collection
                RETURN 1
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "track_ids": track_ids, "mappings": normalized_mappings},
        )
        return len(rows)

    def resolve_nd_track_to_file(self, nd_id: str) -> str | None:
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from == @track_id
                SORT edge._key
                LIMIT 1
                RETURN edge._to
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "track_id": _as_document_id(self.TRACK_COLLECTION, nd_id)},
        )
        return cast("str", rows[0]) if rows else None

    def resolve_file_to_nd_track(self, file_id: str) -> str | None:
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._to == @file_id
                SORT edge._key
                LIMIT 1
                RETURN PARSE_IDENTIFIER(edge._from).key
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "file_id": _as_document_id("library_files", file_id)},
        )
        return cast("str", rows[0]) if rows else None

    def bulk_resolve_nd_tracks_to_files(self, nd_ids: list[str]) -> dict[str, str]:
        track_ids = [_as_document_id(self.TRACK_COLLECTION, nd_id) for nd_id in nd_ids]
        if not track_ids:
            return {}
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from IN @track_ids
                RETURN { nd_id: PARSE_IDENTIFIER(edge._from).key, file_id: edge._to }
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "track_ids": track_ids},
        )
        result: dict[str, str] = {}
        for row in rows:
            nd_id = row.get("nd_id")
            file_id = row.get("file_id")
            if isinstance(nd_id, str) and isinstance(file_id, str) and nd_id not in result:
                result[nd_id] = file_id
        return result

    def bulk_resolve_files_to_nd_ids(self, file_ids: list[str]) -> dict[str, str]:
        normalized_file_ids = [_as_document_id("library_files", file_id) for file_id in file_ids]
        if not normalized_file_ids:
            return {}
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._to IN @file_ids
                RETURN { file_id: edge._to, nd_id: PARSE_IDENTIFIER(edge._from).key }
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "file_ids": normalized_file_ids},
        )
        result: dict[str, str] = {}
        for row in rows:
            file_id = row.get("file_id")
            nd_id = row.get("nd_id")
            if isinstance(file_id, str) and isinstance(nd_id, str) and file_id not in result:
                result[file_id] = nd_id
        return result

    def upsert_nd_playcount(self, user_id: str, nd_id: str, playcount: int, last_played: int) -> None:
        track_id = _as_document_id(self.TRACK_COLLECTION, nd_id)
        bucket_key = f"{playcount}:{user_id}"
        bucket_id = _as_document_id(self.PLAYCOUNT_COLLECTION, bucket_key)
        primitives.execute(
            self._db,
            """
            LET stale_bucket_ids = UNIQUE(
                FOR edge IN @@play_edge_collection
                    FILTER edge._from == @track_id
                    LET bucket = DOCUMENT(edge._to)
                    FILTER bucket != null AND bucket.userid == @user_id
                    REMOVE edge IN @@play_edge_collection
                    RETURN edge._to
            )
            FOR bucket_id IN stale_bucket_ids
                FILTER LENGTH(
                    FOR edge IN @@play_edge_collection
                        FILTER edge._to == bucket_id
                        LIMIT 1
                        RETURN 1
                ) == 0
                REMOVE bucket_id IN @@playcount_collection
                OPTIONS { ignoreErrors: true }
            UPSERT { _key: @bucket_key }
                INSERT { _key: @bucket_key, playcount: @playcount, userid: @user_id }
                UPDATE { playcount: @playcount, userid: @user_id }
                IN @@playcount_collection
            UPSERT { _from: @track_id, _to: @bucket_id }
                INSERT { _key: @edge_key, _from: @track_id, _to: @bucket_id, last_played: @last_played }
                UPDATE { last_played: @last_played }
                IN @@play_edge_collection
            """,
            {
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "@playcount_collection": self.PLAYCOUNT_COLLECTION,
                "track_id": track_id,
                "user_id": user_id,
                "bucket_key": bucket_key,
                "bucket_id": bucket_id,
                "playcount": playcount,
                "last_played": last_played,
                "edge_key": _edge_key(track_id, bucket_id),
            },
        )

    def increment_nd_play(self, user_id: str, nd_id: str, timestamp_ms: int) -> None:
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@play_edge_collection
                FILTER edge._from == @track_id
                LET bucket = DOCUMENT(edge._to)
                FILTER bucket != null AND bucket.userid == @user_id
                SORT TO_NUMBER(bucket.playcount) DESC, edge._key
                LIMIT 1
                RETURN bucket.playcount
            """,
            {
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "track_id": _as_document_id(self.TRACK_COLLECTION, nd_id),
                "user_id": user_id,
            },
        )
        current_playcount = int(cast("int", rows[0])) if rows else 0
        self.upsert_nd_playcount(user_id, nd_id, current_playcount + 1, timestamp_ms)

    def bulk_upsert_nd_plays(self, user_id: str, plays: list[dict[str, Any]]) -> int:
        bucket_docs_by_key: dict[str, dict[str, Any]] = {}
        edge_docs: list[dict[str, Any]] = []
        for play in plays:
            nd_id = play.get("nd_id")
            playcount = play.get("playcount")
            last_played = play.get("last_played")
            if not isinstance(nd_id, str) or not isinstance(playcount, int) or not isinstance(last_played, int):
                continue
            bucket_key = f"{playcount}:{user_id}"
            bucket_docs_by_key.setdefault(
                bucket_key,
                {"_key": bucket_key, "playcount": playcount, "userid": user_id},
            )
            track_id = _as_document_id(self.TRACK_COLLECTION, nd_id)
            bucket_id = _as_document_id(self.PLAYCOUNT_COLLECTION, bucket_key)
            edge_docs.append(
                {
                    "_key": _edge_key(track_id, bucket_id),
                    "_from": track_id,
                    "_to": bucket_id,
                    "last_played": last_played,
                }
            )

        primitives.execute(
            self._db,
            """
            LET old_bucket_ids = (
                FOR bucket IN @@playcount_collection
                    FILTER bucket.userid == @user_id
                    RETURN bucket._id
            )
            FOR edge IN @@play_edge_collection
                FILTER edge._to IN old_bucket_ids
                REMOVE edge IN @@play_edge_collection
            FOR bucket_id IN old_bucket_ids
                REMOVE bucket_id IN @@playcount_collection
                OPTIONS { ignoreErrors: true }
            FOR bucket_doc IN @bucket_docs
                UPSERT { _key: bucket_doc._key }
                    INSERT bucket_doc
                    UPDATE UNSET(bucket_doc, "_key")
                    IN @@playcount_collection
            FOR edge_doc IN @edge_docs
                INSERT edge_doc INTO @@play_edge_collection
                OPTIONS { overwriteMode: "ignore" }
            """,
            {
                "@playcount_collection": self.PLAYCOUNT_COLLECTION,
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "user_id": user_id,
                "bucket_docs": list(bucket_docs_by_key.values()),
                "edge_docs": edge_docs,
            },
        )
        return len(edge_docs)

    def get_top_nd_plays(self, user_id: str, top_n: int) -> list[Document]:
        if top_n <= 0:
            return []
        return primitives.execute(
            self._db,
            """
            FOR bucket IN @@playcount_collection
                FILTER bucket.userid == @user_id
                FOR edge IN @@play_edge_collection
                    FILTER edge._to == bucket._id
                    LET file_id = FIRST(
                        FOR file_edge IN @@nd_edge_collection
                            FILTER file_edge._from == edge._from
                            SORT file_edge._key
                            LIMIT 1
                            RETURN file_edge._to
                    )
                    SORT TO_NUMBER(bucket.playcount) DESC, edge.last_played DESC, edge._key
                    LIMIT @top_n
                    RETURN {
                        nd_id: PARSE_IDENTIFIER(edge._from).key,
                        file_id: file_id,
                        playcount: bucket.playcount,
                        last_played: edge.last_played
                    }
            """,
            {
                "@playcount_collection": self.PLAYCOUNT_COLLECTION,
                "@play_edge_collection": self.PLAY_EDGE_COLLECTION,
                "@nd_edge_collection": self.ND_ID_EDGE_COLLECTION,
                "user_id": user_id,
                "top_n": top_n,
            },
        )

    def get_nd_id_edge(self, track_id: str) -> Document | None:
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._from == @track_id
                SORT edge._key
                LIMIT 1
                RETURN edge
            """,
            {"@collection": self.ND_ID_EDGE_COLLECTION, "track_id": _as_document_id(self.TRACK_COLLECTION, track_id)},
        )
        return rows[0] if rows else None

    def _resolve_track_key(self, payload: dict[str, Any]) -> str:
        for candidate_key in ("_key", "track_id", "id", "nd_id"):
            candidate = payload.get(candidate_key)
            if isinstance(candidate, str) and candidate:
                return _extract_key(candidate)
        track_id = payload.get("_id")
        if isinstance(track_id, str) and track_id:
            return _extract_key(track_id)
        msg = "Navidrome track payload must include one of '_key', '_id', 'track_id', 'id', or 'nd_id'"
        raise ValueError(msg)
