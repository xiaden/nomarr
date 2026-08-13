"""Unit tests for TagRepository and SongTagRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: create a library and a song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name="Tag Lib",
            path="/tag/lib",
            library_type="music",
            auto_tag=0,
            auto_curate=0,
            created_at=1000,
            updated_at=1000,
        )
    )
    lib_id = lib_r.inserted_primary_key[0]
    song_r = session.execute(
        insert(Song).values(
            library_id=lib_id,
            path="/tag/lib/test.mp3",
            normalized_path="/tag/lib/test.mp3",
            file_size=1000,
            modified_time=1000,
            duration_seconds=180,
            needs_tagging=0,
            is_valid=1,
            tagged=0,
            created_at=1000,
        )
    )
    song_id = song_r.inserted_primary_key[0]
    return lib_id, song_id


def _create_tag(session, name: str = "rock", value: str = "rock", namespace: str = "genre") -> int:
    """Helper: create a tag and return its id."""
    r = session.execute(
        insert(Tag).values(
            name=name,
            value=value,
            namespace=namespace,
            source="ml",
            confidence=0.95,
            tier=1,
            created_at=1000,
        )
    )
    return r.inserted_primary_key[0]


@pytest.mark.unit
@pytest.mark.integration
class TestTagRepository:
    """Tests for TagRepository CRUD and query methods."""

    # ── core CRUD ───────────────────────────────────────────────

    def test_get_tag_existing(self, pg_session) -> None:
        """get_tag should return the tag as a dict."""
        tag_id = _create_tag(pg_session)
        repo = TagRepository(pg_session)
        result = repo.get_tag(tag_id)
        assert result is not None
        assert result["id"] == tag_id
        assert result["name"] == "rock"
        assert result["namespace"] == "genre"

    def test_get_tag_nonexistent(self, pg_session) -> None:
        """get_tag should return None for missing id."""
        repo = TagRepository(pg_session)
        result = repo.get_tag(999999)
        assert result is None

    def test_get_tag_by_name(self, pg_session) -> None:
        """get_tag_by_name should find tag by name and namespace."""
        tag_id = _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.get_tag_by_name("pop", "genre")
        assert result is not None
        assert result["id"] == tag_id
        assert result["name"] == "pop"

    def test_get_tag_by_name_nonexistent(self, pg_session) -> None:
        """get_tag_by_name should return None for missing tag."""
        repo = TagRepository(pg_session)
        result = repo.get_tag_by_name("nonexistent", "genre")
        assert result is None

    def test_get_or_create_tag_existing(self, pg_session) -> None:
        """get_or_create_tag should return existing tag id."""
        tag_id = _create_tag(pg_session, name="jazz", value="jazz", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.get_or_create_tag("jazz", "jazz", "genre")
        assert result == tag_id

    def test_get_or_create_tag_new(self, pg_session) -> None:
        """get_or_create_tag should create and return new tag id."""
        repo = TagRepository(pg_session)
        result = repo.get_or_create_tag("blues", "blues", "genre")
        assert isinstance(result, int)
        assert result > 0
        # Verify it exists
        tag = repo.get_tag(result)
        assert tag is not None
        assert tag["name"] == "blues"

    def test_create_tag(self, pg_session) -> None:
        """create_tag should insert and return id."""
        repo = TagRepository(pg_session)
        tag_id = repo.create_tag(
            {
                "name": "electronic",
                "value": "electronic",
                "namespace": "genre",
                "source": "ml",
                "confidence": 0.9,
                "tier": 1,
                "created_at": 2000,
            }
        )
        assert isinstance(tag_id, int)
        assert tag_id > 0

    def test_delete_tag(self, pg_session) -> None:
        """delete_tag should remove the row."""
        tag_id = _create_tag(pg_session)
        repo = TagRepository(pg_session)
        repo.delete_tag(tag_id)
        result = repo.get_tag(tag_id)
        assert result is None

    # ── song-tag associations ───────────────────────────────────

    def test_get_tags_for_song(self, pg_session) -> None:
        """get_tags_for_song should return tags assigned to a song."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id1 = _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        tag_id2 = _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id1, confidence=0.9)
        song_tag_repo.assign_tag_to_song(song_id, tag_id2, confidence=0.8)
        result = song_tag_repo.get_tags_for_song(song_id)
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert "rock" in names
        assert "pop" in names

    def test_assign_tag_to_song(self, pg_session) -> None:
        """assign_tag_to_song should create a song-tag association."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id, confidence=0.95, source="ml")
        tags = song_tag_repo.get_tags_for_song(song_id)
        assert len(tags) == 1
        assert tags[0]["id"] == tag_id

    def test_remove_tag_from_song(self, pg_session) -> None:
        """remove_tag_from_song should delete the association."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        song_tag_repo.remove_tag_from_song(song_id, tag_id)
        tags = song_tag_repo.get_tags_for_song(song_id)
        assert len(tags) == 0

    def test_replace_song_tags(self, pg_session) -> None:
        """replace_song_tags should delete old and insert new assignments."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id1 = _create_tag(pg_session, name="old1", value="old1", namespace="genre")
        tag_id2 = _create_tag(pg_session, name="old2", value="old2", namespace="genre")
        tag_id3 = _create_tag(pg_session, name="new1", value="new1", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id1)
        song_tag_repo.assign_tag_to_song(song_id, tag_id2)
        song_tag_repo.replace_song_tags(
            song_id,
            [
                {"tag_id": tag_id3, "confidence": 0.9, "source": "ml"},
            ],
        )
        tags = song_tag_repo.get_tags_for_song(song_id)
        assert len(tags) == 1
        assert tags[0]["name"] == "new1"

    def test_get_songs_for_tag(self, pg_session) -> None:
        """get_songs_for_tag should return songs assigned to a tag."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)
        result = song_tag_repo.get_songs_for_tag(tag_id)
        assert len(result) == 2
        ids = {s["id"] for s in result}
        assert song_id1 in ids
        assert song_id2 in ids

    def test_list_song_ids_for_tag(self, pg_session) -> None:
        """list_song_ids_for_tag should return song ids with pagination."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)
        result = song_tag_repo.list_song_ids_for_tag(tag_id, limit=1, offset=0)
        assert len(result) == 1
        assert result[0] in (song_id1, song_id2)

    def test_count_songs_for_tag(self, pg_session) -> None:
        """count_songs_for_tag should count song-tag assignments for a tag."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)
        result = song_tag_repo.count_songs_for_tag(tag_id)
        assert result == 2

    def test_count_songs_for_tag_zero(self, pg_session) -> None:
        """count_songs_for_tag should return 0 for a tag with no assignments."""
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        result = song_tag_repo.count_songs_for_tag(tag_id)
        assert result == 0

    def test_count_songs_by_tag(self, pg_session) -> None:
        """count_songs_by_tag should count distinct songs for matching tags."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)
        result = song_tag_repo.count_songs_by_tag("genre", "rock")
        assert result == 2

    def test_count_songs_by_tag_non_matching_value(self, pg_session) -> None:
        """count_songs_by_tag should return 0 when value does not match."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = song_tag_repo.count_songs_by_tag("genre", "pop")
        assert result == 0

    def test_get_song_tag_edges_for_tags(self, pg_session) -> None:
        """get_song_tag_edges_for_tags should return edge dicts with expected keys."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id, confidence=0.9, source="ml")
        result = song_tag_repo.get_song_tag_edges_for_tags([tag_id])
        assert len(result) == 1
        edge = result[0]
        assert edge["song_id"] == song_id
        assert edge["tag_id"] == tag_id
        assert edge["confidence"] == 0.9
        assert edge["source"] == "ml"

    def test_get_song_tag_edges_for_tags_empty(self, pg_session) -> None:
        """get_song_tag_edges_for_tags should return [] for empty tag_ids."""
        song_tag_repo = SongTagRepository(pg_session)
        result = song_tag_repo.get_song_tag_edges_for_tags([])
        assert result == []

    def test_get_song_tag_edges_for_tags_limit(self, pg_session) -> None:
        """get_song_tag_edges_for_tags should respect the limit parameter."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)
        result = song_tag_repo.get_song_tag_edges_for_tags([tag_id], limit=1)
        assert len(result) == 1

    # ── orphan management ───────────────────────────────────────

    def test_get_orphaned_tag_ids(self, pg_session) -> None:
        """get_orphaned_tag_ids should return tags with no song assignments."""
        tag_id1 = _create_tag(pg_session, name="orphan1", value="orphan1", namespace="genre")
        tag_id2 = _create_tag(pg_session, name="orphan2", value="orphan2", namespace="genre")
        _, song_id = _create_library_and_song(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id1)
        result = tag_repo.get_orphaned_tag_ids()
        assert tag_id2 in result
        assert tag_id1 not in result

    def test_cleanup_orphaned_tags(self, pg_session) -> None:
        """cleanup_orphaned_tags should delete tags with no assignments."""
        tag_id1 = _create_tag(pg_session, name="keep", value="keep", namespace="genre")
        tag_id2 = _create_tag(pg_session, name="delete", value="delete", namespace="genre")
        _, song_id = _create_library_and_song(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id1)
        deleted = tag_repo.cleanup_orphaned_tags()
        assert deleted == 1
        assert tag_repo.get_tag(tag_id1) is not None
        assert tag_repo.get_tag(tag_id2) is None

    # ── tag listing ─────────────────────────────────────────────

    def test_list_tags(self, pg_session) -> None:
        """list_tags should return all tags with optional filters."""
        _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.list_tags()
        assert len(result) >= 2
        names = {t["name"] for t in result}
        assert "rock" in names
        assert "pop" in names

    def test_list_tags_with_name_filter(self, pg_session) -> None:
        """list_tags should filter by name."""
        _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.list_tags(name="rock")
        assert len(result) == 1
        assert result[0]["name"] == "rock"

    def test_count_tags(self, pg_session) -> None:
        """count_tags should return total tag count."""
        _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.count_tags()
        assert result >= 2

    def test_get_tags_for_songs_batch(self, pg_session) -> None:
        """get_tags_for_songs_batch should return tag assignments for multiple songs."""
        _, song_id1 = _create_library_and_song(pg_session)
        _, song_id2 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id, confidence=0.9)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id, confidence=0.8)
        result = song_tag_repo.get_tags_for_songs_batch([song_id1, song_id2])
        assert len(result) == 2
        assert all(r["tag_id"] == tag_id for r in result)

    def test_get_song_tags(self, pg_session) -> None:
        """get_song_tags should return tags for a song."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = song_tag_repo.get_song_tags(song_id)
        assert len(result) == 1
        assert result[0]["id"] == tag_id

    # ── search ──────────────────────────────────────────────────

    def test_search_songs_by_tag(self, pg_session) -> None:
        """search_songs_by_tag should find songs with exact tag match."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = song_tag_repo.search_songs_by_tag("genre", "rock")
        assert len(result) == 1
        assert result[0]["id"] == song_id

    def test_search_songs_by_tag_contains(self, pg_session) -> None:
        """search_songs_by_tag_contains should find songs with partial tag match."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="progressive rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = song_tag_repo.search_songs_by_tag_contains("genre", "rock")
        assert len(result) == 1
        assert result[0]["id"] == song_id

    def test_get_tag_value_frequencies(self, pg_session) -> None:
        """get_tag_value_frequencies should return value counts."""
        # Create tags with same name and value but different namespaces
        _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        _create_tag(pg_session, name="genre", value="rock", namespace="mood")
        _create_tag(pg_session, name="genre", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.get_tag_value_frequencies("genre", limit=10)
        assert len(result) == 2
        # rock should appear twice (different namespaces)
        rock_count = next((c for v, c in result if v == "rock"), 0)
        assert rock_count == 2
        pop_count = next((c for v, c in result if v == "pop"), 0)
        assert pop_count == 1

    def test_replace_tag_references(self, pg_session) -> None:
        """replace_tag_references should re-point assignments."""
        _, song_id = _create_library_and_song(pg_session)
        source_id = _create_tag(pg_session, name="old", value="old", namespace="genre")
        target_id = _create_tag(pg_session, name="new", value="new", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        TagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, source_id)
        song_tag_repo.replace_tag_references(source_id, target_id)
        tags = song_tag_repo.get_tags_for_song(song_id)
        assert len(tags) == 1
        assert tags[0]["id"] == target_id

    # ── Plan E facade support ───────────────────────────────────

    def test_list_all_tag_names(self, pg_session) -> None:
        """list_all_tag_names should return distinct names."""
        _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.list_all_tag_names()
        assert "rock" in result
        assert "pop" in result

    def test_count_tags_filtered(self, pg_session) -> None:
        """count_tags_filtered should count with filters."""
        _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.count_tags_filtered(name="rock")
        assert result == 1

    def test_list_tags_with_song_count(self, pg_session) -> None:
        """list_tags_with_song_count should include assignment counts."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = tag_repo.list_tags_with_song_count()
        assert len(result) >= 1
        rock_tag = next((t for t in result if t["name"] == "rock"), None)
        assert rock_tag is not None
        assert rock_tag["song_count"] == 1

    def test_get_genre_tags_for_songs(self, pg_session) -> None:
        """get_genre_tags_for_songs should return genre tags for songs."""
        _, song_id = _create_library_and_song(pg_session)
        genre_id = _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        other_id = _create_tag(pg_session, name="mood", value="happy", namespace="mood")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, genre_id)
        song_tag_repo.assign_tag_to_song(song_id, other_id)
        result = song_tag_repo.get_genre_tags_for_songs([song_id])
        assert len(result) == 1
        assert result[0]["name"] == "genre"

    def test_search_songs_by_tag_pattern(self, pg_session) -> None:
        """search_songs_by_tag_pattern should match ILIKE pattern."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="progressive rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        result = song_tag_repo.search_songs_by_tag_pattern("genre", "%rock%")
        assert len(result) == 1
        assert result[0]["id"] == song_id

    # ── maintenance ─────────────────────────────────────────────

    def test_truncate_song_tag_assignments(self, pg_session) -> None:
        """truncate_song_tag_assignments should remove all song_tags."""
        _, song_id = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id)
        song_tag_repo.truncate_song_tag_assignments()
        from sqlalchemy import select

        result = pg_session.execute(select(SongTag))
        assert len(result.all()) == 0

    def test_truncate_tags(self, pg_session) -> None:
        """truncate_tags should remove all tags."""
        _create_tag(pg_session)
        repo = TagRepository(pg_session)
        repo.truncate_tags()
        from sqlalchemy import select

        result = pg_session.execute(select(Tag))
        assert len(result.all()) == 0
