"""Unit tests for ``Database.register()`` template namespace behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.db import Database, _matches_name_pattern


class TestDatabaseRegister:
    """Direct unit tests for ``Database.register()``."""

    def _make_database(self) -> Database:
        """Construct a ``Database`` instance without connecting to ArangoDB."""
        db: Database = object.__new__(Database)
        db._template_namespaces = {}  # type: ignore[attr-defined]
        db.db = MagicMock()
        return db

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_success_stores_collection_and_sets_attribute(self) -> None:
        """``register()`` caches the builder-wired collection instance and exposes it as an attribute."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        class FakeVectorTemplate:
            NAME_PATTERN = "vectors_track_hot__{model}__{library}"

        with (
            patch.dict(
                "nomarr.persistence.db._VECTOR_TEMPLATE_CLASSES",
                {"vectors_track_hot": FakeVectorTemplate},
                clear=True,
            ),
            patch("nomarr.persistence.db.Builder") as mock_builder_cls,
        ):
            result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        mock_builder_cls.assert_called_once_with(database.db)
        mock_builder_cls.return_value.construct.assert_called_once_with(result)
        assert isinstance(result, FakeVectorTemplate)
        assert result._name == "vectors_track_hot__effnet__lib1"
        assert database._template_namespaces["vectors_track_hot__effnet__lib1"] is result
        assert database.__dict__["vectors_track_hot__effnet__lib1"] is result

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_idempotent_returns_cached_without_db_check(self) -> None:
        """Calling ``register()`` twice with the same name returns the cached namespace."""
        database = self._make_database()
        cached_ns = MagicMock()
        database._template_namespaces["vectors_track_hot__effnet__lib1"] = cached_ns

        result = database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

        assert result is cached_ns
        database.db.has_collection.assert_not_called()

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_collection_not_in_arango(self) -> None:
        """``register()`` raises ``ValueError`` when the ArangoDB collection does not exist."""
        database = self._make_database()
        database.db.has_collection.return_value = False

        with pytest.raises(ValueError, match="does not exist in ArangoDB"):
            database.register("vectors_track_hot__effnet__lib1", "vectors_track_hot")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_non_template_collection_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` is not a supported template."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            database.register("libraries__foo", "libraries")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_for_unknown_template_name(self) -> None:
        """``register()`` raises ``ValueError`` when ``template_name`` is not present in the template registry."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="is not a supported template collection"):
            database.register("nonexistent__foo", "nonexistent_template")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_register_raises_when_vector_template_name_does_not_match_pattern(self) -> None:
        """``register()`` raises ``ValueError`` when a vector template name mismatches its ``NAME_PATTERN``."""
        database = self._make_database()
        database.db.has_collection.return_value = True

        with pytest.raises(ValueError, match="does not match template pattern"):
            database.register("vectors_track_hot__bad", "vectors_track_hot")


class TestDatabaseGetVersion:
    """Direct unit tests for ``Database.get_version()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_string_value_from_meta_doc(self) -> None:
        """``get_version()`` returns the stored version string when present."""
        database: Database = object.__new__(Database)
        database.meta = MagicMock()
        database.meta.get.return_value = {"value": "0.28.0"}

        result = database.get_version()

        assert result == "0.28.0"
        database.meta.get.assert_called_once_with(key="version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_none_when_meta_doc_is_not_dict(self) -> None:
        """``get_version()`` returns ``None`` when meta storage returns a non-dict."""
        database: Database = object.__new__(Database)
        database.meta = MagicMock()
        database.meta.get.return_value = None

        result = database.get_version()

        assert result is None
        database.meta.get.assert_called_once_with(key="version")

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_get_version_returns_none_when_value_is_not_string(self) -> None:
        """``get_version()`` returns ``None`` when the stored value is not a string."""
        database: Database = object.__new__(Database)
        database.meta = MagicMock()
        database.meta.get.return_value = {"value": 28}

        result = database.get_version()

        assert result is None
        database.meta.get.assert_called_once_with(key="version")


class TestDatabaseSetVersion:
    """Direct unit tests for ``Database.set_version()``."""

    @pytest.mark.unit
    @pytest.mark.mocked
    def test_set_version_upserts_version_doc(self) -> None:
        """``set_version()`` writes the schema version to ``meta`` via ``upsert()``."""
        database: Database = object.__new__(Database)
        database.meta = MagicMock()

        database.set_version("0.28.0")

        database.meta.upsert.assert_called_once_with(key="version", fields={"value": "0.28.0"})


class TestMatchesNamePattern:
    """Unit tests for ``_matches_name_pattern()``."""

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("resolved_name", "name_pattern", "expected"),
        [
            pytest.param("foo__bar", "foo__bar", True, id="exact-static-match"),
            pytest.param(
                "vectors_track_hot__effnet__lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                True,
                id="single-placeholder-match",
            ),
            pytest.param(
                "vectors_track_hot__bad",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="wrong-number-of-parts",
            ),
            pytest.param(
                "vectors_track_hot____lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="empty-placeholder-segment",
            ),
            pytest.param(
                "vectors_track_cold__effnet__lib1",
                "vectors_track_hot__{backbone_id}__{library_key}",
                False,
                id="static-part-mismatch",
            ),
        ],
    )
    def test_matches_name_pattern(
        self,
        resolved_name: str,
        name_pattern: str,
        expected: bool,
    ) -> None:
        """``_matches_name_pattern()`` compares static segments and placeholder segments correctly."""
        result = _matches_name_pattern(resolved_name, name_pattern)

        assert result is expected
