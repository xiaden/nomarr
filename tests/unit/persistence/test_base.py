"""Tests for persistence base types and collection base classes."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest

from nomarr.persistence.accessors import FieldAccessor
from nomarr.persistence.base_types import (
    CASCADE,
    DETACH,
    INBOUND,
    OUTBOUND,
    EdgeDef,
    Field,
    UniqueField,
    _normalize_field_criteria,
    collection_name_for_class,
)
from nomarr.persistence.collections_base import (
    DocumentCollection,
    EdgeCollection,
    StateGraphCollection,
    VectorCollection,
)


@pytest.mark.unit
class TestFieldAndCriteria:
    """Tests for persistence field criteria helpers."""

    def test_field_is_frozen_dataclass(self) -> None:
        field = Field("status", "active")

        assert is_dataclass(Field)
        assert field.name == "status"
        assert field.value == "active"

        with pytest.raises(FrozenInstanceError):
            field.__setattr__("name", "inactive")

    def test_field_and_uniquefield_subscription_are_runtime_noops(self) -> None:
        assert Field.__class_getitem__(str) is str
        assert UniqueField.__class_getitem__(int) is int

    def test_normalize_field_criteria_accepts_positional_fields(self) -> None:
        criteria = _normalize_field_criteria((Field("status", "ready"), Field("attempts", 2)), {})

        assert criteria == {"status": "ready", "attempts": 2}

    def test_normalize_field_criteria_accepts_keyword_fields(self) -> None:
        criteria = _normalize_field_criteria((), {"status": "ready", "attempts": 2})

        assert criteria == {"status": "ready", "attempts": 2}

    def test_normalize_field_criteria_rejects_mixed_styles(self) -> None:
        with pytest.raises(ValueError, match="Do not mix positional"):
            _normalize_field_criteria((Field("status", "ready"),), {"attempts": 2})

    def test_normalize_field_criteria_rejects_duplicates(self) -> None:
        with pytest.raises(ValueError, match="Duplicate field criterion"):
            _normalize_field_criteria((Field("status", "ready"), Field("status", "done")), {})


@pytest.mark.unit
class TestConstantsAndNames:
    """Tests for public constants and collection name helpers."""

    def test_constant_values_match_expected_literals(self) -> None:
        assert INBOUND == "INBOUND"
        assert OUTBOUND == "OUTBOUND"
        assert CASCADE == "CASCADE"
        assert DETACH == "DETACH"

    def test_collection_name_uses_declared_name_when_present(self) -> None:
        class DeclaredCollection(DocumentCollection):
            _name = "declared_name"

        assert collection_name_for_class(DeclaredCollection) == "declared_name"

    def test_collection_name_falls_back_to_snake_case(self) -> None:
        class CamelCaseCollection(DocumentCollection):
            pass

        assert collection_name_for_class(CamelCaseCollection) == "camel_case_collection"


@pytest.mark.unit
class TestEdgeDef:
    """Tests for the edge declaration dataclass."""

    def test_is_frozen_dataclass(self) -> None:
        assert is_dataclass(EdgeDef)

    def test_stores_constructor_values(self) -> None:
        class Artists(DocumentCollection):
            _name = "artists"

        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"

        edge_def = EdgeDef(
            via=ArtistAlbumEdges,
            direction=OUTBOUND,
            target=Albums,
            on_delete=DETACH,
        )

        assert edge_def.via is ArtistAlbumEdges
        assert edge_def.direction == OUTBOUND
        assert edge_def.target is Albums
        assert edge_def.on_delete == DETACH

        with pytest.raises(FrozenInstanceError):
            edge_def.__setattr__("on_delete", CASCADE)


@pytest.mark.unit
class TestCollectionBases:
    """Tests for instance-bound collection base classes."""

    def test_document_collection_registers_default_fields_and_traversal(self) -> None:
        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"

        class Artists(DocumentCollection):
            pass

        Artists.EDGES = [EdgeDef(via=ArtistAlbumEdges, direction=OUTBOUND, target=Albums, on_delete=CASCADE)]

        safe_db = MagicMock()
        artists = Artists(safe_db, "artists")

        assert isinstance(artists._key, FieldAccessor)
        assert isinstance(artists._id, FieldAccessor)
        assert isinstance(artists._rev, FieldAccessor)
        assert set(artists._fields) >= {"_key", "_id", "_rev"}
        traversal = cast("Any", artists).artist_album_edges
        assert callable(traversal)

        with patch(
            "nomarr.persistence.constructor.verbs.traversal_by_id", return_value=[{"_id": "albums/1"}]
        ) as traversal_mock:
            result = traversal("artists/1", limit=2, offset=3)

        assert result == [{"_id": "albums/1"}]
        traversal_mock.assert_called_once_with(
            safe_db,
            "artists",
            "artists/1",
            "artist_album_edges",
            OUTBOUND,
            limit=2,
            offset=3,
        )

    def test_edge_collection_registers_edge_fields(self) -> None:
        class FileHasState(EdgeCollection):
            _name = "file_has_state"

        safe_db = MagicMock()
        edges = FileHasState(safe_db, "file_has_state")

        assert isinstance(edges._key, FieldAccessor)
        assert isinstance(edges._id, FieldAccessor)
        assert isinstance(edges._from, FieldAccessor)
        assert isinstance(edges._to, FieldAccessor)
        assert set(edges._fields) >= {"_key", "_id", "_from", "_to"}

    def test_vector_collection_registers_vector_fields(self) -> None:
        class Embeddings(VectorCollection):
            VECTOR_TIER = "hot"
            NAME_PATTERN = "embeddings__{library}"

        safe_db = MagicMock()
        vectors = Embeddings(safe_db, "embeddings__lib1")

        assert isinstance(vectors._key, FieldAccessor)
        assert isinstance(vectors._id, FieldAccessor)
        assert isinstance(vectors.file_id, FieldAccessor)
        assert isinstance(vectors.vector, FieldAccessor)
        assert set(vectors._fields) >= {"_key", "_id", "file_id", "vector"}

    def test_state_graph_collection_stores_edge_name_and_delegates_transition(self) -> None:
        safe_db = MagicMock()
        state_graph = StateGraphCollection(safe_db, "file_states", "file_has_state")

        assert isinstance(state_graph, DocumentCollection)
        assert state_graph._edge_name == "file_has_state"

        with patch("nomarr.persistence.constructor.verbs.transition") as transition_mock:
            state_graph.transition(["library_files/1"], "queued", "processed")

        transition_mock.assert_called_once_with(
            safe_db,
            "file_has_state",
            ["library_files/1"],
            "queued",
            "processed",
        )
