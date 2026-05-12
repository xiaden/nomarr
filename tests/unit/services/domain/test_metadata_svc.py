"""Tests for ``nomarr.services.domain.metadata_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

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
                "_id": "tags/artist-1",
                "_key": "artist-1",
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
                    "_id": "tags/artist-1",
                    "_key": "artist-1",
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

        with patch("nomarr.services.domain.metadata_svc.get_tag", return_value=None) as mock_get_tag:
            result = service.get_entity("tags/missing")

        assert result is None
        mock_get_tag.assert_called_once_with(mock_db, "tags/missing")
        mock_db.song_has_tags.count.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_entity_dict_when_tag_found(self) -> None:
        """Existing tags should be transformed into an entity dict."""
        mock_db = MagicMock()
        tag_doc = {
            "_id": "tags/artist-1",
            "_key": "artist-1",
            "value": "The Artist",
        }
        mock_db.library.count_song_tag_edges.return_value = 7
        service = _make_service(db=mock_db)

        with patch("nomarr.services.domain.metadata_svc.get_tag", return_value=tag_doc) as mock_get_tag:
            result = service.get_entity("tags/artist-1")

        assert result == {
            "_id": "tags/artist-1",
            "_key": "artist-1",
            "display_name": "The Artist",
            "song_count": 7,
        }
        mock_get_tag.assert_called_once_with(mock_db, "tags/artist-1")
        mock_db.library.count_song_tag_edges.assert_called_once_with("tags/artist-1")


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
        mock_db.library.count_song_tag_edges.return_value = 5
        service = _make_service(db=mock_db)
        with patch(
            "nomarr.services.domain.metadata_svc.list_songs_for_tag",
            return_value=["songs/1", "songs/2"],
        ) as mock_list:
            result = service.list_songs_for_entity("tags/artist-1", "artist", limit=10, offset=0)
        assert result["song_ids"] == ["songs/1", "songs/2"]
        assert result["total"] == 5
        assert result["limit"] == 10
        assert result["offset"] == 0
        mock_list.assert_called_once_with(mock_db, "tags/artist-1", limit=10, offset=0)
        mock_db.library.count_song_tag_edges.assert_called_once_with("tags/artist-1")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_paging_params_forwarded(self) -> None:
        mock_db = MagicMock()
        mock_db.library.count_song_tag_edges.return_value = 100
        service = _make_service(db=mock_db)
        with patch(
            "nomarr.services.domain.metadata_svc.list_songs_for_tag",
            return_value=[],
        ) as mock_list:
            result = service.list_songs_for_entity("tags/genre-7", "genre", limit=25, offset=50)
        assert result["limit"] == 25
        assert result["offset"] == 50
        mock_list.assert_called_once_with(mock_db, "tags/genre-7", limit=25, offset=50)
