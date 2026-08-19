"""Tests for the persistence-layer tag row<->domain mappers.

These pin the boundary contracts from
``artifacts/designs/parts/tag-boundary/CONTRACTS.md``: row-to-domain grouping,
value-order preservation, empty-row behavior, domain rejection of
persistence-only fields, and the write-payload row shape.
"""

from __future__ import annotations

import pytest

from nomarr.helpers.dataclasses.tags_dataclass import Tag, Tags
from nomarr.persistence.mappers.tag_mapper import tag_rows_from_tags, tags_from_tag_rows


class TestTagsFromTagRows:
    def test_groups_rows_by_name(self) -> None:
        rows = [
            {"name": "artist", "value": "x"},
            {"name": "genre", "value": "rock"},
            {"name": "genre", "value": "pop"},
        ]
        result = tags_from_tag_rows(rows)
        assert result.to_dict() == {"artist": ("x",), "genre": ("rock", "pop")}

    def test_preserves_value_order(self) -> None:
        rows = [
            {"name": "genre", "value": "pop"},
            {"name": "genre", "value": "rock"},
            {"name": "genre", "value": "jazz"},
        ]
        result = tags_from_tag_rows(rows)
        assert result.get_values("genre") == ("pop", "rock", "jazz")

    def test_empty_rows_raise_value_error(self) -> None:
        with pytest.raises(ValueError, match="at least one tag"):
            tags_from_tag_rows([])

    def test_ignores_persistence_only_fields(self) -> None:
        rows = [
            {
                "name": "genre",
                "value": "rock",
                "id": 1,
                "namespace": "nom",
                "source": "curation",
                "confidence": 0.9,
                "tier": 2,
                "created_at": 1,
                "updated_at": 2,
            },
        ]
        result = tags_from_tag_rows(rows)
        tag = result.items[0]
        assert not hasattr(tag, "namespace")
        assert not hasattr(tag, "source")
        assert not hasattr(tag, "id")
        assert tag.name == "genre"
        assert tag.values == ("rock",)

    def test_accepts_tag_row_shaped_dicts(self) -> None:
        rows = [
            {"name": "tempo", "value": 120, "id": 10, "namespace": "nom"},
            {"name": "year", "value": 2020, "id": 11, "namespace": ""},
        ]
        result = tags_from_tag_rows(rows)
        assert result.to_dict() == {"tempo": (120,), "year": (2020,)}

    def test_produces_canonical_domain_instances(self) -> None:
        result = tags_from_tag_rows([{"name": "genre", "value": "rock"}])
        assert isinstance(result, Tags)
        assert isinstance(result.items[0], Tag)
        assert result.items[0].name == "genre"
        assert result.items[0].values == ("rock",)


class TestTagRowsFromTags:
    def test_one_row_per_value(self) -> None:
        tags = tags_from_tag_rows(
            [{"name": "genre", "value": "rock"}, {"name": "genre", "value": "pop"}]
        )
        rows = tag_rows_from_tags(tags, namespace="nom", source="curation")
        assert rows == [
            {"name": "genre", "value": "rock", "namespace": "nom", "source": "curation"},
            {"name": "genre", "value": "pop", "namespace": "nom", "source": "curation"},
        ]

    def test_multiple_tags_are_ordered(self) -> None:
        tags = tags_from_tag_rows(
            [
                {"name": "artist", "value": "x"},
                {"name": "genre", "value": "rock"},
            ]
        )
        rows = tag_rows_from_tags(tags, namespace="", source="s")
        assert [r["name"] for r in rows] == ["artist", "genre"]

    def test_applies_namespace_and_source_keywords(self) -> None:
        tags = tags_from_tag_rows([{"name": "mood", "value": "calm"}])
        rows = tag_rows_from_tags(tags, namespace="nom", source="ml")
        assert rows == [
            {"name": "mood", "value": "calm", "namespace": "nom", "source": "ml"},
        ]

    def test_does_not_mutate_domain_tags(self) -> None:
        tags = tags_from_tag_rows([{"name": "genre", "value": "rock"}])
        before = tags.to_dict()
        tag_rows_from_tags(tags, namespace="nom", source="curation")
        assert tags.to_dict() == before
