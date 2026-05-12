# mypy: disable-error-code=func-returns-value
"""Unit tests for ``LibraryDb`` delegation."""

from __future__ import annotations

from unittest.mock import MagicMock, sentinel

import pytest

from nomarr.persistence.api.library import LibraryDb


def _make_library_db() -> tuple[LibraryDb, MagicMock, MagicMock, MagicMock, MagicMock]:
    libraries = MagicMock()
    files = MagicMock()
    tags = MagicMock()
    scan = MagicMock()
    db = LibraryDb(libraries=libraries, files=files, tags=tags, scan=scan)
    return db, libraries, files, tags, scan


@pytest.mark.unit
def test_add_library_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    payload = {"name": "Library"}
    libraries.add_library.return_value = sentinel.result

    result = db.add_library(payload)

    assert result is sentinel.result
    libraries.add_library.assert_called_once_with(payload)


@pytest.mark.unit
def test_get_library_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    libraries.get_library.return_value = sentinel.result

    result = db.get_library("libraries/1")

    assert result is sentinel.result
    libraries.get_library.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_get_library_by_name_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    libraries.get_library_by_name.return_value = sentinel.result

    result = db.get_library_by_name("Main")

    assert result is sentinel.result
    libraries.get_library_by_name.assert_called_once_with("Main")


@pytest.mark.unit
def test_list_libraries_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    libraries.list_libraries.return_value = sentinel.result

    result = db.list_libraries(enabled_only=True)

    assert result is sentinel.result
    libraries.list_libraries.assert_called_once_with(enabled_only=True)


@pytest.mark.unit
def test_list_library_keys_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    libraries.list_library_keys.return_value = sentinel.result

    result = db.list_library_keys()

    assert result is sentinel.result
    libraries.list_library_keys.assert_called_once_with()


@pytest.mark.unit
def test_update_library_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    fields = {"enabled": False}
    libraries.update_library.return_value = sentinel.result

    result = db.update_library("libraries/1", fields)

    assert result is sentinel.result
    libraries.update_library.assert_called_once_with("libraries/1", fields)


@pytest.mark.unit
def test_delete_library_delegates_to_libraries() -> None:
    db, libraries, _, _, _ = _make_library_db()
    libraries.delete_library.return_value = sentinel.result

    result = db.delete_library("libraries/1")

    assert result is sentinel.result
    libraries.delete_library.assert_called_once_with("libraries/1")


@pytest.mark.unit
def test_add_file_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    payload = {"path": "C:/music/track.flac"}
    files.add_file.return_value = sentinel.result

    result = db.add_file(payload)

    assert result is sentinel.result
    files.add_file.assert_called_once_with(payload)


@pytest.mark.unit
def test_get_file_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.get_file.return_value = sentinel.result

    result = db.get_file("library_files/1")

    assert result is sentinel.result
    files.get_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_get_file_by_path_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.get_file_by_path.return_value = sentinel.result

    result = db.get_file_by_path("C:/music/track.flac", "libraries/1")

    assert result is sentinel.result
    files.get_file_by_path.assert_called_once_with("C:/music/track.flac", "libraries/1")


@pytest.mark.unit
def test_upsert_file_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    payload = {"_key": "file1"}
    files.upsert_file.return_value = sentinel.result

    result = db.upsert_file(payload)

    assert result is sentinel.result
    files.upsert_file.assert_called_once_with(payload)


@pytest.mark.unit
def test_upsert_files_batch_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    payloads = [{"_key": "file1"}, {"_key": "file2"}]
    files.upsert_files_batch.return_value = sentinel.result

    result = db.upsert_files_batch(payloads)

    assert result is sentinel.result
    files.upsert_files_batch.assert_called_once_with(payloads)


@pytest.mark.unit
def test_update_file_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    fields = {"duration": 123}
    files.update_file.return_value = sentinel.result

    result = db.update_file("library_files/1", fields)

    assert result is sentinel.result
    files.update_file.assert_called_once_with("library_files/1", fields)


@pytest.mark.unit
def test_delete_file_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.delete_file.return_value = sentinel.result

    result = db.delete_file("library_files/1")

    assert result is sentinel.result
    files.delete_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_list_files_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    filters = {"artist": "Artist"}
    files.list_files.return_value = sentinel.result

    result = db.list_files(filters=filters, limit=10)

    assert result is sentinel.result
    files.list_files.assert_called_once_with(filters=filters, limit=10)


@pytest.mark.unit
def test_count_files_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.count_files.return_value = sentinel.result

    result = db.count_files()

    assert result is sentinel.result
    files.count_files.assert_called_once_with()


@pytest.mark.unit
def test_get_files_by_ids_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    file_ids = ["library_files/1", "library_files/2"]
    files.get_files_by_ids.return_value = sentinel.result

    result = db.get_files_by_ids(file_ids)

    assert result is sentinel.result
    files.get_files_by_ids.assert_called_once_with(file_ids)


@pytest.mark.unit
def test_get_library_ids_for_files_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    file_ids = ["library_files/1"]
    files.get_library_ids_for_files.return_value = sentinel.result

    result = db.get_library_ids_for_files(file_ids)

    assert result is sentinel.result
    files.get_library_ids_for_files.assert_called_once_with(file_ids)


