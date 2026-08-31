"""Unit tests for TagRepository and SongTagRepository."""

from __future__ import annotations

from itertools import count

import pytest
from sqlalchemy import func, insert, select

from nomarr.persistence.database.song_tag_repo import SongTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.song import Song
from nomarr.persistence.models.song_tag import SongTag
from nomarr.persistence.models.tag import Tag

_LIBRARY_NAMES = count(1)


def _create_library_and_song(session) -> tuple[int, int]:
    """Helper: create a library and a song, return (library_id, song_id)."""
    lib_r = session.execute(
        insert(Library).values(
            name=f"Tag Lib {next(_LIBRARY_NAMES)}",
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
        _, song_id3 = _create_library_and_song(pg_session)
        tag_id = _create_tag(pg_session)
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id1, tag_id)
        song_tag_repo.assign_tag_to_song(song_id3, tag_id)
        song_tag_repo.assign_tag_to_song(song_id2, tag_id)

        first_page = song_tag_repo.list_song_ids_for_tag(tag_id, limit=1, offset=0)
        second_page = song_tag_repo.list_song_ids_for_tag(tag_id, limit=1, offset=1)
        third_page = song_tag_repo.list_song_ids_for_tag(tag_id, limit=1, offset=2)
        expected_ids = sorted((song_id1, song_id2, song_id3))
        assert first_page == expected_ids[:1]
        assert second_page == expected_ids[1:2]
        assert third_page == expected_ids[2:]

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

    def test_search_songs_by_tag_contains_escapes_like_wildcards(self, pg_session) -> None:
        """Literal percent and underscore characters should not act as wildcards."""
        _, matching_song_id = _create_library_and_song(pg_session)
        _, wildcard_song_id = _create_library_and_song(pg_session)
        _, underscore_match_id = _create_library_and_song(pg_session)
        _, underscore_wildcard_id = _create_library_and_song(pg_session)
        matching_tag_id = _create_tag(pg_session, name="genre", value="100% rock", namespace="genre")
        wildcard_tag_id = _create_tag(pg_session, name="genre", value="1000 rock", namespace="genre")
        underscore_match_tag_id = _create_tag(pg_session, name="genre", value="100_ rock", namespace="genre")
        underscore_wildcard_tag_id = _create_tag(pg_session, name="genre", value="1001 rock", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(matching_song_id, matching_tag_id)
        song_tag_repo.assign_tag_to_song(wildcard_song_id, wildcard_tag_id)
        song_tag_repo.assign_tag_to_song(underscore_match_id, underscore_match_tag_id)
        song_tag_repo.assign_tag_to_song(underscore_wildcard_id, underscore_wildcard_tag_id)

        result = song_tag_repo.search_songs_by_tag_contains("genre", "100%")
        underscore_result = song_tag_repo.search_songs_by_tag_contains("genre", "100_")

        assert [song["id"] for song in result] == [matching_song_id]
        assert [song["id"] for song in underscore_result] == [underscore_match_id]

    def test_tag_value_search_escapes_like_wildcards(self, pg_session) -> None:
        """Tag value filters should treat percent and underscore literally."""
        _create_tag(pg_session, name="genre", value="100% rock", namespace="genre")
        _create_tag(pg_session, name="genre", value="1000 rock", namespace="genre")
        _create_tag(pg_session, name="genre", value="100_ rock", namespace="genre")
        repo = TagRepository(pg_session)

        assert repo.count_tags_filtered(name="genre", search="100%") == 1
        result = repo.list_tags_with_song_count(name="genre", search="100%")

        assert [tag["value"] for tag in result] == ["100% rock"]
        assert repo.count_tags_filtered(name="genre", search="100_") == 1

    def test_get_tag_value_frequencies(self, pg_session) -> None:
        """get_tag_value_frequencies groups by namespace, never collapsing values."""
        # Create tags with same name and value but different namespaces
        _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        _create_tag(pg_session, name="genre", value="rock", namespace="mood")
        _create_tag(pg_session, name="genre", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = repo.get_tag_value_frequencies("genre", limit=10)
        assert len(result) == 3
        counts = {(ns, v): c for ns, v, c in result}
        # The two namespaces are NOT collapsed onto one (rock, 2) row.
        assert counts[("genre", "rock")] == 1
        assert counts[("mood", "rock")] == 1
        assert counts[("genre", "pop")] == 1

    def test_replace_tag_references(self, pg_session) -> None:
        """replace_tag_references should re-point assignments."""
        _, song_id = _create_library_and_song(pg_session)
        source_id = _create_tag(pg_session, name="old", value="old", namespace="genre")
        target_id = _create_tag(pg_session, name="new", value="new", namespace="genre")
        song_tag_repo = SongTagRepository(pg_session)
        TagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, source_id)
        song_tag_repo.relink_song_tags(source_id, target_id)
        tags = song_tag_repo.get_tags_for_song(song_id)
        assert len(tags) == 1
        assert tags[0]["id"] == target_id

    def test_replace_tag_references_removes_source_when_target_exists(self, pg_session) -> None:
        """replace_tag_references should remove source edges on target collisions."""
        _, song_with_source_id = _create_library_and_song(pg_session)
        _, song_with_both_id = _create_library_and_song(pg_session)
        source_id = _create_tag(pg_session, name="old", value="old", namespace="genre")
        target_id = _create_tag(pg_session, name="new", value="new", namespace="genre")
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(song_with_source_id, source_id)
        repo.assign_tag_to_song(song_with_both_id, source_id)
        repo.assign_tag_to_song(song_with_both_id, target_id)

        repo.relink_song_tags(source_id, target_id)

        source_tags = repo.get_tags_for_song(song_with_source_id)
        both_tags = repo.get_tags_for_song(song_with_both_id)
        assert [tag["id"] for tag in source_tags] == [target_id]
        assert {tag["id"] for tag in both_tags} == {target_id}

    def test_replace_tag_references_scopes_collision_removal(self, pg_session) -> None:
        """Scoped relinks remove selected collisions but preserve outside sources."""
        _, selected_song_id = _create_library_and_song(pg_session)
        _, outside_song_id = _create_library_and_song(pg_session)
        source_id = _create_tag(pg_session, name="old", value="old", namespace="genre")
        target_id = _create_tag(pg_session, name="new", value="new", namespace="genre")
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(selected_song_id, source_id)
        repo.assign_tag_to_song(selected_song_id, target_id)
        repo.assign_tag_to_song(outside_song_id, source_id)
        repo.assign_tag_to_song(outside_song_id, target_id)

        repo.relink_song_tags(source_id, target_id, song_ids=[selected_song_id])

        assert {tag["id"] for tag in repo.get_tags_for_song(selected_song_id)} == {target_id}
        assert {tag["id"] for tag in repo.get_tags_for_song(outside_song_id)} == {source_id, target_id}

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

    def test_value_search_filters_tag_value(self, pg_session) -> None:
        """Search should match values rather than tag names."""
        _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        _create_tag(pg_session, name="genre", value="jazz", namespace="genre")
        repo = TagRepository(pg_session)

        result = repo.list_tags_with_song_count(name="genre", search="ro")
        count = repo.count_tags_filtered(name="genre", search="ro")

        assert [tag["value"] for tag in result] == ["rock"]
        assert count == 1

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

    # ── numeric tag search (Phase 1 SQL pagination) ─────────────

    def test_search_songs_by_numeric_tag_orders_by_distance_and_paginates(self, pg_session) -> None:
        """Numeric search orders by absolute distance and applies SQL offset/limit."""
        _, s170 = _create_library_and_song(pg_session)
        _, s175 = _create_library_and_song(pg_session)
        _, s180 = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(s170, _create_tag(pg_session, name="genre", value="170", namespace="genre"))
        repo.assign_tag_to_song(s175, _create_tag(pg_session, name="genre", value="175", namespace="genre"))
        repo.assign_tag_to_song(s180, _create_tag(pg_session, name="genre", value="180", namespace="genre"))

        all_rows = repo.search_songs_by_numeric_tag("genre", 172)
        # distances: |170-172|=2, |175-172|=3, |180-172|=8
        assert [r["id"] for r in all_rows] == [s170, s175, s180]
        assert [r["matched_tag"] for r in all_rows] == ["170", "175", "180"]
        assert [r["distance"] for r in all_rows] == [2.0, 3.0, 8.0]

        page = repo.search_songs_by_numeric_tag("genre", 172, limit=1, offset=1)
        assert [r["id"] for r in page] == [s175]
        page2 = repo.search_songs_by_numeric_tag("genre", 172, limit=2, offset=0)
        assert [r["id"] for r in page2] == [s170, s175]

    def test_search_songs_by_numeric_tag_excludes_non_numeric_values(self, pg_session) -> None:
        """Non-numeric tag text must never be coerced and must not match."""
        _, numeric_song = _create_library_and_song(pg_session)
        _, text_song = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(numeric_song, _create_tag(pg_session, name="genre", value="180", namespace="genre"))
        repo.assign_tag_to_song(text_song, _create_tag(pg_session, name="genre", value="rock", namespace="genre"))

        rows = repo.search_songs_by_numeric_tag("genre", 180)
        assert [r["id"] for r in rows] == [numeric_song]
        assert repo.count_songs_by_numeric_tag("genre", 180) == 1

    def test_search_songs_by_numeric_tag_picks_closest_tag_per_song(self, pg_session) -> None:
        """A song with several numeric tags yields exactly one (closest) match.

        Two-sided: tags lie on both sides of the target, so the closest tag is
        not merely the smallest value (regression for per-song winner ordering
        by distance rather than by raw value).
        """
        _, song = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        # Tags on both sides of the target: 160 (distance 12) and 175 (distance 3) from 172.
        repo.assign_tag_to_song(song, _create_tag(pg_session, name="genre", value="160", namespace="genre"))
        repo.assign_tag_to_song(song, _create_tag(pg_session, name="genre", value="175", namespace="genre"))

        rows = repo.search_songs_by_numeric_tag("genre", 172)
        assert len(rows) == 1
        assert rows[0]["id"] == song
        assert rows[0]["matched_tag"] == "175"
        assert rows[0]["distance"] == 3.0

    def test_search_songs_by_numeric_tag_tie_breaks_by_tag_id(self, pg_session) -> None:
        """Equal-distance tags on one song resolve deterministically by tag id."""
        _, song = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        # Both distance 3 from 172; "175" created first gets the lower tag id.
        repo.assign_tag_to_song(song, _create_tag(pg_session, name="genre", value="175", namespace="genre"))
        repo.assign_tag_to_song(song, _create_tag(pg_session, name="genre", value="175.0", namespace="genre"))

        rows = repo.search_songs_by_numeric_tag("genre", 172)
        assert len(rows) == 1
        assert rows[0]["matched_tag"] == "175"

    def test_count_songs_by_numeric_tag_uncapped_distinct(self, pg_session) -> None:
        """Numeric count is a separate uncapped distinct-song count."""
        _, s1 = _create_library_and_song(pg_session)
        _, s2 = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        tag_id = _create_tag(pg_session, name="genre", value="180", namespace="genre")
        repo.assign_tag_to_song(s1, tag_id)
        repo.assign_tag_to_song(s2, tag_id)
        assert repo.count_songs_by_numeric_tag("genre", 180) == 2
        # Any target still counts the full numeric-tag result universe.
        assert repo.count_songs_by_numeric_tag("genre", 999) == 2

    def test_numeric_guard_compiles_safely_per_dialect(self) -> None:
        """Guarded numeric cast compiles for PostgreSQL and SQLite without a bare cast."""
        from sqlalchemy.dialects import postgresql, sqlite

        from nomarr.persistence.database.song_tag_repo import _NUMERIC_TEXT_RE

        value_col = Tag.__table__.c.value

        pg_expr = SongTagRepository._guarded_numeric_value(value_col, "postgresql")
        pg_sql = str(pg_expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        # CASE guard wraps the CAST and the strict regex is used.
        assert "CASE WHEN" in pg_sql
        assert _NUMERIC_TEXT_RE in pg_sql
        assert "CAST(tags.value AS FLOAT)" in pg_sql

        sqlite_expr = SongTagRepository._guarded_numeric_value(value_col, "sqlite")
        sqlite_sql = str(sqlite_expr.compile(dialect=sqlite.dialect(), compile_kwargs={"literal_binds": True}))
        assert "CASE WHEN" in sqlite_sql
        assert "GLOB" in sqlite_sql
        assert "CAST(tags.value AS FLOAT)" in sqlite_sql
        # Neither dialect may emit a bare (unguarded) cast of the value.
        assert "CASE" in pg_sql and "CASE" in sqlite_sql

    def test_search_songs_by_numeric_tag_deterministic_song_ties(self, pg_session) -> None:
        """Songs at equal distance tie-break by song id ASC, independent of edge insert order."""
        _, s_a = _create_library_and_song(pg_session)
        _, s_b = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        # Both distance 10 from target 100 (values 90 and 110).
        tag_a = _create_tag(pg_session, name="rating", value="90", namespace="genre")
        tag_b = _create_tag(pg_session, name="rating", value="110", namespace="genre")
        # Insert edges in reverse song-id order (higher id first) to prove the SQL
        # orders by song id rather than by insertion order.
        repo.assign_tag_to_song(s_b, tag_b)
        repo.assign_tag_to_song(s_a, tag_a)

        rows = repo.search_songs_by_numeric_tag("rating", 100)

        # s_a was created first so it has the lower auto-increment id.
        assert [r["id"] for r in rows] == sorted([s_a, s_b])
        assert [r["distance"] for r in rows] == [10.0, 10.0]

    def test_search_songs_by_numeric_tag_offset_beyond_end_returns_empty(self, pg_session) -> None:
        """An offset past the result set yields an empty page."""
        _, s1 = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(s1, _create_tag(pg_session, name="rating", value="5", namespace="genre"))

        rows = repo.search_songs_by_numeric_tag("rating", 5, limit=10, offset=100)

        assert rows == []

    def test_numeric_query_compiles_with_window_order_and_pagination(self, pg_session) -> None:
        """The real paged query compiles with a guarded cast, row_number window, ORDER BY, and LIMIT/OFFSET.

        Captures the exact statement ``search_songs_by_numeric_tag`` builds (running
        against the SQLite-backed ``pg_session`` fixture) and compiles it through both
        the SQLite and PostgreSQL dialect compilers. Ordering and pagination must live
        in SQL, not Python slicing.
        """
        from sqlalchemy.dialects import postgresql, sqlite

        _, s1 = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(s1, _create_tag(pg_session, name="rating", value="5", namespace="genre"))

        captured: dict = {}
        real_execute = pg_session.execute

        def _capture(stmt, *args, **kwargs):
            captured["stmt"] = stmt
            return real_execute(stmt, *args, **kwargs)

        pg_session.execute = _capture
        repo.search_songs_by_numeric_tag("rating", 5, limit=10, offset=20)

        stmt = captured["stmt"]
        assert stmt is not None
        pg_sql = str(stmt.compile(dialect=postgresql.dialect()))
        sqlite_sql = str(stmt.compile(dialect=sqlite.dialect()))

        for sql in (pg_sql, sqlite_sql):
            # Guarded numeric cast (no unconditional CAST of arbitrary text).
            assert "CASE WHEN" in sql
            assert "CAST(tags.value AS FLOAT)" in sql
            # One closest tag per song via a row_number window with distance then tag-id tie-break.
            assert "row_number() OVER" in sql
            assert "PARTITION BY" in sql
            assert "tags.id ASC" in sql
            # SQL-level ordering and pagination (LIMIT/OFFSET bound parameters).
            assert "ORDER BY" in sql
            assert "LIMIT" in sql
            assert "OFFSET" in sql
        # The SQLite-built query uses the GLOB guard (no regexp() on SQLite).
        assert "GLOB" in sqlite_sql

    def test_search_songs_by_numeric_tag_uncapped_over_1000_matches(self, pg_session) -> None:
        """>1000 matching edges are all searchable/countable with no arbitrary cap.

        Insert 1005 songs with a matching numeric tag edge in REVERSED song-id order
        so the regression is non-vacuous: correct ordering comes from SQL, not from
        insertion order or a Python slice. Old code capped the edge materialization at
        DEFAULT_LIMIT=1000, so a count/search over 1005 matches proves the paged intent.
        """
        from sqlalchemy import select

        lib_id, _ = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        tag_id = _create_tag(pg_session, name="rating", value="5", namespace="genre")

        n = 1005
        song_rows = [
            {
                "library_id": lib_id,
                "path": f"/tag/lib/song{i}.mp3",
                "normalized_path": f"song{i}.mp3",
                "file_size": 1000,
                "modified_time": 1000,
                "duration_seconds": None,
                "needs_tagging": 0,
                "is_valid": 1,
                "tagged": 0,
                "created_at": 1000,
            }
            for i in range(n)
        ]
        pg_session.execute(insert(Song), song_rows)
        pg_session.commit()

        # Only the bulk-inserted songs (the helper's first song has no numeric edge).
        song_ids = [
            r[0]
            for r in pg_session.execute(select(Song.id).where(Song.normalized_path.like("song%")).order_by(Song.id))
        ]
        assert len(song_ids) == n

        # Insert edges in REVERSED song-id order (non-vacuous).
        edge_rows = [
            {
                "song_id": sid,
                "tag_id": tag_id,
                "confidence": 1.0,
                "source": "nomarr",
                "created_at": 1000,
            }
            for sid in reversed(song_ids)
        ]
        pg_session.execute(insert(SongTag), edge_rows)
        pg_session.commit()

        # Uncapped distinct-song count proves NO edge cap (old code capped at DEFAULT_LIMIT=1000).
        assert repo.count_songs_by_numeric_tag("rating", 5) == n

        # Paging through in chunks returns every match with no overlap/gaps.
        pages = [
            repo.search_songs_by_numeric_tag("rating", 5, limit=250, offset=offset)
            for offset in (0, 250, 500, 750, 1000)
        ]
        concatenated = [r["id"] for page in pages for r in page]

        assert len(concatenated) == n
        assert len(set(concatenated)) == n  # no overlap
        assert concatenated == sorted(song_ids)  # no gaps, SQL order by song id
        assert len(pages[-1]) == n - 250 * 4  # last-page math: 1005 = 250*4 + 5

        # Repeated page requests are identical (song_id, matched_tag, distance).
        def _tuples(rows):
            return [(r["id"], r["matched_tag"], r["distance"]) for r in rows]

        page_a = repo.search_songs_by_numeric_tag("rating", 5, limit=250, offset=250)
        page_b = repo.search_songs_by_numeric_tag("rating", 5, limit=250, offset=250)
        assert _tuples(page_a) == _tuples(page_b)

        # Page totals equal the separate uncapped count.
        assert sum(len(page) for page in pages) == repo.count_songs_by_numeric_tag("rating", 5)

    def test_count_songs_by_numeric_tag_no_match_returns_zero(self, pg_session) -> None:
        """Count is 0 when no tag has the requested key (target value irrelevant)."""
        _, s1 = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(s1, _create_tag(pg_session, name="rating", value="5", namespace="genre"))

        assert repo.count_songs_by_numeric_tag("nom:mood", 5) == 0

    def test_count_songs_by_numeric_tag_only_counts_numeric_values(self, pg_session) -> None:
        """Only songs whose tag value is valid numeric text are counted."""
        _, s_numeric = _create_library_and_song(pg_session)
        _, s_text = _create_library_and_song(pg_session)
        _, s_decimal = _create_library_and_song(pg_session)
        repo = SongTagRepository(pg_session)
        repo.assign_tag_to_song(s_numeric, _create_tag(pg_session, name="rating", value="5", namespace="genre"))
        repo.assign_tag_to_song(s_text, _create_tag(pg_session, name="rating", value="not-a-number", namespace="genre"))
        repo.assign_tag_to_song(s_decimal, _create_tag(pg_session, name="rating", value="7.5", namespace="genre"))

        assert repo.count_songs_by_numeric_tag("rating", 5) == 2


@pytest.mark.unit
@pytest.mark.integration
class TestTagIdentitySpec:
    """Spec-first repository cases against the immutable user ledger.

    These pin the identity-only contract at the repository boundary:
    ``(default, genre, Rock)`` and ``(nom, genre, Rock)`` are distinct
    identities; duplicate complete-key insertion is prevented; ordinary
    namespace normalizes to the literal ``default`` (never NULL/empty); and
    repository result rows expose no removed tag metadata. The normalization
    and identity-only-row assertions are expected to FAIL against the current
    repository until Phase 3 (P3-S2/P3-S3) lands.
    """

    def test_default_and_nom_namespaces_are_distinct_identities(self, pg_session) -> None:
        """(default, genre, Rock) and (nom, genre, Rock) resolve to separate tag rows."""
        repo = TagRepository(pg_session)
        default_id = repo.get_or_create_tag("genre", "Rock", "default")
        nom_id = repo.get_or_create_tag("genre", "Rock", "nom")
        assert default_id != nom_id
        default_row = repo.get_tag(default_id)
        nom_row = repo.get_tag(nom_id)
        assert default_row is not None and nom_row is not None
        assert (default_row["namespace"], default_row["name"], default_row["value"]) == ("default", "genre", "Rock")
        assert (nom_row["namespace"], nom_row["name"], nom_row["value"]) == ("nom", "genre", "Rock")

    def test_complete_key_duplicate_insert_is_prevented(self, pg_session) -> None:
        """Inserting the same complete (namespace, name, value) twice yields one row."""
        from sqlalchemy import func, select

        from nomarr.persistence.models.tag import Tag

        repo = TagRepository(pg_session)
        first = repo.get_or_create_tag("genre", "Rock", "default")
        second = repo.get_or_create_tag("genre", "Rock", "default")
        assert first == second
        count = pg_session.execute(
            select(func.count())
            .select_from(Tag)
            .where(Tag.name == "genre", Tag.value == "Rock", Tag.namespace == "default")
        ).scalar()
        assert count == 1

    def test_same_name_value_different_namespace_not_deduped(self, pg_session) -> None:
        """Same (name, value) in different namespaces must NOT be collapsed by dedup.

        Batch results are keyed by the complete ``(namespace, name, value)`` tuple
        so the two namespaces never collapse onto one tag id.
        """
        repo = TagRepository(pg_session)
        ids = repo.get_or_create_tags_batch(
            [
                {"name": "genre", "value": "Rock", "namespace": "default"},
                {"name": "genre", "value": "Rock", "namespace": "nom"},
            ]
        )
        assert len(ids) == 2
        assert ids[("default", "genre", "Rock")] != ids[("nom", "genre", "Rock")]

    def test_omitted_namespace_normalizes_to_default(self, pg_session) -> None:
        """Omitted ordinary namespace is stored as the literal 'default', never '' or NULL."""
        repo = TagRepository(pg_session)
        result = repo.get_or_create_tags_batch([{"name": "genre", "value": "Rock"}])
        # The complete identity must use the canonical "default" namespace.
        assert ("default", "genre", "Rock") in result
        row = repo.get_tag(result[("default", "genre", "Rock")])
        assert row is not None
        assert row["namespace"] == "default"

    def test_no_null_namespace_rows(self, pg_session) -> None:
        """An empty namespace is normalized to 'default'; no row may carry a NULL/empty namespace."""
        repo = TagRepository(pg_session)
        tag_id = repo.get_or_create_tag("genre", "Rock", "")
        row = repo.get_tag(tag_id)
        assert row is not None
        assert row["namespace"] == "default"

    def test_result_rows_have_no_removed_tag_metadata_keys(self, pg_session) -> None:
        """Repository tag rows expose only id, namespace, name, value."""
        repo = TagRepository(pg_session)
        tag_id = repo.get_or_create_tag("genre", "Rock", "default")
        row = repo.get_tag(tag_id)
        assert row is not None
        assert set(row.keys()) == {"id", "namespace", "name", "value"}

    def test_edge_writes_never_modify_shared_tag_row(self, pg_session) -> None:
        """P3-S7: edge writes touch only ``song_tags``, never a shared ``tags`` row.

        Reassigning the same tag to a song with different per-song edge metadata
        (confidence/source) must not issue an UPDATE against the shared ``tags``
        identity row — the identity stays intact and the row count unchanged.
        """
        _, song_id = _create_library_and_song(pg_session)
        repo = TagRepository(pg_session)
        tag_id = repo.get_or_create_tag("genre", "Rock", "default")

        song_tag_repo = SongTagRepository(pg_session)
        song_tag_repo.assign_tag_to_song(song_id, tag_id, confidence=0.9, source="ml")
        # Edge rewrite with different per-song metadata.
        song_tag_repo.replace_song_tags(song_id, [{"tag_id": tag_id, "confidence": 0.7, "source": "nomarr"}])

        # The shared tags identity row is untouched (no UPDATE against tags).
        row = repo.get_tag(tag_id)
        assert row is not None
        assert row["namespace"] == "default"
        assert row["name"] == "genre"
        assert row["value"] == "Rock"
        assert set(row.keys()) == {"id", "namespace", "name", "value"}
        # Exactly one tag row still exists for this identity.
        total = pg_session.execute(select(func.count()).select_from(Tag)).scalar_one()
        assert total == 1
        # The edge metadata was replaced per song (independent of the tag row).
        edges = song_tag_repo.get_song_tag_edges_for_tags([tag_id])
        assert len(edges) == 1
        assert edges[0]["confidence"] == 0.7
        assert edges[0]["source"] == "nomarr"
