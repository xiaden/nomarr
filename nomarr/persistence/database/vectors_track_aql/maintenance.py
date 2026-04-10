"""Maintenance operations for hot/cold vectors track collections."""

from typing import Any, cast

from nomarr.persistence.arango_client import DatabaseLike


class VectorsTrackMaintenanceOperations:
    """Maintenance operations for hot/cold vector promotion and enrichment.

    Collection naming:
    - hot: ``vectors_track_hot__{backbone_id}__{library_key}``
    - cold: ``vectors_track_cold__{backbone_id}__{library_key}``
    """

    def __init__(self, db: DatabaseLike, backbone_id: str, library_key: str) -> None:
        self.db = db
        self.backbone_id = backbone_id
        self.library_key = library_key
        self.hot_collection_name = f"vectors_track_hot__{backbone_id}__{library_key}"
        self.cold_collection_name = f"vectors_track_cold__{backbone_id}__{library_key}"
        self.hot_collection = db.collection(self.hot_collection_name)
        self.cold_collection = db.collection(self.cold_collection_name)

    def drain_to_cold(self) -> int:
        """Drain all vectors from hot to cold collection.

        Returns:
            Number of documents drained from hot.

        Raises:
            ValueError: If the hot collection does not exist.
        """
        hot_name = self.hot_collection_name
        cold_name = self.cold_collection_name

        if not self.db.has_collection(hot_name):
            raise ValueError(f"Hot collection '{hot_name}' does not exist")

        if not self.db.has_collection(cold_name):
            self.db.create_collection(cold_name)

        hot_count = self.hot_collection.count()
        if hot_count == 0:  # type: ignore[operator]  # count() returns int in sync context
            return 0

        cursor = self.db.aql.execute(
            f"""
            FOR doc IN {hot_name}
                LET file_id = FIRST(
                    FOR f IN INBOUND doc file_has_vectors
                        RETURN f._id
                )
                LET genres = (
                    FOR edge IN song_has_tags
                        FILTER edge._from == file_id
                        FOR tag IN tags
                            FILTER tag._id == edge._to AND tag.rel == \"genre\"
                            RETURN tag.value
                )
                UPSERT {{ _key: doc._key }}
                INSERT MERGE(doc, {{ genres: genres }})
                UPDATE MERGE(doc, {{ genres: genres }})
                IN {cold_name}
            COLLECT WITH COUNT INTO drained
            RETURN drained
            """
        )
        results = list(cursor)  # type: ignore[arg-type]
        drained = cast("int", results[0]) if results else 0

        self.db.aql.execute(
            """
            FOR doc IN @@cold_coll
                LET file_id = FIRST(
                    FOR f IN INBOUND doc file_has_vectors
                        RETURN f._id
                )
                FILTER file_id != null
                LET hot_id = CONCAT(@hot_prefix, doc._key)
                LET cold_id = doc._id
                FOR e IN file_has_vectors
                    FILTER e._to == hot_id
                    REMOVE e IN file_has_vectors
                UPSERT { _from: file_id, _to: cold_id }
                INSERT { _from: file_id, _to: cold_id }
                UPDATE {}
                IN file_has_vectors
            """,
            bind_vars=cast(
                "dict[str, Any]",
                {
                    "@cold_coll": cold_name,
                    "hot_prefix": f"{hot_name}/",
                },
            ),
        )

        self.hot_collection.truncate()
        return drained

    def backfill_genres(self) -> int:
        """Backfill genres on cold vector documents.

        Returns:
            Number of cold documents updated with genre data.

        Raises:
            ValueError: If the cold collection does not exist.
        """
        cold_name = self.cold_collection_name
        if not self.db.has_collection(cold_name):
            raise ValueError(
                f"Cold collection '{cold_name}' does not exist. "
                "Run drain_hot_to_cold first to create and populate the cold collection."
            )

        cursor = self.db.aql.execute(
            """
            FOR doc IN @@cold_coll
                LET file_ids = (
                    FOR f IN INBOUND doc file_has_vectors
                        RETURN f._id
                )
                LET file_id = FIRST(file_ids)
                FILTER file_id != null
                LET genres = (
                    FOR edge IN song_has_tags
                        FILTER edge._from == file_id
                        FOR tag IN tags
                            FILTER tag._id == edge._to AND tag.rel == "genre"
                            RETURN tag.value
                )
                UPDATE doc WITH { genres: genres } IN @@cold_coll
                COLLECT WITH COUNT INTO updated
                RETURN updated
            """,
            bind_vars={"@cold_coll": cold_name},
        )
        results = list(cursor)  # type: ignore[arg-type]
        return cast("int", results[0]) if results else 0
