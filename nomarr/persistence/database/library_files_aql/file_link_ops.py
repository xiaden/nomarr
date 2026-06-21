from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.schema import CollectionNames

from ._helpers import _as_document_id, _extract_key

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class FileLinkOpsMixin:
    """Mixin for file-link edge and truncation operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    ``self.FILE_COLLECTION``, ``self.LIBRARY_FILE_EDGE_COLLECTION``,
    ``self.list_library_file_ids()``, and ``self._truncate_collection()``.
    """

    _db: SafeDatabase
    FILE_COLLECTION: str = CollectionNames.LIBRARY_FILES.value
    LIBRARY_COLLECTION: str = CollectionNames.LIBRARIES.value
    LIBRARY_FILE_EDGE_COLLECTION: str = CollectionNames.LIBRARY_CONTAINS_FILE.value
    LIBRARY_FOLDER_EDGE_COLLECTION: str = CollectionNames.LIBRARY_CONTAINS_FOLDER.value

    def _truncate_collection(self, collection_name: str) -> None: ...

    def list_library_file_ids(self, library_id: str, *, limit: int | None = None) -> list[str]:
        raise NotImplementedError

    def _link_file_to_library(self, library_id: str, file_id: str) -> None:
        primitives.upsert_edge(
            self._db,
            self.LIBRARY_FILE_EDGE_COLLECTION,
            _as_document_id(self.LIBRARY_COLLECTION, library_id),
            _as_document_id(self.FILE_COLLECTION, file_id),
        )

    def _upsert_file_links_batch(self, links: list[dict[str, Any]]) -> None:
        for link in links:
            self._link_file_to_library(
                str(link["library_id"]),
                str(link["file_id"]),
            )

    def _upsert_library_file_links_batch(self, links: list[dict[str, Any]]) -> None:
        for link in links:
            self._link_file_to_library(
                str(link["_from"]),
                str(link["_to"]),
            )

    def _delete_files_for_library(self, library_id: str) -> int:
        file_ids = self.list_library_file_ids(library_id, limit=None)
        if not file_ids:
            return 0
        keys = [_extract_key(file_id) for file_id in file_ids]
        return primitives.delete_many_by_keys(self._db, self.FILE_COLLECTION, keys)

    def _delete_all_file_links_for_library(self, library_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.LIBRARY_FILE_EDGE_COLLECTION,
            from_id=_as_document_id(self.LIBRARY_COLLECTION, library_id),
        )

    def truncate_file_links(self) -> None:
        self._truncate_collection(self.LIBRARY_FILE_EDGE_COLLECTION)
