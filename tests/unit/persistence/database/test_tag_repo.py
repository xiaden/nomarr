"""Unit tests for TagRepository and FileTagRepository."""

from __future__ import annotations

import pytest
from sqlalchemy import insert

from nomarr.persistence.database.file_tag_repo import FileTagRepository
from nomarr.persistence.database.tag_repo import TagRepository
from nomarr.persistence.models.file_tag import FileTag
from nomarr.persistence.models.library import Library
from nomarr.persistence.models.library_file import LibraryFile
from nomarr.persistence.models.tag import Tag


async def _create_library_and_file(session) -> tuple[int, int]:
    """Helper: create a library and a file, return (library_id, file_id)."""
    lib_r = await session.execute(
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
    file_r = await session.execute(
        insert(LibraryFile).values(
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
    file_id = file_r.inserted_primary_key[0]
    return lib_id, file_id


async def _create_tag(session, name: str = "rock", value: str = "rock", namespace: str = "genre") -> int:
    """Helper: create a tag and return its id."""
    r = await session.execute(
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

    @pytest.mark.asyncio
    async def test_get_tag_existing(self, pg_session) -> None:
        """get_tag should return the tag as a dict."""
        tag_id = await _create_tag(pg_session)
        repo = TagRepository(pg_session)
        result = await repo.get_tag(tag_id)
        assert result is not None
        assert result["id"] == tag_id
        assert result["name"] == "rock"
        assert result["namespace"] == "genre"

    @pytest.mark.asyncio
    async def test_get_tag_nonexistent(self, pg_session) -> None:
        """get_tag should return None for missing id."""
        repo = TagRepository(pg_session)
        result = await repo.get_tag(999999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tag_by_name(self, pg_session) -> None:
        """get_tag_by_name should find tag by name and namespace."""
        tag_id = await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.get_tag_by_name("pop", "genre")
        assert result is not None
        assert result["id"] == tag_id
        assert result["name"] == "pop"

    @pytest.mark.asyncio
    async def test_get_tag_by_name_nonexistent(self, pg_session) -> None:
        """get_tag_by_name should return None for missing tag."""
        repo = TagRepository(pg_session)
        result = await repo.get_tag_by_name("nonexistent", "genre")
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_create_tag_existing(self, pg_session) -> None:
        """get_or_create_tag should return existing tag id."""
        tag_id = await _create_tag(pg_session, name="jazz", value="jazz", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.get_or_create_tag("jazz", "jazz", "genre")
        assert result == tag_id

    @pytest.mark.asyncio
    async def test_get_or_create_tag_new(self, pg_session) -> None:
        """get_or_create_tag should create and return new tag id."""
        repo = TagRepository(pg_session)
        result = await repo.get_or_create_tag("blues", "blues", "genre")
        assert isinstance(result, int)
        assert result > 0
        # Verify it exists
        tag = await repo.get_tag(result)
        assert tag is not None
        assert tag["name"] == "blues"

    @pytest.mark.asyncio
    async def test_create_tag(self, pg_session) -> None:
        """create_tag should insert and return id."""
        repo = TagRepository(pg_session)
        tag_id = await repo.create_tag(
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

    @pytest.mark.asyncio
    async def test_delete_tag(self, pg_session) -> None:
        """delete_tag should remove the row."""
        tag_id = await _create_tag(pg_session)
        repo = TagRepository(pg_session)
        await repo.delete_tag(tag_id)
        result = await repo.get_tag(tag_id)
        assert result is None

    # ── file-tag associations ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_tags_for_file(self, pg_session) -> None:
        """get_tags_for_file should return tags assigned to a file."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id1 = await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        tag_id2 = await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id1, confidence=0.9)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id2, confidence=0.8)
        result = await file_tag_repo.get_tags_for_file(file_id)
        assert len(result) == 2
        names = {t["name"] for t in result}
        assert "rock" in names
        assert "pop" in names

    @pytest.mark.asyncio
    async def test_assign_tag_to_file(self, pg_session) -> None:
        """assign_tag_to_file should create a file-tag association."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id, confidence=0.95, source="ml")
        tags = await file_tag_repo.get_tags_for_file(file_id)
        assert len(tags) == 1
        assert tags[0]["id"] == tag_id

    @pytest.mark.asyncio
    async def test_remove_tag_from_file(self, pg_session) -> None:
        """remove_tag_from_file should delete the association."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        await file_tag_repo.remove_tag_from_file(file_id, tag_id)
        tags = await file_tag_repo.get_tags_for_file(file_id)
        assert len(tags) == 0

    @pytest.mark.asyncio
    async def test_replace_file_tags(self, pg_session) -> None:
        """replace_file_tags should delete old and insert new assignments."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id1 = await _create_tag(pg_session, name="old1", value="old1", namespace="genre")
        tag_id2 = await _create_tag(pg_session, name="old2", value="old2", namespace="genre")
        tag_id3 = await _create_tag(pg_session, name="new1", value="new1", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id1)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id2)
        await file_tag_repo.replace_file_tags(
            file_id,
            [
                {"tag_id": tag_id3, "confidence": 0.9, "source": "ml"},
            ],
        )
        tags = await file_tag_repo.get_tags_for_file(file_id)
        assert len(tags) == 1
        assert tags[0]["name"] == "new1"

    @pytest.mark.asyncio
    async def test_get_files_for_tag(self, pg_session) -> None:
        """get_files_for_tag should return files assigned to a tag."""
        _, file_id1 = await _create_library_and_file(pg_session)
        _, file_id2 = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id1, tag_id)
        await file_tag_repo.assign_tag_to_file(file_id2, tag_id)
        result = await file_tag_repo.get_files_for_tag(tag_id)
        assert len(result) == 2
        ids = {f["id"] for f in result}
        assert file_id1 in ids
        assert file_id2 in ids

    @pytest.mark.asyncio
    async def test_list_file_ids_for_tag(self, pg_session) -> None:
        """list_file_ids_for_tag should return file ids with pagination."""
        _, file_id1 = await _create_library_and_file(pg_session)
        _, file_id2 = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id1, tag_id)
        await file_tag_repo.assign_tag_to_file(file_id2, tag_id)
        result = await file_tag_repo.list_file_ids_for_tag(tag_id, limit=1, offset=0)
        assert len(result) == 1
        assert result[0] in (file_id1, file_id2)

    # ── orphan management ───────────────────────────────────────

    @pytest.mark.asyncio
    async def test_get_orphaned_tag_ids(self, pg_session) -> None:
        """get_orphaned_tag_ids should return tags with no file assignments."""
        tag_id1 = await _create_tag(pg_session, name="orphan1", value="orphan1", namespace="genre")
        tag_id2 = await _create_tag(pg_session, name="orphan2", value="orphan2", namespace="genre")
        _, file_id = await _create_library_and_file(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id1)
        result = await tag_repo.get_orphaned_tag_ids()
        assert tag_id2 in result
        assert tag_id1 not in result

    @pytest.mark.asyncio
    async def test_cleanup_orphaned_tags(self, pg_session) -> None:
        """cleanup_orphaned_tags should delete tags with no assignments."""
        tag_id1 = await _create_tag(pg_session, name="keep", value="keep", namespace="genre")
        tag_id2 = await _create_tag(pg_session, name="delete", value="delete", namespace="genre")
        _, file_id = await _create_library_and_file(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id1)
        deleted = await tag_repo.cleanup_orphaned_tags()
        assert deleted == 1
        assert await tag_repo.get_tag(tag_id1) is not None
        assert await tag_repo.get_tag(tag_id2) is None

    # ── tag listing ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_tags(self, pg_session) -> None:
        """list_tags should return all tags with optional filters."""
        await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.list_tags()
        assert len(result) >= 2
        names = {t["name"] for t in result}
        assert "rock" in names
        assert "pop" in names

    @pytest.mark.asyncio
    async def test_list_tags_with_name_filter(self, pg_session) -> None:
        """list_tags should filter by name."""
        await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.list_tags(name="rock")
        assert len(result) == 1
        assert result[0]["name"] == "rock"

    @pytest.mark.asyncio
    async def test_count_tags(self, pg_session) -> None:
        """count_tags should return total tag count."""
        await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.count_tags()
        assert result >= 2

    @pytest.mark.asyncio
    async def test_get_tags_for_files_batch(self, pg_session) -> None:
        """get_tags_for_files_batch should return tag assignments for multiple files."""
        _, file_id1 = await _create_library_and_file(pg_session)
        _, file_id2 = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id1, tag_id, confidence=0.9)
        await file_tag_repo.assign_tag_to_file(file_id2, tag_id, confidence=0.8)
        result = await file_tag_repo.get_tags_for_files_batch([file_id1, file_id2])
        assert len(result) == 2
        assert all(r["tag_id"] == tag_id for r in result)

    @pytest.mark.asyncio
    async def test_get_song_tags(self, pg_session) -> None:
        """get_song_tags should return tags for a file."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        result = await file_tag_repo.get_song_tags(file_id)
        assert len(result) == 1
        assert result[0]["id"] == tag_id

    # ── search ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_search_files_by_tag(self, pg_session) -> None:
        """search_files_by_tag should find files with exact tag match."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        result = await file_tag_repo.search_files_by_tag("genre", "rock")
        assert len(result) == 1
        assert result[0]["id"] == file_id

    @pytest.mark.asyncio
    async def test_search_files_by_tag_contains(self, pg_session) -> None:
        """search_files_by_tag_contains should find files with partial tag match."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session, name="genre", value="progressive rock", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        result = await file_tag_repo.search_files_by_tag_contains("genre", "rock")
        assert len(result) == 1
        assert result[0]["id"] == file_id

    @pytest.mark.asyncio
    async def test_get_tag_value_frequencies(self, pg_session) -> None:
        """get_tag_value_frequencies should return value counts."""
        # Create tags with same name and value but different namespaces
        await _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        await _create_tag(pg_session, name="genre", value="rock", namespace="mood")
        await _create_tag(pg_session, name="genre", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.get_tag_value_frequencies("genre", limit=10)
        assert len(result) == 2
        # rock should appear twice (different namespaces)
        rock_count = next((c for v, c in result if v == "rock"), 0)
        assert rock_count == 2
        pop_count = next((c for v, c in result if v == "pop"), 0)
        assert pop_count == 1

    @pytest.mark.asyncio
    async def test_replace_tag_references(self, pg_session) -> None:
        """replace_tag_references should re-point assignments."""
        _, file_id = await _create_library_and_file(pg_session)
        source_id = await _create_tag(pg_session, name="old", value="old", namespace="genre")
        target_id = await _create_tag(pg_session, name="new", value="new", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        TagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, source_id)
        await file_tag_repo.replace_tag_references(source_id, target_id)
        tags = await file_tag_repo.get_tags_for_file(file_id)
        assert len(tags) == 1
        assert tags[0]["id"] == target_id

    # ── Plan E facade support ───────────────────────────────────

    @pytest.mark.asyncio
    async def test_list_all_tag_names(self, pg_session) -> None:
        """list_all_tag_names should return distinct names."""
        await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.list_all_tag_names()
        assert "rock" in result
        assert "pop" in result

    @pytest.mark.asyncio
    async def test_count_tags_filtered(self, pg_session) -> None:
        """count_tags_filtered should count with filters."""
        await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        await _create_tag(pg_session, name="pop", value="pop", namespace="genre")
        repo = TagRepository(pg_session)
        result = await repo.count_tags_filtered(name="rock")
        assert result == 1

    @pytest.mark.asyncio
    async def test_list_tags_with_song_count(self, pg_session) -> None:
        """list_tags_with_song_count should include assignment counts."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session, name="rock", value="rock", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        tag_repo = TagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        result = await tag_repo.list_tags_with_song_count()
        assert len(result) >= 1
        rock_tag = next((t for t in result if t["name"] == "rock"), None)
        assert rock_tag is not None
        assert rock_tag["song_count"] == 1

    @pytest.mark.asyncio
    async def test_get_genre_tags_for_files(self, pg_session) -> None:
        """get_genre_tags_for_files should return genre tags for files."""
        _, file_id = await _create_library_and_file(pg_session)
        genre_id = await _create_tag(pg_session, name="genre", value="rock", namespace="genre")
        other_id = await _create_tag(pg_session, name="mood", value="happy", namespace="mood")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, genre_id)
        await file_tag_repo.assign_tag_to_file(file_id, other_id)
        result = await file_tag_repo.get_genre_tags_for_files([file_id])
        assert len(result) == 1
        assert result[0]["name"] == "genre"

    @pytest.mark.asyncio
    async def test_search_files_by_tag_pattern(self, pg_session) -> None:
        """search_files_by_tag_pattern should match ILIKE pattern."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session, name="genre", value="progressive rock", namespace="genre")
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        result = await file_tag_repo.search_files_by_tag_pattern("genre", "%rock%")
        assert len(result) == 1
        assert result[0]["id"] == file_id

    # ── maintenance ─────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_truncate_file_tag_assignments(self, pg_session) -> None:
        """truncate_file_tag_assignments should remove all file_tags."""
        _, file_id = await _create_library_and_file(pg_session)
        tag_id = await _create_tag(pg_session)
        file_tag_repo = FileTagRepository(pg_session)
        await file_tag_repo.assign_tag_to_file(file_id, tag_id)
        await file_tag_repo.truncate_file_tag_assignments()
        from sqlalchemy import select

        result = await pg_session.execute(select(FileTag))
        assert len(result.all()) == 0

    @pytest.mark.asyncio
    async def test_truncate_tags(self, pg_session) -> None:
        """truncate_tags should remove all tags."""
        await _create_tag(pg_session)
        repo = TagRepository(pg_session)
        await repo.truncate_tags()
        from sqlalchemy import select

        result = await pg_session.execute(select(Tag))
        assert len(result.all()) == 0