@pytest.mark.unit
def test_count_recently_tagged_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.count_recently_tagged.return_value = sentinel.result

    result = db.count_recently_tagged(123)

    assert result is sentinel.result
    files.count_recently_tagged.assert_called_once_with(123)


@pytest.mark.unit
def test_list_existing_file_paths_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    paths = ["C:/music/track.flac"]
    files.list_existing_file_paths.return_value = sentinel.result

    result = db.list_existing_file_paths(paths)

    assert result is sentinel.result
    files.list_existing_file_paths.assert_called_once_with(paths)


@pytest.mark.unit
def test_search_files_by_text_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.search_files_by_text.return_value = sentinel.result

    result = db.search_files_by_text("artist", "%beatles%", limit=5)

    assert result is sentinel.result
    files.search_files_by_text.assert_called_once_with("artist", "%beatles%", limit=5)


@pytest.mark.unit
def test_list_library_file_ids_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.list_library_file_ids.return_value = sentinel.result

    result = db.list_library_file_ids("libraries/1", limit=25)

    assert result is sentinel.result
    files.list_library_file_ids.assert_called_once_with("libraries/1", limit=25)


@pytest.mark.unit
def test_count_files_by_tag_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.count_files_by_tag.return_value = sentinel.result

    result = db.count_files_by_tag("genre", "rock")

    assert result is sentinel.result
    files.count_files_by_tag.assert_called_once_with("genre", "rock")


@pytest.mark.unit
def test_get_artist_album_frequencies_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.get_artist_album_frequencies.return_value = sentinel.result

    result = db.get_artist_album_frequencies(25)

    assert result is sentinel.result
    files.get_artist_album_frequencies.assert_called_once_with(25)


@pytest.mark.unit
def test_get_tracks_for_matching_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.get_tracks_for_matching.return_value = sentinel.result

    result = db.get_tracks_for_matching("libraries/1", limit=50)

    assert result is sentinel.result
    files.get_tracks_for_matching.assert_called_once_with("libraries/1", limit=50)


@pytest.mark.unit
def test_search_files_by_tag_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    tags.search_files_by_tag.return_value = sentinel.result

    result = db.search_files_by_tag("mood", "calm", limit=10)

    assert result is sentinel.result
    tags.search_files_by_tag.assert_called_once_with("mood", "calm", limit=10)


@pytest.mark.unit
def test_add_tag_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    payload = {"value": "rock"}
    tags.add_tag.return_value = sentinel.result

    result = db.add_tag("library_files/1", payload)

    assert result is sentinel.result
    tags.add_tag.assert_called_once_with("library_files/1", payload)


@pytest.mark.unit
def test_upsert_tag_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    payload = {"value": "rock"}
    tags.upsert_tag.return_value = sentinel.result

    result = db.upsert_tag("library_files/1", "genre", payload)

    assert result is sentinel.result
    tags.upsert_tag.assert_called_once_with("library_files/1", "genre", payload)


@pytest.mark.unit
def test_get_tags_for_file_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    tags.get_tags_for_file.return_value = sentinel.result

    result = db.get_tags_for_file("library_files/1")

    assert result is sentinel.result
    tags.get_tags_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_delete_tag_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    tags.delete_tag.return_value = sentinel.result

    result = db.delete_tag("library_files/1", "genre")

    assert result is sentinel.result
    tags.delete_tag.assert_called_once_with("library_files/1", "genre")


@pytest.mark.unit
def test_delete_all_tags_for_file_delegates_to_tags() -> None:
    db, _, _, tags, _ = _make_library_db()
    tags.delete_all_tags_for_file.return_value = sentinel.result

    result = db.delete_all_tags_for_file("library_files/1")

    assert result is sentinel.result
    tags.delete_all_tags_for_file.assert_called_once_with("library_files/1")


@pytest.mark.unit
def test_link_file_to_library_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.link_file_to_library.return_value = sentinel.result

    result = db.link_file_to_library("libraries/1", "library_files/1")

    assert result is sentinel.result
    files.link_file_to_library.assert_called_once_with("libraries/1", "library_files/1")


@pytest.mark.unit
def test_upsert_file_links_batch_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    links = [{"_from": "libraries/1", "_to": "library_files/1"}]
    files.upsert_file_links_batch.return_value = sentinel.result

    result = db.upsert_file_links_batch(links)

    assert result is sentinel.result
    files.upsert_file_links_batch.assert_called_once_with(links)


@pytest.mark.unit
def test_add_folder_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    payload = {"path": "C:/music"}
    files.add_folder.return_value = sentinel.result

    result = db.add_folder(payload)

    assert result is sentinel.result
    files.add_folder.assert_called_once_with(payload)


@pytest.mark.unit
def test_get_folder_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.get_folder.return_value = sentinel.result

    result = db.get_folder("library_folders/1")

    assert result is sentinel.result
    files.get_folder.assert_called_once_with("library_folders/1")


@pytest.mark.unit
def test_delete_folder_delegates_to_files() -> None:
    db, _, files, _, _ = _make_library_db()
    files.delete_folder.return_value = sentinel.result

    result = db.delete_folder("library_folders/1")

    assert result is sentinel.result
    files.delete_folder.assert_called_once_with("library_folders/1")
