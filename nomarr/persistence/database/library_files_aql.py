from __future__ import annotations

from typing import Any

from nomarr.persistence.aql import primitives
from nomarr.persistence.arango_client import SafeDatabase

Document = dict[str, Any]


def _extract_key(document_id_or_key: str) -> str:
    return document_id_or_key.split("/", 1)[1] if "/" in document_id_or_key else document_id_or_key


def _as_document_id(collection: str, document_id_or_key: str) -> str:
    return document_id_or_key if "/" in document_id_or_key else f"{collection}/{document_id_or_key}"


class LibraryFilesAqlOperations:
    """Thin Tier 2 bindings for library file, folder, and edge operations."""

    FILE_COLLECTION = "library_files"
    FOLDER_COLLECTION = "library_folders"
    LIBRARY_FILE_EDGE_COLLECTION = "library_contains_file"
    LIBRARY_FOLDER_EDGE_COLLECTION = "library_contains_folder"
    TAG_EDGE_COLLECTION = "song_has_tags"
    TAG_COLLECTION = "tags"

    ALLOWED_FILE_FIELDS = frozenset(
        {
            "path",
            "normalized_path",
            "library_key",
            "status",
            "modified_time",
            "duration_seconds",
            "file_size",
            "album",
            "title",
            "artist",
            "artists",
            "labels",
            "genres",
            "year",
            "scanned_at",
            "chromaprint",
            "is_valid",
            "last_tagged_at",
        },
    )
    ALLOWED_FOLDER_FIELDS = frozenset({"path", "library_key"})
    TEXT_SEARCH_FIELDS = frozenset({"artist", "album", "title"})

    def __init__(self, db: SafeDatabase) -> None:
        self._db = db

    def add_file(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.FILE_COLLECTION, payload)

    def get_file(self, file_id: str) -> Document | None:
        results = primitives.get_many_by_keys(self._db, self.FILE_COLLECTION, [_extract_key(file_id)])
        return results[0] if results else None

    def get_file_by_path_unscoped(self, path: str) -> Document | None:
        results = primitives.get_filtered_docs(
            self._db,
            self.FILE_COLLECTION,
            filters={"path": path},
            sort_field="path",
            limit=1,
            allowed_fields=self.ALLOWED_FILE_FIELDS,
        )
        return results[0] if results else None

    def get_file_by_path(self, path: str, library_id: str) -> Document | None:
        results = primitives.get_filtered_docs(
            self._db,
            self.FILE_COLLECTION,
            filters={"path": path, "library_key": _extract_key(library_id)},
            sort_field="path",
            limit=1,
            allowed_fields=self.ALLOWED_FILE_FIELDS,
        )
        return results[0] if results else None

    def upsert_file(self, payload: dict[str, Any]) -> str:
        path = payload.get("path")
        if not isinstance(path, str) or not path:
            msg = "File payload must include a non-empty 'path' string"
            raise ValueError(msg)
        return primitives.upsert_by_field(self._db, self.FILE_COLLECTION, "path", path, payload)

    def upsert_files_batch(self, payloads: list[dict[str, Any]]) -> list[str]:
        for payload in payloads:
            path = payload.get("path")
            if not isinstance(path, str) or not path:
                msg = "File payload must include a non-empty 'path' string"
                raise ValueError(msg)
        return primitives.upsert_many_by_field(self._db, self.FILE_COLLECTION, "path", payloads)

    def upsert_files_for_library(self, library_id: str, payloads: list[dict[str, Any]]) -> list[str]:
        """Upsert file docs and ensure library→file ownership edges, returning _ids."""
        file_ids = self.upsert_files_batch(payloads)
        edge_docs = [{"_from": library_id, "_to": file_id} for file_id in file_ids]
        if edge_docs:
            self.upsert_library_file_links_batch(edge_docs)
        return file_ids

    def update_file(self, file_id: str, fields: dict[str, Any]) -> None:
        primitives.update_document_by_key(self._db, self.FILE_COLLECTION, _extract_key(file_id), fields)

    def delete_file(self, file_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.FILE_COLLECTION, [_extract_key(file_id)])

    def list_files(self, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[Document]:
        bind_vars: dict[str, Any] = {"@collection": self.FILE_COLLECTION}
        query_lines = ["FOR file IN @@collection"]
        for index, (field_name, value) in enumerate((filters or {}).items()):
            primitives._validate_field_name(field_name)
            if field_name not in self.ALLOWED_FILE_FIELDS:
                msg = f"Unsupported file filter field: {field_name}"
                raise ValueError(msg)
            bind_var = f"value_{index}"
            query_lines.append(f"    FILTER file.{field_name} == @{bind_var}")
            bind_vars[bind_var] = value
        query_lines.append("    SORT file._key")
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def count_files(self) -> int:
        cursor = self._db.aql.execute(
            """
            FOR file IN @@collection
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={"@collection": self.FILE_COLLECTION},
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def get_files_by_ids(self, file_ids: list[str]) -> list[Document]:
        if not file_ids:
            return []
        file_docs = primitives.get_many_by_keys(
            self._db,
            self.FILE_COLLECTION,
            [_extract_key(file_id) for file_id in file_ids],
        )
        docs_by_id = {doc_id: doc for doc in file_docs if isinstance((doc_id := doc.get("_id")), str)}
        normalized_ids = [_as_document_id(self.FILE_COLLECTION, file_id) for file_id in file_ids]
        return [docs_by_id[file_id] for file_id in normalized_ids if file_id in docs_by_id]

    def get_library_ids_for_files(self, file_ids: list[str]) -> dict[str, str]:
        normalized_ids = [_as_document_id(self.FILE_COLLECTION, file_id) for file_id in file_ids]
        if not normalized_ids:
            return {}
        rows = primitives.execute(
            self._db,
            """
            FOR edge IN @@collection
                FILTER edge._to IN @file_ids
                SORT edge._to, edge._from, edge._key
                RETURN { file_id: edge._to, library_id: edge._from }
            """,
            {
                "@collection": self.LIBRARY_FILE_EDGE_COLLECTION,
                "file_ids": normalized_ids,
            },
        )
        result: dict[str, str] = {}
        for row in rows:
            file_id = row.get("file_id")
            library_id = row.get("library_id")
            if isinstance(file_id, str) and isinstance(library_id, str) and file_id not in result:
                result[file_id] = library_id
        return result

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        cursor = self._db.aql.execute(
            """
            FOR file IN @@collection
                FILTER file.last_tagged_at >= @cutoff_ms
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@collection": self.FILE_COLLECTION,
                "cutoff_ms": cutoff_ms,
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        if not paths:
            return []
        cursor = self._db.aql.execute(
            """
            FOR file IN @@collection
                FILTER file.path IN @paths
                COLLECT path = file.path
                SORT path
                RETURN path
            """,
            bind_vars={"@collection": self.FILE_COLLECTION, "paths": paths},
        )
        return [path for path in cursor if isinstance(path, str)]

    def search_files_by_text(self, field_name: str, pattern: str, *, limit: int | None = None) -> list[Document]:
        primitives._validate_field_name(field_name)
        if field_name not in self.TEXT_SEARCH_FIELDS:
            msg = f"Unsupported text-search field: {field_name}"
            raise ValueError(msg)
        bind_vars: dict[str, Any] = {
            "@collection": self.FILE_COLLECTION,
            "pattern": pattern,
        }
        query_lines = [
            "FOR file IN @@collection",
            f"    FILTER LIKE(file.{field_name}, @pattern, true)",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def search_library_files_by_field(self, field: str, value: str, *, limit: int | None = None) -> list[Document]:
        primitives._validate_field_name(field)
        if field not in self.TEXT_SEARCH_FIELDS:
            msg = f"Unsupported library-file search field: {field}"
            raise ValueError(msg)
        bind_vars: dict[str, Any] = {
            "@collection": self.FILE_COLLECTION,
            "value": value,
        }
        query_lines = [
            "FOR file IN @@collection",
            f"    FILTER LOWER(TO_STRING(file.{field})) == LOWER(@value)",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def list_library_file_ids(self, library_id: str, *, limit: int | None = None) -> list[str]:
        bind_vars: dict[str, Any] = {
            "@collection": self.LIBRARY_FILE_EDGE_COLLECTION,
            "library_id": _as_document_id("libraries", library_id),
        }
        query_lines = [
            "FOR edge IN @@collection",
            "    FILTER edge._from == @library_id",
            "    SORT edge._to",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN edge._to")
        cursor = self._db.aql.execute("\n".join(query_lines), bind_vars=bind_vars)
        return list(cursor)

    def list_library_files_for_folder(self, library_id: str, folder_rel_path: str) -> list[Document]:
        """Fetch file docs for a single folder, with ``has_tagged_state`` annotated.

        One query: edge traversal + normalized_path filter + tagged-state sub-query.
        """
        bind_vars: dict[str, Any] = {
            "@lib_edge": self.LIBRARY_FILE_EDGE_COLLECTION,
            "@state_edge": "file_has_state",
            "library_id": _as_document_id("libraries", library_id),
            "is_root": folder_rel_path == "",
            "folder_prefix": f"{folder_rel_path}/",
            "tagged_state_id": "file_states/ml_tagged",
        }
        query = """
        FOR edge IN @@lib_edge
            FILTER edge._from == @library_id
            LET file = DOCUMENT(edge._to)
            FILTER file != null
            FILTER (
                @is_root
                ? NOT CONTAINS(file.normalized_path, '/')
                : STARTS_WITH(file.normalized_path, @folder_prefix)
            )
            LET has_tagged = LENGTH(
                FOR se IN @@state_edge
                    FILTER se._from == file._id AND se._to == @tagged_state_id
                    LIMIT 1
                    RETURN 1
            ) > 0
            SORT file._key
            RETURN MERGE(file, { has_tagged_state: has_tagged })
        """
        return primitives.execute(self._db, query, bind_vars)

    def find_library_file_by_chromaprint(self, library_id: str, chromaprint: str) -> Document | None:
        """Find the first library file matching ``chromaprint``. Returns ``None`` if not found."""
        results = primitives.execute(
            self._db,
            """
            FOR edge IN @@edge_collection
                FILTER edge._from == @library_id
                LET file = DOCUMENT(edge._to)
                FILTER file != null AND file.chromaprint == @chromaprint
                LIMIT 1
                RETURN file
            """,
            {
                "@edge_collection": self.LIBRARY_FILE_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
                "chromaprint": chromaprint,
            },
        )
        return results[0] if results else None

    def list_library_files(self, library_id: str, *, limit: int | None = None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.LIBRARY_FILE_EDGE_COLLECTION,
            "library_id": _as_document_id("libraries", library_id),
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._from == @library_id",
            "    LET file = DOCUMENT(edge._to)",
            "    FILTER file != null",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def count_library_file_links(self, library_id: str) -> int:
        cursor = self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                COLLECT WITH COUNT INTO count
                RETURN count
            """,
            bind_vars={
                "@collection": self.LIBRARY_FILE_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
            },
        )
        results = list(cursor)
        return int(results[0]) if results else 0

    def delete_files_for_library(self, library_key: str) -> int:
        file_docs = primitives.get_many_by_field(
            self._db,
            self.FILE_COLLECTION,
            "library_key",
            library_key,
            limit=None,
            allowed_fields=self.ALLOWED_FILE_FIELDS,
        )
        keys = [doc["_key"] for doc in file_docs if isinstance(doc.get("_key"), str)]
        if not keys:
            return 0
        return primitives.delete_many_by_keys(self._db, self.FILE_COLLECTION, keys)

    def delete_all_file_links_for_library(self, library_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_FILE_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
            },
        )

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        return primitives.count_distinct_edge_sources_to_filtered_vertices(
            self._db,
            edge_collection=self.TAG_EDGE_COLLECTION,
            vertex_collection=self.TAG_COLLECTION,
            vertex_filters={"name": tag_key, "value": target_value},
        )

    def get_artist_album_frequencies(self, limit: int) -> dict[str, list[tuple[str, int]]]:
        bind_vars = {"@collection": self.FILE_COLLECTION, "limit": limit}
        artist_rows = primitives.execute(
            self._db,
            """
            FOR file IN @@collection
                FILTER file.artist != null
                COLLECT value = file.artist WITH COUNT INTO count
                SORT count DESC, value
                LIMIT @limit
                RETURN { value: value, count: count }
            """,
            bind_vars,
        )
        album_rows = primitives.execute(
            self._db,
            """
            FOR file IN @@collection
                FILTER file.album != null
                COLLECT value = file.album WITH COUNT INTO count
                SORT count DESC, value
                LIMIT @limit
                RETURN { value: value, count: count }
            """,
            bind_vars,
        )
        return {
            "artist_rows": [
                (value, row["count"])
                for row in artist_rows
                if isinstance((value := row.get("value")), str) and isinstance(row.get("count"), int)
            ],
            "album_rows": [
                (value, row["count"])
                for row in album_rows
                if isinstance((value := row.get("value")), str) and isinstance(row.get("count"), int)
            ],
        }

    def get_tracks_for_matching(self, library_id: str, *, limit: int | None) -> list[Document]:
        bind_vars: dict[str, Any] = {
            "@edge_collection": self.LIBRARY_FILE_EDGE_COLLECTION,
            "library_id": _as_document_id("libraries", library_id),
        }
        query_lines = [
            "FOR edge IN @@edge_collection",
            "    FILTER edge._from == @library_id",
            "    LET file = DOCUMENT(edge._to)",
            "    FILTER file != null",
            "    SORT file._key",
        ]
        normalized_limit = primitives.normalize_limit(limit)
        if normalized_limit is not None:
            query_lines.append("    LIMIT @limit")
            bind_vars["limit"] = normalized_limit
        query_lines.append("    RETURN file")
        return primitives.execute(self._db, "\n".join(query_lines), bind_vars)

    def link_file_to_library(self, library_id: str, file_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @library_id, _to: @file_id }
                INSERT { _from: @library_id, _to: @file_id }
                UPDATE {}
                IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_FILE_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
                "file_id": _as_document_id(self.FILE_COLLECTION, file_id),
            },
        )

    def upsert_file_links_batch(self, links: list[dict[str, Any]]) -> None:
        for link in links:
            self.link_file_to_library(
                str(link["library_id"]),
                str(link["file_id"]),
            )

    def upsert_library_file_links_batch(self, links: list[dict[str, Any]]) -> None:
        for link in links:
            self.link_file_to_library(
                str(link["_from"]),
                str(link["_to"]),
            )

    def add_folder(self, payload: dict[str, Any]) -> str:
        return primitives.insert_document(self._db, self.FOLDER_COLLECTION, payload)

    def link_folder_to_library(self, library_id: str, folder_id: str) -> None:
        self._db.aql.execute(
            """
            UPSERT { _from: @library_id, _to: @folder_id }
                INSERT { _from: @library_id, _to: @folder_id }
                UPDATE {}
                IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_FOLDER_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
                "folder_id": _as_document_id(self.FOLDER_COLLECTION, folder_id),
            },
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
                "library_id": _as_document_id("libraries", library_id),
            },
        )

    def delete_folder(self, folder_id: str) -> None:
        primitives.delete_many_by_keys(self._db, self.FOLDER_COLLECTION, [_extract_key(folder_id)])

    def delete_folder_link(self, library_id: str, folder_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                FILTER edge._to == @folder_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_FOLDER_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
                "folder_id": _as_document_id(self.FOLDER_COLLECTION, folder_id),
            },
        )

    def delete_folders_for_library(self, library_key: str) -> int:
        folder_docs = primitives.get_many_by_field(
            self._db,
            self.FOLDER_COLLECTION,
            "library_key",
            library_key,
            limit=None,
            allowed_fields=self.ALLOWED_FOLDER_FIELDS,
        )
        keys = [doc["_key"] for doc in folder_docs if isinstance(doc.get("_key"), str)]
        if not keys:
            return 0
        return primitives.delete_many_by_keys(self._db, self.FOLDER_COLLECTION, keys)

    def delete_all_folder_links_for_library(self, library_id: str) -> None:
        self._db.aql.execute(
            """
            FOR edge IN @@collection
                FILTER edge._from == @library_id
                REMOVE edge IN @@collection
            """,
            bind_vars={
                "@collection": self.LIBRARY_FOLDER_EDGE_COLLECTION,
                "library_id": _as_document_id("libraries", library_id),
            },
        )

    def truncate_files(self) -> None:
        self._truncate_collection(self.FILE_COLLECTION)

    def truncate_file_links(self) -> None:
        self._truncate_collection(self.LIBRARY_FILE_EDGE_COLLECTION)

    def truncate_folder_links(self) -> None:
        self._truncate_collection(self.LIBRARY_FOLDER_EDGE_COLLECTION)

    def truncate_folders(self) -> None:
        self._truncate_collection(self.FOLDER_COLLECTION)

    def _truncate_collection(self, collection_name: str) -> None:
        self._db.aql.execute(
            """
            FOR doc IN @@collection
                REMOVE doc IN @@collection
            """,
            bind_vars={"@collection": collection_name},
        )
