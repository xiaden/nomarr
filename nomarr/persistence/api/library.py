from __future__ import annotations

from typing import Any

from nomarr.persistence.database.libraries_aql import LibrariesAqlOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesAqlOperations
from nomarr.persistence.database.scan_aql import ScanAqlOperations
from nomarr.persistence.database.tags_aql import TagsAqlOperations


class LibraryDb:
    """Persistence sub-facade for library, file, tag, and scan operations."""

    def __init__(
        self,
        *,
        libraries: LibrariesAqlOperations,
        files: LibraryFilesAqlOperations,
        tags: TagsAqlOperations,
        scan: ScanAqlOperations,
    ) -> None:
        self._libraries = libraries
        self._files = files
        self._tags = tags
        self._scan = scan

    def add_library(self, payload: dict) -> str:
        return self._libraries.add_library(payload)

    def get_library(self, library_id: str) -> dict | None:
        return self._libraries.get_library(library_id)

    def get_library_by_name(self, name: str) -> dict | None:
        return self._libraries.get_library_by_name(name)

    def list_libraries(self, *, enabled_only: bool = False) -> list[dict]:
        return self._libraries.list_libraries(enabled_only=enabled_only)

    def list_library_keys(self) -> list[str]:
        return self._libraries.list_library_keys()

    def update_library(self, library_id: str, fields: dict) -> None:
        return self._libraries.update_library(library_id, fields)

    def delete_library(self, library_id: str) -> None:
        return self._libraries.delete_library(library_id)

    def add_file(self, payload: dict) -> str:
        return self._files.add_file(payload)

    def get_file(self, file_id: str) -> dict | None:
        return self._files.get_file(file_id)

    def get_file_by_path_unscoped(self, path: str) -> dict | None:
        return self._files.get_file_by_path_unscoped(path)

    def get_file_by_path(self, path: str, library_id: str) -> dict | None:
        return self._files.get_file_by_path(path, library_id)

    def upsert_file(self, payload: dict) -> str:
        return self._files.upsert_file(payload)

    def upsert_files_batch(self, payloads: list[dict]) -> list[str]:
        return self._files.upsert_files_batch(payloads)

    def upsert_files_for_library(self, library_id: str, payloads: list[dict]) -> list[str]:
        return self._files.upsert_files_for_library(library_id, payloads)

    def update_file(self, file_id: str, fields: dict) -> None:
        return self._files.update_file(file_id, fields)

    def delete_file(self, file_id: str) -> None:
        return self._files.delete_file(file_id)

    def list_files(self, *, filters: dict[str, Any] | None = None, limit: int | None = None) -> list[dict]:
        return self._files.list_files(filters=filters, limit=limit)

    def count_files(self) -> int:
        return self._files.count_files()

    def get_files_by_ids(self, file_ids: list[str]) -> list[dict]:
        return self._files.get_files_by_ids(file_ids)

    def get_library_ids_for_files(self, file_ids: list[str]) -> dict[str, str]:
        return self._files.get_library_ids_for_files(file_ids)

    def count_recently_tagged(self, cutoff_ms: int) -> int:
        return self._files.count_recently_tagged(cutoff_ms)

    def list_existing_file_paths(self, paths: list[str]) -> list[str]:
        return self._files.list_existing_file_paths(paths)

    def search_files_by_text(self, field_name: str, pattern: str, *, limit: int | None = None) -> list[dict]:
        return self._files.search_files_by_text(field_name, pattern, limit=limit)

    def list_library_file_ids(self, library_id: str, *, limit: int | None = None) -> list[str]:
        return self._files.list_library_file_ids(library_id, limit=limit)

    def list_library_files(self, library_id: str, *, limit: int | None = None) -> list[dict]:
        return self._files.list_library_files(library_id, limit=limit)

    def list_library_files_for_folder(self, library_id: str, folder_rel_path: str) -> list[dict]:
        return self._files.list_library_files_for_folder(library_id, folder_rel_path)

    def find_library_file_by_chromaprint(self, library_id: str, chromaprint: str) -> dict | None:
        return self._files.find_library_file_by_chromaprint(library_id, chromaprint)

    def count_library_file_links(self, library_id: str) -> int:
        return self._files.count_library_file_links(library_id)

    def delete_files_for_library(self, library_key: str) -> int:
        return self._files.delete_files_for_library(library_key)

    def delete_all_file_links_for_library(self, library_id: str) -> None:
        return self._files.delete_all_file_links_for_library(library_id)

    def count_files_by_tag(self, tag_key: str, target_value: str) -> int:
        return self._files.count_files_by_tag(tag_key, target_value)

    def get_artist_album_frequencies(self, limit: int) -> dict[str, list[tuple[str, int]]]:
        return self._files.get_artist_album_frequencies(limit)

    def get_tracks_for_matching(self, library_id: str, *, limit: int | None) -> list[dict]:
        return self._files.get_tracks_for_matching(library_id, limit=limit)

    def search_files_by_tag(self, tag_key: str, value: str, *, limit: int | None) -> list[dict]:
        return self._tags.search_files_by_tag(tag_key, value, limit=limit)

    def add_tag(self, file_id: str, payload: dict) -> str:
        return self._tags.add_tag(file_id, payload)

    def get_tag(self, tag_id: str) -> dict | None:
        return self._tags.get_tag(tag_id)

    def find_or_create_tag(self, name: str, value: Any) -> str:
        return self._tags.find_or_create_tag(name, value)

    def upsert_tag(self, file_id: str, tag_key: str, payload: dict) -> None:
        return self._tags.upsert_tag(file_id, tag_key, payload)

    def get_tags_for_file(self, file_id: str) -> list[dict]:
        return self._tags.get_tags_for_file(file_id)

    def get_tags_for_files_batch(
        self,
        file_ids: list[str],
        *,
        name_starts_with: str | None = None,
        include_edge: bool = False,
    ) -> list[dict]:
        return self._tags.get_tags_for_files_batch(
            file_ids,
            name_starts_with=name_starts_with,
            include_edge=include_edge,
        )

    def list_all_tag_names(self, limit: int) -> list[str]:
        return self._tags.list_all_tag_names(limit)

    def get_tags_by_name(self, name: str, limit: int) -> list[dict]:
        return self._tags.get_tags_by_name(name, limit)

    def get_genre_tags_for_files(self, file_ids: list[str]) -> list[dict]:
        return self._tags.get_genre_tags_for_files(file_ids)

    def list_tags(
        self,
        *,
        name: str | None = None,
        value: Any = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict]:
        return self._tags.list_tags(name=name, value=value, limit=limit, offset=offset)

    def count_tags(self) -> int:
        return self._tags.count_tags()

    def aggregate_tag_field(self, field: str, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        return self._tags.aggregate_tag_field(field, limit=limit, offset=offset)

    def get_song_tag_edges_for_tags(self, tag_ids: list[str], *, limit: int | None = None) -> list[dict]:
        return self._tags.get_song_tag_edges_for_tags(tag_ids, limit=limit)

    def insert_song_tag_edges(self, docs: list[dict]) -> None:
        return self._tags.insert_song_tag_edges(docs)

    def delete_song_tag_edge_by_id(self, edge_id: str) -> None:
        return self._tags.delete_song_tag_edge_by_id(edge_id)

    def delete_tag(self, file_id: str, tag_key: str) -> None:
        return self._tags.delete_tag(file_id, tag_key)

    def delete_all_tags_for_file(self, file_id: str) -> None:
        return self._tags.delete_all_tags_for_file(file_id)

    def upsert_song_tag_edge(self, song_id: str, tag_id: str) -> None:
        return self._tags.upsert_song_tag_edge(song_id, tag_id)

    def delete_song_tag_edges_for_file(self, file_id: str) -> None:
        return self._tags.delete_song_tag_edges_for_file(file_id)

    def count_song_tag_edges(self, tag_id: str) -> int:
        return self._tags.count_song_tag_edges(tag_id)

    def count_song_tag_edges_for_file_state(self, file_id: str, state_tag_id: str) -> int:
        return self._tags.count_song_tag_edges_for_file_state(file_id, state_tag_id)

    def link_file_to_library(self, library_id: str, file_id: str) -> None:
        return self._files.link_file_to_library(library_id, file_id)

    def upsert_file_links_batch(self, links: list[dict]) -> None:
        return self._files.upsert_file_links_batch(links)

    def upsert_library_file_links_batch(self, links: list[dict]) -> None:
        return self._files.upsert_library_file_links_batch(links)

    def add_folder(self, payload: dict) -> str:
        return self._files.add_folder(payload)

    def link_folder_to_library(self, library_id: str, folder_id: str) -> None:
        return self._files.link_folder_to_library(library_id, folder_id)

    def get_folder(self, folder_id: str) -> dict | None:
        return self._files.get_folder(folder_id)

    def list_folders_for_library(self, library_id: str) -> list[dict]:
        return self._files.list_folders_for_library(library_id)

    def delete_folder(self, folder_id: str) -> None:
        return self._files.delete_folder(folder_id)

    def delete_folder_link(self, library_id: str, folder_id: str) -> None:
        return self._files.delete_folder_link(library_id, folder_id)

    def delete_folders_for_library(self, library_key: str) -> int:
        return self._files.delete_folders_for_library(library_key)

    def delete_all_folder_links_for_library(self, library_id: str) -> None:
        return self._files.delete_all_folder_links_for_library(library_id)

    def truncate_files(self) -> None:
        return self._files.truncate_files()

    def truncate_file_links(self) -> None:
        return self._files.truncate_file_links()

    def truncate_folder_links(self) -> None:
        return self._files.truncate_folder_links()

    def truncate_folders(self) -> None:
        return self._files.truncate_folders()

    def get_orphaned_tag_ids(self) -> list[str]:
        return self._tags.get_orphaned_tag_ids()

    def delete_tags_by_ids(self, tag_ids: list[str]) -> int:
        return self._tags.delete_tags_by_ids(tag_ids)

    def truncate_tags(self) -> None:
        return self._tags.truncate_tags()

    def truncate_song_tag_edges(self) -> None:
        return self._tags.truncate_song_tag_edges()
