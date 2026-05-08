"""Unit tests for persistence accessor dispatch helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.accessors import CollectionDelete, CollectionGet, FieldAccessor
from nomarr.persistence.base_types import Field


@pytest.mark.unit
@pytest.mark.mocked
class TestFieldAccessor:
    """Tests for ``FieldAccessor``."""

    def test_constructor_builds_field_specific_get_and_delete_helpers(self) -> None:
        safe_db = MagicMock()
        accessor = FieldAccessor(safe_db, "library_files", "path", unique=True)

        assert accessor._db is safe_db
        assert accessor._collection == "library_files"
        assert accessor._field == "path"
        assert accessor._unique is True
        assert accessor.get._field == "path"
        assert accessor.delete._field == "path"

    def test_upsert_merges_lookup_field_into_document(self) -> None:
        safe_db = MagicMock()
        accessor = FieldAccessor(safe_db, "library_files", "path")

        with patch("nomarr.persistence.accessors.verbs.upsert_by_field", return_value=["doc-1"]) as upsert_mock:
            result = accessor.upsert("song.flac", {"size": 123})

        assert result == ["doc-1"]
        upsert_mock.assert_called_once_with(
            safe_db,
            "library_files",
            "path",
            [{"path": "song.flac", "size": 123}],
        )

    def test_count_inbound_connections_uses_bound_field(self) -> None:
        safe_db = MagicMock()
        accessor = FieldAccessor(safe_db, "tags", "name")

        with patch(
            "nomarr.persistence.accessors.verbs.count_inbound_connections",
            return_value=[{"tag": "Rock", "count": 4}],
        ) as inbound_mock:
            result = accessor.count_inbound_connections(
                "song_has_tags",
                ["genre"],
                return_field="value",
                label="tag",
                limit=3,
                offset=2,
            )

        assert result == [{"tag": "Rock", "count": 4}]
        inbound_mock.assert_called_once_with(
            safe_db,
            "tags",
            "song_has_tags",
            "name",
            ["genre"],
            return_field="value",
            label="tag",
            limit=3,
            offset=2,
        )

    def test_count_outbound_connections_uses_bound_field(self) -> None:
        safe_db = MagicMock()
        accessor = FieldAccessor(safe_db, "library_files", "_id")

        with patch(
            "nomarr.persistence.accessors.verbs.count_outbound_connections",
            return_value=[{"song_id": "library_files/1", "count": 7}],
        ) as outbound_mock:
            result = accessor.count_outbound_connections("song_has_tags", ["library_files/1"], label="song_id")

        assert result == [{"song_id": "library_files/1", "count": 7}]
        outbound_mock.assert_called_once_with(
            safe_db,
            "library_files",
            "song_has_tags",
            "_id",
            ["library_files/1"],
            return_field="_id",
            label="song_id",
            limit=None,
            offset=0,
        )


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionGet:
    """Tests for ``CollectionGet`` dispatch behavior."""

    def test_no_criteria_calls_get_many_by_filter_with_empty_dict(self) -> None:
        safe_db = MagicMock()
        collection_get = CollectionGet(safe_db, "docs", {})

        with patch(
            "nomarr.persistence.accessors.verbs.get_many_by_filter", return_value=[{"_key": "1"}]
        ) as get_many_mock:
            result = collection_get(limit=5, offset=2)

        assert result == [{"_key": "1"}]
        get_many_mock.assert_called_once_with(safe_db, "docs", {}, limit=5, offset=2)

    def test_single_known_field_delegates_to_bound_field_accessor_get(self) -> None:
        safe_db = MagicMock()
        accessor = MagicMock()
        accessor.get = MagicMock(return_value={"_key": "doc-1"})
        accessor.get.many = MagicMock()
        collection_get = CollectionGet(safe_db, "docs", {"slug": accessor})

        result = collection_get(slug="alpha")

        assert result == {"_key": "doc-1"}
        accessor.get.assert_called_once_with("alpha")
        accessor.get.many.assert_not_called()

    def test_single_known_field_with_limit_uses_accessor_many(self) -> None:
        safe_db = MagicMock()
        accessor = MagicMock()
        accessor.get = MagicMock()
        accessor.get.many = MagicMock(return_value=[{"_key": "doc-2"}])
        collection_get = CollectionGet(safe_db, "docs", {"slug": accessor})

        result = collection_get(slug="alpha", limit=10, offset=3)

        assert result == [{"_key": "doc-2"}]
        accessor.get.assert_not_called()
        accessor.get.many.assert_called_once_with("alpha", limit=10, offset=3)

    def test_single_unknown_field_calls_get_many_by_field(self) -> None:
        safe_db = MagicMock()
        collection_get = CollectionGet(safe_db, "docs", {})

        with patch(
            "nomarr.persistence.accessors.verbs.get_many_by_field", return_value=[{"_key": "doc-3"}]
        ) as get_many_by_field_mock:
            result = collection_get(slug="beta", limit=4, offset=1)

        assert result == [{"_key": "doc-3"}]
        get_many_by_field_mock.assert_called_once_with(
            safe_db,
            "docs",
            "slug",
            "beta",
            limit=4,
            offset=1,
        )

    def test_multiple_fields_calls_get_many_by_filter(self) -> None:
        safe_db = MagicMock()
        collection_get = CollectionGet(safe_db, "docs", {})

        with patch(
            "nomarr.persistence.accessors.verbs.get_many_by_filter", return_value=[{"_key": "doc-4"}]
        ) as get_many_mock:
            result = collection_get(slug="beta", status="ready", limit=7, offset=6)

        assert result == [{"_key": "doc-4"}]
        get_many_mock.assert_called_once_with(
            safe_db,
            "docs",
            {"slug": "beta", "status": "ready"},
            limit=7,
            offset=6,
        )

    def test_in_uses_known_field_accessor_when_available(self) -> None:
        safe_db = MagicMock()
        accessor = MagicMock()
        accessor.get = MagicMock()
        accessor.get.in_ = MagicMock(return_value=[{"_key": "doc-5"}])
        collection_get = CollectionGet(safe_db, "docs", {"slug": accessor})

        result = collection_get.in_(Field("slug", ["a", "b"]), limit=8, offset=2)

        assert result == [{"_key": "doc-5"}]
        accessor.get.in_.assert_called_once_with(["a", "b"], limit=8, offset=2)

    def test_in_requires_exactly_one_criterion(self) -> None:
        collection_get = CollectionGet(MagicMock(), "docs", {})

        with pytest.raises(ValueError, match="exactly one criterion"):
            collection_get.in_(Field("slug", ["a"]), Field("status", ["ready"]))


@pytest.mark.unit
@pytest.mark.mocked
class TestCollectionDelete:
    """Tests for ``CollectionDelete`` dispatch behavior."""

    def test_no_criteria_calls_truncate_and_returns_zero(self) -> None:
        safe_db = MagicMock()
        collection_delete = CollectionDelete(safe_db, "docs")

        with patch("nomarr.persistence.accessors.verbs.truncate") as truncate_mock:
            result = collection_delete()

        assert result == 0
        truncate_mock.assert_called_once_with(safe_db, "docs")

    def test_single_field_calls_delete_by_field(self) -> None:
        safe_db = MagicMock()
        collection_delete = CollectionDelete(safe_db, "docs")

        with patch("nomarr.persistence.accessors.verbs.delete_by_field", return_value=3) as delete_by_field_mock:
            result = collection_delete(slug="alpha")

        assert result == 3
        delete_by_field_mock.assert_called_once_with(safe_db, "docs", "slug", "alpha")

    def test_multiple_fields_calls_delete_by_filter(self) -> None:
        safe_db = MagicMock()
        collection_delete = CollectionDelete(safe_db, "docs")

        with patch("nomarr.persistence.accessors.verbs.delete_by_filter", return_value=5) as delete_by_filter_mock:
            result = collection_delete(slug="alpha", status="ready")

        assert result == 5
        delete_by_filter_mock.assert_called_once_with(
            safe_db,
            "docs",
            {"slug": "alpha", "status": "ready"},
        )

    def test_in_calls_delete_in_by_field(self) -> None:
        safe_db = MagicMock()
        collection_delete = CollectionDelete(safe_db, "docs")

        with patch("nomarr.persistence.accessors.verbs.delete_in_by_field", return_value=2) as delete_in_mock:
            result = collection_delete.in_(Field("slug", ["a", "b"]))

        assert result == 2
        delete_in_mock.assert_called_once_with(safe_db, "docs", "slug", ["a", "b"])

    def test_in_requires_exactly_one_criterion(self) -> None:
        collection_delete = CollectionDelete(MagicMock(), "docs")

        with pytest.raises(ValueError, match="exactly one criterion"):
            collection_delete.in_(Field("slug", ["a"]), Field("status", ["ready"]))

    def test_unreferenced_calls_delete_unreferenced(self) -> None:
        safe_db = MagicMock()
        collection_delete = CollectionDelete(safe_db, "docs")

        with patch(
            "nomarr.persistence.accessors.verbs.delete_unreferenced", return_value=4
        ) as delete_unreferenced_mock:
            result = collection_delete.unreferenced("doc_edges")

        assert result == 4
        delete_unreferenced_mock.assert_called_once_with(safe_db, "docs", "doc_edges")

    def test_cascade_property_defaults_to_none(self) -> None:
        collection_delete = CollectionDelete(MagicMock(), "docs")

        assert collection_delete.cascade is None
