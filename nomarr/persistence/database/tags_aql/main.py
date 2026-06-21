from __future__ import annotations

from typing import cast

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.schema import CollectionNames

from ._helpers import Document, _as_document_id, _extract_key
from .tag_edge_ops import TagEdgeOpsMixin
from .tag_search_ops import TagSearchOpsMixin


class TagsAqlOperations(TagSearchOpsMixin, TagEdgeOpsMixin):
    """Thin Tier 2 bindings for tag documents and file↔tag traversals."""

    COLLECTION = CollectionNames.TAGS.value
    EDGE_COLLECTION = CollectionNames.SONG_HAS_TAGS.value
    FILE_STATE_EDGE_COLLECTION = CollectionNames.FILE_HAS_STATE.value
    FILE_COLLECTION = CollectionNames.LIBRARY_FILES.value
    ALLOWED_FIELDS = frozenset({"name", "value"})
    ALLOWED_AGGREGATE_FIELDS = frozenset({"_id", "_key", "name", "value"})

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def get_tag(self, tag_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.COLLECTION, [_extract_key(tag_id)])
        return results[0] if results else None

    def get_tags_for_file(self, file_id: str) -> list[Document]:
        return cast(
            "list[Document]",
            primitives.execute(
                self._db,
                """
                FOR edge IN @@edge_collection
                    FILTER edge._from == @file_id
                    LET tag = DOCUMENT(edge._to)
                    FILTER tag != null
                    RETURN tag
                """,
                bind_vars={
                    "@edge_collection": self.EDGE_COLLECTION,
                    "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
                },
            ),
        )

    def truncate_tags(self) -> None:
        self._truncate_collection(self.COLLECTION)

    def truncate_song_tag_edges(self) -> None:
        self._truncate_collection(self.EDGE_COLLECTION)

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection OPTIONS { ignoreErrors: true }
            """,
            bind_vars={"@collection": collection_name},
        )
