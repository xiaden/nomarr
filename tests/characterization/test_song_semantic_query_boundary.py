"""Real (non-mocked) semantic boundary coverage for the Q3-G service/query cut.

The migrated semantic read path was previously covered only through facade
mocks. These tests exercise it end-to-end against the real PostgreSQL
characterization database:

- ``LibraryService.get_song_tags(SongIdentity, nomarr_only=False)`` returns a
  typed ``FileTagsResult`` whose ``file_id`` is the opaque ``nom1`` locator of
  the same ``SongIdentity`` and whose tags match the seeded assignments.
- ``LibraryService.get_files_by_ids(list[SongIdentity])`` projects real
  persistence carriers back to the opaque locators of the inputs (no integer
  handle crosses the boundary).

Marked ``characterization`` + ``requires_database``; runs in the CI
database-tests job. A native pgvector PostgreSQL cluster was reachable in the
authoring workspace at ``127.0.0.1:5432`` (credentials from
``NOMARR_TEST_DATABASE_URL`` / ``PGPASSWORD``), so the local tier is
``LOCAL_PASS`` against native PostgreSQL; the testcontainer tier remains
``CI_DEFERRED`` and no ``CI_PASS`` is claimed.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dto.library_dto import FileTagsResult, SearchFilesResult
from nomarr.helpers.song_locator_codec import encode_song_locator
from nomarr.services.domain.library_svc import LibraryService
from nomarr.services.domain.library_svc.config import LibraryServiceConfig


def _service(db) -> LibraryService:
    cfg = LibraryServiceConfig(
        models_dir="/tmp/models",
        namespace="nom",
        tagger_version="test-v1",
    )
    return LibraryService(cfg=cfg, db=db)


@pytest.mark.characterization
@pytest.mark.requires_database
class TestSongSemanticQueryBoundary:
    """Q3-G semantic read boundary against real persistence (no mocks)."""

    def test_get_song_tags_returns_opaque_locator_for_identity(self, db, seed_data):
        """The typed result carries the opaque locator of the same identity."""
        song = seed_data["song_identities"][0]
        result = _service(db).get_song_tags(song, nomarr_only=False)

        assert isinstance(result, FileTagsResult)
        assert result.file_id == encode_song_locator(song)
        assert result.file_id.startswith("nom1")
        assert not result.file_id.isdigit()
        # The real stored DB path for the seeded song, not a re-encoded input.
        assert result.path == "/tmp/test1/song1.flac"
        assert {tag.key: tag.value for tag in result.tags} == {
            "nom:mood-strict": "happy",
            "nom:genre": "rock",
        }

    def test_get_song_tags_cross_library_identity(self, db, seed_data):
        """A song in a different library resolves against the real read path.

        ``song_identities[2]`` lives in library 2 and has no seeded tag
        assignments, so only the typed contract and identity/round-trip
        consistency are asserted; an empty tag list is legitimate here.
        """
        song = seed_data["song_identities"][2]
        result = _service(db).get_song_tags(song, nomarr_only=False)

        assert isinstance(result, FileTagsResult)
        assert result.file_id == encode_song_locator(song)
        assert result.file_id.startswith("nom1")
        assert not result.file_id.isdigit()
        # The real stored DB path for the library-2 seeded song.
        assert result.path == "/tmp/test2/song3.flac"
        # No seeded tags on this song: the typed contract still holds.
        assert result.tags == []

    def test_get_files_by_ids_round_trips_semantic_locators(self, db, seed_data):
        """Query carriers project back to the opaque locators of the inputs."""
        songs = list(seed_data["song_identities"][:2])
        result = _service(db).get_files_by_ids(songs)

        assert isinstance(result, SearchFilesResult)
        assert result.total == 2
        assert {song.file_id for song in result.songs} == {encode_song_locator(s) for s in songs}
