"""Persistence facade tests for the domain folder + library-scoped song surface.

These use repository doubles (``MagicMock``) — no real database — and prove the
hard domain boundary (ADR-032/041/043) for ``LibrarySongsDb``:

- folder intents accept a ``Library`` natural key and a ``LibraryFolder`` value;
  folder row ids / ``parent_id`` / ``library_id`` never cross the facade;
- ``parent_path`` is resolved to a storage ``parent_id`` *internally*;
- folder replacement (``replace_library_folders``) is path-stable so songs keep
  their folder linkage;
- library-scoped song methods accept a ``Library`` and resolve its storage id
  internally, returning domain ``Song`` values (no song/library ids leak).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.library_domain_dataclasses import LibraryFolder
from nomarr.helpers.dto.repo_dto import LibraryFolderRow, LibraryRow, SongRow
from nomarr.persistence.api.library_songs import LibrarySongsDb


def _library_row(**overrides: object) -> LibraryRow:
    base = {
        "id": 7,
        "name": "main",
        "path": "/music",
        "library_type": "music",
        "auto_tag": 0,
        "auto_curate": 0,
        "watch_mode": "off",
        "file_write_mode": "full",
        "created_at": 100,
        "updated_at": 200,
    }
    return LibraryRow(**{**base, **overrides})


def _folder_row(**overrides: object) -> LibraryFolderRow:
    base = {
        "id": 41,
        "library_id": 7,
        "parent_id": None,
        "path": "Album",
        "name": "Album",
        "mtime": 5000,
        "file_count": 3,
        "last_scanned_at": 6000,
    }
    return LibraryFolderRow(**{**base, **overrides})


def _song_row(**overrides: object) -> SongRow:
    base = {
        "id": 11,
        "library_id": 7,
        "folder_id": 41,
        "path": "Album/track.mp3",
        "normalized_path": "album/track.mp3",
        "file_size": 1024,
        "modified_time": 5000,
        "duration_seconds": 200.0,
        "chromaprint": None,
        "needs_tagging": True,
        "is_valid": True,
        "tagged": False,
        "calibration_hash": None,
        "write_claimed_by": None,
        "last_tagged_at": None,
        "scanned_at": 6000,
        "created_at": 7000,
    }
    return SongRow(**{**base, **overrides})


def _make_songs(
    *,
    song_repo: MagicMock | None = None,
    folder_repo: MagicMock | None = None,
    library_repo: MagicMock | None = None,
) -> tuple[LibrarySongsDb, MagicMock, MagicMock, MagicMock]:
    song_repo = song_repo or MagicMock()
    folder_repo = folder_repo or MagicMock()
    library_repo = library_repo or MagicMock()
    songs = LibrarySongsDb(
        session=MagicMock(),
        song_repo=song_repo,
        folder_repo=folder_repo,
        song_state_repo=MagicMock(),
        song_hydration_repo=MagicMock(),
        library_repo=library_repo,
    )
    return songs, song_repo, folder_repo, library_repo


def _main_library() -> Library:
    return Library(
        name="main",
        root_path="/music",
        is_enabled=True,
        watch_mode="off",
        file_write_mode="full",
        library_auto_write=False,
        created_at=100,
        updated_at=200,
    )


def _folder(**overrides: object) -> LibraryFolder:
    base = {
        "path": "Album",
        "name": "Album",
        "parent_path": None,
        "mtime": 5000,
        "file_count": 3,
        "last_scanned_at": 6000,
    }
    return LibraryFolder(**{**base, **overrides})


# ── folder reads (row → domain, no id leaks) ───────────────────────────────


@pytest.mark.unit
def test_get_folder_uses_library_relative_natural_identity() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_by_path = MagicMock(return_value=_folder())

    result = songs.get_folder(_main_library(), "Album")

    assert result == _folder()
    folder_repo.get_folder_by_path.assert_called_once_with(7, "Album")


@pytest.mark.unit
def test_list_folders_forwards_domain_values_without_ids() -> None:
    # ``FolderRepository.list_folders_for_library`` performs the row→domain
    # mapping (P3-S2); the facade forwards domain ``LibraryFolder`` values
    # unchanged and resolves the natural key. Raw ``LibraryFolderRow`` values
    # never reach the caller.
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.list_folders_for_library = MagicMock(return_value=[_folder()])

    result = songs.list_folders_for_library(_main_library())

    assert len(result) == 1
    folder = result[0]
    assert isinstance(folder, LibraryFolder)
    assert folder.path == "Album"
    assert folder.name == "Album"
    assert folder.mtime == 5000
    assert folder.file_count == 3
    assert folder.last_scanned_at == 6000
    # storage ids never cross the boundary
    assert not hasattr(folder, "id")
    assert not hasattr(folder, "parent_id")
    assert not hasattr(folder, "library_id")
    library_repo.get_library_by_natural_key.assert_called_once_with("main", "/music")
    folder_repo.list_folders_for_library.assert_called_once_with(7)


# ── folder writes (domain → storage payload, FK resolved internally) ───────


@pytest.mark.unit
def test_add_library_folder_builds_payload_and_returns_domain() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_by_path = MagicMock(return_value=_folder())

    result = songs.add_library_folder(_main_library(), _folder())

    payload = folder_repo.add_library_folder.call_args[0][1]
    assert payload == {
        "path": "Album",
        "name": "Album",
        "parent_id": None,
        "mtime": 5000,
        "file_count": 3,
        "last_scanned_at": 6000,
    }
    folder_repo.add_library_folder.assert_called_once_with(7, payload)
    assert isinstance(result, LibraryFolder)
    assert result.path == "Album"


@pytest.mark.unit
def test_add_library_folder_resolves_parent_path_to_parent_id_internally() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=55)

    songs.add_library_folder(_main_library(), _folder(parent_path="Boxset"))

    folder_repo.get_folder_id_by_path.assert_called_once_with(7, "Boxset")
    payload = folder_repo.add_library_folder.call_args[0][1]
    assert payload["parent_id"] == 55


@pytest.mark.unit
def test_replace_library_folder_resolves_path_and_updates() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=41)
    folder_repo.get_folder_by_path = MagicMock(return_value=_folder(name="Album V2"))

    result = songs.replace_library_folder(_main_library(), "Album", _folder(name="Album V2"))

    folder_repo.replace_library_folder.assert_called_once()
    args = folder_repo.replace_library_folder.call_args[0]
    assert args[0] == 7
    assert args[1] == 41  # resolved from folder_path internally
    assert args[2]["name"] == "Album V2"
    assert isinstance(result, LibraryFolder)


@pytest.mark.unit
def test_replace_library_folder_rejects_path_mismatch() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())

    with pytest.raises(ValueError, match=r"folder_path must match folder\.path"):
        songs.replace_library_folder(_main_library(), "Missing", _folder())

    folder_repo.get_folder_id_by_path.assert_not_called()


@pytest.mark.unit
def test_replace_library_folder_raises_when_path_missing() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=None)

    with pytest.raises(LookupError):
        songs.replace_library_folder(_main_library(), "Missing", _folder(path="Missing"))


@pytest.mark.unit
def test_remove_library_folder_resolves_path() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=41)

    songs.remove_library_folder(_main_library(), "Album")

    folder_repo.get_folder_id_by_path.assert_called_once_with(7, "Album")
    folder_repo.remove_library_folder.assert_called_once_with(7, 41)


@pytest.mark.unit
def test_remove_library_folder_is_noop_when_missing() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=None)

    songs.remove_library_folder(_main_library(), "Missing")

    folder_repo.remove_library_folder.assert_not_called()


@pytest.mark.unit
def test_replace_library_folders_is_path_stable() -> None:
    songs, _, folder_repo, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    folder_repo.get_folder_id_by_path = MagicMock(return_value=55)

    songs.replace_library_folders(
        _main_library(),
        [_folder(path="Album"), _folder(path="Boxset", parent_path="Album")],
    )

    folder_repo.replace_library_folders.assert_called_once()
    args = folder_repo.replace_library_folders.call_args[0]
    assert args[0] == 7
    payloads = args[1]
    assert [p["path"] for p in payloads] == ["Album", "Boxset"]
    # path-keyed payloads let the repo reconcile in place, preserving row ids
    # so song → folder linkage survives (repos preserve ids across replacement).
    assert payloads[0]["parent_id"] is None
    assert payloads[1]["parent_id"] == 55


# ── library-scoped song reads (Library key → domain Song) ──────────────────


@pytest.mark.unit
def test_list_songs_resolves_library_and_returns_domain_songs() -> None:
    songs, song_repo, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    song_repo.list_songs = MagicMock(return_value=[_song_row()])

    result = songs.list_songs(_main_library(), limit=100)

    song_repo.list_songs.assert_called_once_with(7, limit=100)
    assert len(result) == 1
    assert result[0].path == "Album/track.mp3"
    assert result[0].song_id == 11
    library_repo.get_library_by_natural_key.assert_called_once_with("main", "/music")


@pytest.mark.unit
def test_list_songs_for_folder_resolves_library_and_maps() -> None:
    songs, song_repo, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    song_repo.list_songs_for_folder = MagicMock(return_value=[_song_row()])

    result = songs.list_songs_for_folder(_main_library(), "Album")

    song_repo.list_songs_for_folder.assert_called_once_with(7, "Album")
    assert result[0].path == "Album/track.mp3"


@pytest.mark.unit
def test_count_songs_for_library_resolves_library() -> None:
    songs, song_repo, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    song_repo.count_songs = MagicMock(return_value=5)

    assert songs.count_songs_for_library(_main_library()) == 5
    song_repo.count_songs.assert_called_once_with(7)


@pytest.mark.unit
def test_find_library_song_by_chromaprint_resolves_and_maps() -> None:
    songs, song_repo, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    song_repo.find_song_by_chromaprint = MagicMock(return_value=_song_row(chromaprint="abc"))

    result = songs.find_library_song_by_chromaprint(_main_library(), "abc")

    song_repo.find_song_by_chromaprint.assert_called_once_with(7, "abc")
    assert result is not None
    assert result.chromaprint == "abc"


@pytest.mark.unit
def test_list_existing_song_paths_resolves_library() -> None:
    songs, song_repo, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=_library_row())
    song_repo.list_existing_song_paths = MagicMock(return_value=["Album/track.mp3"])

    result = songs.list_existing_song_paths(_main_library(), ["Album/track.mp3"])

    song_repo.list_existing_song_paths.assert_called_once_with(7, ["Album/track.mp3"])
    assert result == ["Album/track.mp3"]


@pytest.mark.unit
def test_library_scoped_song_raises_when_library_unknown() -> None:
    songs, _, _, library_repo = _make_songs()
    library_repo.get_library_by_natural_key = MagicMock(return_value=None)

    with pytest.raises(LookupError):
        songs.list_songs(_main_library())
