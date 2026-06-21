from __future__ import annotations

from typing import TYPE_CHECKING, Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.schema import CollectionNames

from ._helpers import Document, _as_document_id, _extract_key

if TYPE_CHECKING:
    from nomarr.persistence.arango_client import SafeDatabase


class FolderOpsMixin:
    """Mixin for folder CRUD and truncation operations.

    Requires the host class to provide ``self._db`` (a ``SafeDatabase``),
    ``self.FOLDER_COLLECTION``, ``self.LIBRARY_FOLDER_EDGE_COLLECTION``,
    ``self.ALLOWED_FOLDER_FIELDS``, and ``self._truncate_collection()``.
    """

    _db: SafeDatabase
    FILE_COLLECTION: str = CollectionNames.LIBRARY_FILES.value
    LIBRARY_COLLECTION: str = CollectionNames.LIBRARIES.value
    LIBRARY_FILE_EDGE_COLLECTION: str = CollectionNames.LIBRARY_CONTAINS_FILE.value
    LIBRARY_FOLDER_EDGE_COLLECTION: str = CollectionNames.LIBRARY_CONTAINS_FOLDER.value
    FOLDER_COLLECTION: str
    ALLOWED_FOLDER_FIELDS: frozenset[str]

    def _truncate_collection(self, collection_name: str) -> None: ...

    def add_folder(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.FOLDER_COLLECTION, payload)

    def add_library_folder(self, library_id: str, payload: dict[str, Any]) -> str:
        """Create a folder document and link it to a library.

        Args:
            library_id: Document ID of the library that should own the folder.
            payload: Folder fields to store in the new document.

        Returns:
            The document ID of the created folder.
        """
        folder_id = self.add_folder(payload)
        self._link_folder_to_library(library_id, folder_id)
        return folder_id

    def _link_folder_to_library(self, library_id: str, folder_id: str) -> None:
        primitives.upsert_edge(
            self._db,
            self.LIBRARY_FOLDER_EDGE_COLLECTION,
            _as_document_id(self.LIBRARY_COLLECTION, library_id),
            _as_document_id(self.FOLDER_COLLECTION, folder_id),
        )

    def get_folder(self, folder_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.FOLDER_COLLECTION, [_extract_key(folder_id)])
        return results[0] if results else None

    def list_folders_for_library(self, library_id: str) -> list[Document]:
        return primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @library_id
                LET folder = DOCUMENT(edge._to)
                FILTER folder != null
                SORT folder._key
                RETURN folder
            """,
            {
                "@edge_collection": self.LIBRARY_FOLDER_EDGE_COLLECTION,
                "library_id": _as_document_id(self.LIBRARY_COLLECTION, library_id),
            },
        )

    def _delete_folder(self, folder_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.FOLDER_COLLECTION, [_extract_key(folder_id)])

    def _delete_folder_link(self, library_id: str, folder_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.LIBRARY_FOLDER_EDGE_COLLECTION,
            from_id=_as_document_id(self.LIBRARY_COLLECTION, library_id),
            to_id=_as_document_id(self.FOLDER_COLLECTION, folder_id),
        )

    def remove_library_folder(self, library_id: str, folder_id: str) -> None:
        """Remove a library's folder link and then delete the folder document.

        Args:
            library_id: Document ID of the library linked to the folder.
            folder_id: Document ID of the folder to unlink and delete.
        """
        self._delete_folder_link(library_id, folder_id)
        self._delete_folder(folder_id)

    def replace_library_folders(self, library_id: str, payloads: list[dict[str, Any]]) -> None:
        """Replace all folders linked to a library with the provided set.

        Args:
            library_id: Document ID of the library whose folders should be
                replaced.
            payloads: Folder payloads to insert after existing folders are
                removed.
        """
        existing_folder_ids = [
            str(folder_id)
            for folder in self.list_folders_for_library(library_id)
            if isinstance(folder, dict) and (folder_id := folder.get("_id")) is not None
        ]
        for folder_id in existing_folder_ids:
            self.remove_library_folder(library_id, folder_id)
        for payload in payloads:
            self.add_library_folder(library_id, payload)

    def _delete_folders_for_library(self, library_key: str) -> int:
        return primitives.delete_many_by_field(
            self._db,
            self.FOLDER_COLLECTION,
            "library_key",
            library_key,
            allowed_fields=self.ALLOWED_FOLDER_FIELDS,
        )

    def _delete_all_folder_links_for_library(self, library_id: str) -> None:
        primitives.delete_edges(
            self._db,
            self.LIBRARY_FOLDER_EDGE_COLLECTION,
            from_id=_as_document_id(self.LIBRARY_COLLECTION, library_id),
        )

    def truncate_folders(self) -> None:
        self._truncate_collection(self.FOLDER_COLLECTION)

    def truncate_folder_links(self) -> None:
        self._truncate_collection(self.LIBRARY_FOLDER_EDGE_COLLECTION)
