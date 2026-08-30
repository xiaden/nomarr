"""Tests for ``nomarr.services.domain.metadata_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from nomarr.helpers.dataclasses.song_tag_dataclass import TagCleanupResult, TagRef
from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.services.domain.metadata_svc import COLLECTION_REL_MAP, EntityCollection, MetadataService


def _make_service(*, db: MagicMock | None = None) -> MetadataService:
    """Build a MetadataService with a mock database."""
    return MetadataService(db=db or MagicMock())


class TestCollectionRelMap:
    """Tests for singular collection-to-rel mapping."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_contains_all_singular_collection_keys(self) -> None:
        """Collection map should expose the expected singular rel values."""
        assert COLLECTION_REL_MAP == {
            "artist": "artist",
            "album": "album",
            "label": "label",
            "genre": "genre",
            "year": "year",
        }


class TestListEntities:
    """Tests for list_entities."""

    @pytest.mark.unit
    @pytest.mark.mocked
    @pytest.mark.parametrize(
        ("collection", "expected_name"),
        [
            ("artist", "artist"),
            ("album", "album"),
            ("label", "label"),
            ("genre", "genre"),
            ("year", "year"),
        ],
    )
    def test_uses_name_mapped_from_collection(
        self,
        collection: EntityCollection,
        expected_name: str,
    ) -> None:
        """Each singular collection should resolve to the correct name query."""
        mock_db = MagicMock()
        service = _make_service(db=mock_db)

        with (
            patch("nomarr.services.domain.metadata_svc.list_tags_by_name", return_value=[]) as mock_list,
            patch("nomarr.services.domain.metadata_svc.count_tags_by_name", return_value=0) as mock_count,
        ):
            result = service.list_entities(collection)

        assert result == {
            "entities": [],
            "total": 0,
            "limit": 100,
            "offset": 0,
        }
        mock_list.assert_called_once_with(
            mock_db,
            expected_name,
            limit=100,
            offset=0,
            search=None,
        )
        mock_count.assert_called_once_with(mock_db, expected_name, search=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_through_limit_offset_and_search(self) -> None:
        """Explicit paging and search options should be forwarded to persistence."""
        mock_db = MagicMock()
        listed_tags = [
            {
                "id": "The Artist",
                "value": "The Artist",
                "song_count": 12,
            },
        ]
        service = _make_service(db=mock_db)

        with (
            patch("nomarr.services.domain.metadata_svc.list_tags_by_name", return_value=listed_tags) as mock_list,
            patch("nomarr.services.domain.metadata_svc.count_tags_by_name", return_value=1) as mock_count,
        ):
            result = service.list_entities("artist", limit=10, offset=5, search="art")

        assert result == {
            "entities": [
                {
                    "id": "The Artist",
                    "display_name": "The Artist",
                    "song_count": 12,
                },
            ],
            "total": 1,
            "limit": 10,
            "offset": 5,
        }
        mock_list.assert_called_once_with(
            mock_db,
            "artist",
            limit=10,
            offset=5,
            search="art",
        )
        mock_count.assert_called_once_with(mock_db, "artist", search="art")


class TestGetEntity:
    """Tests for get_entity."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_tag_not_found(self) -> None:
        """Missing tags should surface as None."""
        mock_db = MagicMock()
        service = _make_service(db=mock_db)

        mock_db.library.get_tag.return_value = None
        result = service.get_entity("artist", "Metallica")

        assert result is None
        mock_db.library.get_tag.assert_called_once_with(TagRef(name="artist", value="Metallica"))
        mock_db.library.find_songs_with_tag.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_entity_dict_when_tag_found(self) -> None:
        """Existing tags should be transformed into an entity dict."""
        mock_db = MagicMock()
        mock_db.library.get_tag.return_value = TagRef(name="artist", value="The Artist")
        mock_db.library.find_songs_with_tag.return_value = (MagicMock(),) * 7
        service = _make_service(db=mock_db)

        result = service.get_entity("artist", "The Artist")

        assert result == {"id": "The Artist", "display_name": "The Artist", "song_count": 7}
        mock_db.library.get_tag.assert_called_once_with(TagRef(name="artist", value="The Artist"))
        mock_db.library.find_songs_with_tag.assert_called_once_with(
            TagRef(name="artist", value="The Artist"), limit=None
        )


class TestGetEntityCounts:
    """Tests for get_entity_counts."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_tags_persistence_for_all_singular_names(self) -> None:
        """Entity counts should be derived from the tags persistence layer."""
        mock_db = MagicMock()
        counts_by_name = {
            "artist": 11,
            "album": 22,
            "label": 33,
            "genre": 44,
            "year": 55,
        }
        service = _make_service(db=mock_db)

        with patch(
            "nomarr.services.domain.metadata_svc.count_tags_by_name",
            side_effect=lambda _db, name: counts_by_name[name],
        ) as mock_count:
            result = service.get_entity_counts()

        assert result == {
            "artists": 11,
            "albums": 22,
            "labels": 33,
            "genres": 44,
            "years": 55,
        }
        mock_count.assert_has_calls(
            [
                call(mock_db, "artist"),
                call(mock_db, "album"),
                call(mock_db, "label"),
                call(mock_db, "genre"),
                call(mock_db, "year"),
            ],
        )
        assert mock_count.call_count == 5


class TestListSongsForEntity:
    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_song_ids_and_count_via_flat_api(self) -> None:
        mock_db = MagicMock()
        service = _make_service(db=mock_db)
        songs = [MagicMock(song_id=1), MagicMock(song_id=2)]
        mock_db.library.find_songs_with_tag.side_effect = [songs, [MagicMock() for _ in range(5)]]
        result = service.list_songs_for_entity("artist", "Metallica", "artist", limit=10, offset=0)
        assert result["song_ids"] == [1, 2]
        assert all(isinstance(song_id, int) for song_id in result["song_ids"])
        assert result["total"] == 5
        assert result["limit"] == 10
        assert result["offset"] == 0
        assert mock_db.library.find_songs_with_tag.call_args_list == [
            call(TagRef(name="artist", value="Metallica"), limit=10, offset=0),
            call(TagRef(name="artist", value="Metallica"), limit=None),
        ]

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_paging_params_forwarded(self) -> None:
        mock_db = MagicMock()
        service = _make_service(db=mock_db)
        mock_db.library.find_songs_with_tag.side_effect = [[], [MagicMock() for _ in range(100)]]
        result = service.list_songs_for_entity("genre", "Electronic", "genre", limit=25, offset=50)
        assert result["limit"] == 25
        assert result["offset"] == 50
        assert mock_db.library.find_songs_with_tag.call_args_list == [
            call(TagRef(name="genre", value="Electronic"), limit=25, offset=50),
            call(TagRef(name="genre", value="Electronic"), limit=None),
        ]


class TestCleanupOrphanedEntities:
    """Tests for cleanup_orphaned_entities dry_run branching."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_dry_run_counts_but_does_not_delete(self) -> None:
        mock_db = MagicMock()
        service = _make_service(db=mock_db)
        with (
            patch(
                "nomarr.services.domain.metadata_svc.count_orphaned_tags",
                return_value=5,
            ) as mock_count,
            patch(
                "nomarr.services.domain.metadata_svc.cleanup_orphaned_tags",
            ) as mock_cleanup,
        ):
            result = service.cleanup_orphaned_entities(dry_run=True)

        assert result == {"orphaned_count": 5, "deleted_count": 0}
        mock_count.assert_called_once_with(mock_db)
        mock_cleanup.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_live_run_deletes_and_reports_real_counts(self) -> None:
        mock_db = MagicMock()
        service = _make_service(db=mock_db)
        with (
            patch(
                "nomarr.services.domain.metadata_svc.count_orphaned_tags",
                return_value=9,
            ) as mock_count,
            patch(
                "nomarr.services.domain.metadata_svc.cleanup_orphaned_tags",
                return_value=TagCleanupResult(deleted=4, orphaned=7),
            ) as mock_cleanup,
        ):
            result = service.cleanup_orphaned_entities(dry_run=False)

        assert result == {"orphaned_count": 7, "deleted_count": 4}
        mock_cleanup.assert_called_once_with(mock_db)
        mock_count.assert_not_called()


class TestMetadataTraversal:
    """Tests for natural-ID artist and album traversal."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_lists_deduplicated_sorted_albums_for_artist(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = [MagicMock(song_id=1), MagicMock(song_id=2)]
        service = _make_service(db=mock_db)
        with patch(
            "nomarr.services.domain.metadata_svc.get_song_tags",
            side_effect=[
                Tags(items=(Tag(name="album", values=("Zeta", "Alpha")),)),
                Tags(items=(Tag(name="album", values=("Alpha",)),)),
            ],
        ):
            result = service.list_albums_for_artist("Metallica", limit=10)
        assert [album["id"] for album in result] == ["Alpha", "Zeta"]
        mock_db.library.find_songs_with_tag.assert_called_once_with(
            TagRef(name="artist", value="Metallica"), limit=10000
        )

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_lists_deduplicated_sorted_artists_for_album_with_limit(self) -> None:
        mock_db = MagicMock()
        mock_db.library.find_songs_with_tag.return_value = [MagicMock(song_id=3), MagicMock(song_id=4)]
        service = _make_service(db=mock_db)
        with patch(
            "nomarr.services.domain.metadata_svc.get_song_tags",
            side_effect=[
                Tags(items=(Tag(name="artist", values=("Zeta", "Alpha")),)),
                None,
            ],
        ):
            result = service.list_artists_for_album("Record", limit=1)
        assert [artist["id"] for artist in result] == ["Alpha"]
        mock_db.library.find_songs_with_tag.assert_called_once_with(TagRef(name="album", value="Record"), limit=10000)
