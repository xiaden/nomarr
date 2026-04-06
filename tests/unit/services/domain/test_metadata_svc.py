"""Tests for ``nomarr.services.domain.metadata_svc``."""

from __future__ import annotations

from unittest.mock import MagicMock, call

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
        ("collection", "expected_rel"),
        [
            ("artist", "artist"),
            ("album", "album"),
            ("label", "label"),
            ("genre", "genre"),
            ("year", "year"),
        ],
    )
    def test_uses_rel_mapped_from_collection(
        self,
        collection: EntityCollection,
        expected_rel: str,
    ) -> None:
        """Each singular collection should resolve to the correct rel query."""
        mock_db = MagicMock()
        mock_db.tags.list_tags_by_rel.return_value = []
        mock_db.tags.count_tags_by_rel.return_value = 0
        service = _make_service(db=mock_db)

        result = service.list_entities(collection)

        assert result == {
            "entities": [],
            "total": 0,
            "limit": 100,
            "offset": 0,
        }
        mock_db.tags.list_tags_by_rel.assert_called_once_with(
            expected_rel,
            limit=100,
            offset=0,
            search=None,
        )
        mock_db.tags.count_tags_by_rel.assert_called_once_with(expected_rel, search=None)

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_passes_through_limit_offset_and_search(self) -> None:
        """Explicit paging and search options should be forwarded to persistence."""
        mock_db = MagicMock()
        mock_db.tags.list_tags_by_rel.return_value = [
            {
                "_id": "tags/artist-1",
                "_key": "artist-1",
                "value": "The Artist",
                "song_count": 12,
            },
        ]
        mock_db.tags.count_tags_by_rel.return_value = 1
        service = _make_service(db=mock_db)

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
        mock_db.tags.list_tags_by_rel.assert_called_once_with(
            "artist",
            limit=10,
            offset=5,
            search="art",
        )
        mock_db.tags.count_tags_by_rel.assert_called_once_with("artist", search="art")


class TestGetEntity:
    """Tests for get_entity."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_none_when_tag_not_found(self) -> None:
        """Missing tags should surface as None."""
        mock_db = MagicMock()
        mock_db.tags.get_tag.return_value = None
        service = _make_service(db=mock_db)

        result = service.get_entity("tags/missing")

        assert result is None
        mock_db.tags.get_tag.assert_called_once_with("tags/missing")
        mock_db.tags.count_songs_for_tag.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_returns_entity_dict_when_tag_found(self) -> None:
        """Existing tags should be transformed into an entity dict."""
        mock_db = MagicMock()
        mock_db.tags.get_tag.return_value = {
            "_id": "tags/artist-1",
            "_key": "artist-1",
            "value": "The Artist",
        }
        mock_db.tags.count_songs_for_tag.return_value = 7
        service = _make_service(db=mock_db)

        result = service.get_entity("tags/artist-1")

        assert result == {
            "_id": "tags/artist-1",
            "_key": "artist-1",
            "display_name": "The Artist",
            "song_count": 7,
        }
        mock_db.tags.get_tag.assert_called_once_with("tags/artist-1")
        mock_db.tags.count_songs_for_tag.assert_called_once_with("tags/artist-1")


class TestGetEntityCounts:
    """Tests for get_entity_counts."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_calls_tags_persistence_for_all_singular_rels(self) -> None:
        """Entity counts should be derived from the tags persistence layer."""
        mock_db = MagicMock()
        counts_by_rel = {
            "artist": 11,
            "album": 22,
            "label": 33,
            "genre": 44,
            "year": 55,
        }
        mock_db.tags.count_tags_by_rel.side_effect = lambda rel: counts_by_rel[rel]
        service = _make_service(db=mock_db)

        result = service.get_entity_counts()

        assert result == {
            "artists": 11,
            "albums": 22,
            "labels": 33,
            "genres": 44,
            "years": 55,
        }
        mock_db.tags.count_tags_by_rel.assert_has_calls(
            [
                call("artist"),
                call("album"),
                call("label"),
                call("genre"),
                call("year"),
            ],
        )
        assert mock_db.tags.count_tags_by_rel.call_count == 5
