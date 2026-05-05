"""Tests for typed persistence base collection declarations."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from typing import Annotated, ClassVar, get_args, get_origin, get_type_hints

import pytest

import nomarr.persistence.base as base
from nomarr.persistence.base import (
    CASCADE,
    DETACH,
    INBOUND,
    OUTBOUND,
    DocumentCollection,
    EdgeCollection,
    EdgeDef,
    Field,
    FieldMarker,
    StateGraphCollection,
    UniqueField,
    VectorCollection,
)


@pytest.mark.unit
class TestFieldMarker:
    """Tests for FieldMarker."""

    def test_is_frozen_dataclass(self) -> None:
        """FieldMarker is implemented as a frozen dataclass."""
        assert is_dataclass(FieldMarker)

    def test_unique_true_stores_true(self) -> None:
        """FieldMarker stores a True unique flag."""
        marker = FieldMarker(unique=True)

        assert marker.unique is True

    def test_unique_false_stores_false(self) -> None:
        """FieldMarker stores a False unique flag."""
        marker = FieldMarker(unique=False)

        assert marker.unique is False

    def test_is_immutable(self) -> None:
        """FieldMarker instances cannot be mutated."""
        marker = FieldMarker(unique=False)

        with pytest.raises(FrozenInstanceError):
            marker.__setattr__("unique", True)


@pytest.mark.unit
class TestField:
    """Tests for Field annotations."""

    def test_returns_annotated_str_with_non_unique_marker(self) -> None:
        """Field[str] resolves to Annotated[str, FieldMarker(unique=False)]."""
        annotation = Field.__class_getitem__(str)
        marker = get_args(annotation)[1]

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[0] is str
        assert marker == FieldMarker(unique=False)

    def test_returns_annotated_int_with_non_unique_marker(self) -> None:
        """Field[int] resolves to Annotated[int, FieldMarker(unique=False)]."""
        annotation = Field.__class_getitem__(int)
        marker = get_args(annotation)[1]

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[0] is int
        assert marker == FieldMarker(unique=False)

    def test_marker_has_unique_false(self) -> None:
        """Field annotations always attach a non-unique marker."""
        marker = get_args(Field.__class_getitem__(str))[1]

        assert isinstance(marker, FieldMarker)
        assert marker.unique is False


@pytest.mark.unit
class TestUniqueField:
    """Tests for UniqueField annotations."""

    def test_returns_annotated_str_with_unique_marker(self) -> None:
        """UniqueField[str] resolves to Annotated[str, FieldMarker(unique=True)]."""
        annotation = UniqueField.__class_getitem__(str)
        marker = get_args(annotation)[1]

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[0] is str
        assert marker == FieldMarker(unique=True)

    def test_marker_has_unique_true(self) -> None:
        """UniqueField annotations always attach a unique marker."""
        marker = get_args(UniqueField.__class_getitem__(str))[1]

        assert isinstance(marker, FieldMarker)
        assert marker.unique is True


@pytest.mark.unit
class TestFieldDataclass:
    """Tests for Field runtime instances and UniqueField instantiation guards."""

    def test_field_is_dataclass_with_name_and_value(self) -> None:
        """Field is a dataclass that stores the provided name and value."""
        field = Field("status", "active")

        assert is_dataclass(Field)
        assert field.name == "status"
        assert field.value == "active"

    def test_field_instance_stores_name_and_value(self) -> None:
        """Field instances preserve the supplied runtime filter payload."""
        field = Field("genre", "rock")

        assert field.name == "genre"
        assert field.value == "rock"

    def test_field_instance_is_frozen(self) -> None:
        """Field instances are immutable once created."""
        field = Field("status", "active")

        with pytest.raises(FrozenInstanceError):
            field.__setattr__("name", "inactive")

    def test_unique_field_instantiation_raises_type_error(self) -> None:
        """UniqueField cannot be instantiated directly."""
        with pytest.raises(TypeError, match="only for type annotations"):
            UniqueField()


@pytest.mark.unit
class TestConstants:
    """Tests for direction and deletion constants."""

    def test_constant_values_match_expected_literals(self) -> None:
        """Public constants expose the expected string values."""
        assert INBOUND == "INBOUND"
        assert OUTBOUND == "OUTBOUND"
        assert CASCADE == "CASCADE"
        assert DETACH == "DETACH"


@pytest.mark.unit
class TestDocumentCollection:
    """Tests for DocumentCollection."""

    def test_has_classvar_annotations_and_empty_edges_default(self) -> None:
        """DocumentCollection declares class variables and defaults EDGES to an empty list."""
        hints = get_type_hints(DocumentCollection, include_extras=True)

        assert get_origin(hints["_name"]) is ClassVar
        assert get_args(hints["_name"]) == (str,)
        assert get_origin(hints["EDGES"]) is ClassVar
        assert DocumentCollection.EDGES == []

    def test_subclass_can_declare_edges_with_edge_defs(self) -> None:
        """DocumentCollection subclasses can define typed edge declarations."""

        class Artists(DocumentCollection):
            _name = "artists"

        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"
            FROM_COLLECTION = Artists
            TO_COLLECTION = Albums

        edge_def = EdgeDef(
            via=ArtistAlbumEdges,
            direction=OUTBOUND,
            target=Albums,
            on_delete=CASCADE,
        )

        class ArtistGraph(DocumentCollection):
            _name = "artist_graph"
            EDGES: ClassVar[list[EdgeDef]] = [edge_def]

        assert [edge_def] == ArtistGraph.EDGES
        assert ArtistGraph.EDGES[0].via is ArtistAlbumEdges
        assert ArtistGraph.EDGES[0].target is Albums


@pytest.mark.unit
class TestStateGraphCollection:
    """Tests for StateGraphCollection."""

    def test_is_subclass_of_document_collection(self) -> None:
        """StateGraphCollection extends DocumentCollection."""
        assert issubclass(StateGraphCollection, DocumentCollection)

    def test_inherits_edges_default(self) -> None:
        """StateGraphCollection inherits the base EDGES default."""
        assert StateGraphCollection.EDGES == []
        assert StateGraphCollection.EDGES is DocumentCollection.EDGES


@pytest.mark.unit
class TestEdgeCollection:
    """Tests for EdgeCollection."""

    def test_has_classvar_annotations(self) -> None:
        """EdgeCollection declares expected class variables."""
        hints = get_type_hints(EdgeCollection, include_extras=True)

        assert get_origin(hints["_name"]) is ClassVar
        assert get_origin(hints["FROM_COLLECTION"]) is ClassVar
        assert get_origin(hints["TO_COLLECTION"]) is ClassVar

    def test_subclass_can_declare_name_and_endpoint_collections(self) -> None:
        """EdgeCollection subclasses can define their required collection references."""

        class Artists(DocumentCollection):
            _name = "artists"

        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"
            FROM_COLLECTION = Artists
            TO_COLLECTION = Albums

        assert ArtistAlbumEdges._name == "artist_album_edges"
        assert ArtistAlbumEdges.FROM_COLLECTION is Artists
        assert ArtistAlbumEdges.TO_COLLECTION is Albums


@pytest.mark.unit
class TestVectorCollection:
    """Tests for VectorCollection."""

    def test_has_classvar_annotations(self) -> None:
        """VectorCollection declares expected class variables."""
        hints = get_type_hints(VectorCollection, include_extras=True)

        assert get_origin(hints["_name"]) is ClassVar
        assert get_origin(hints["VECTOR_TIER"]) is ClassVar
        assert get_origin(hints["NAME_PATTERN"]) is ClassVar

    def test_subclass_can_declare_name_tier_and_pattern(self) -> None:
        """VectorCollection subclasses can define all required metadata."""

        class Embeddings(VectorCollection):
            _name = "embeddings"
            VECTOR_TIER = "hot"
            NAME_PATTERN = "embeddings_{tier}__{lib}"

        assert Embeddings._name == "embeddings"
        assert Embeddings.VECTOR_TIER == "hot"
        assert Embeddings.NAME_PATTERN == "embeddings_{tier}__{lib}"


@pytest.mark.unit
class TestEdgeDef:
    """Tests for EdgeDef."""

    def test_is_frozen_dataclass(self) -> None:
        """EdgeDef is implemented as a frozen dataclass."""
        assert is_dataclass(EdgeDef)

    def test_stores_constructor_values(self) -> None:
        """EdgeDef stores via, direction, target, and on_delete values."""

        class Artists(DocumentCollection):
            _name = "artists"

        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"
            FROM_COLLECTION = Artists
            TO_COLLECTION = Albums

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

    def test_is_immutable(self) -> None:
        """EdgeDef instances cannot be mutated."""

        class Artists(DocumentCollection):
            _name = "artists"

        class Albums(DocumentCollection):
            _name = "albums"

        class ArtistAlbumEdges(EdgeCollection):
            _name = "artist_album_edges"
            FROM_COLLECTION = Artists
            TO_COLLECTION = Albums

        edge_def = EdgeDef(
            via=ArtistAlbumEdges,
            direction=INBOUND,
            target=Artists,
            on_delete=CASCADE,
        )

        with pytest.raises(FrozenInstanceError):
            edge_def.__setattr__("on_delete", DETACH)

    def test_accepts_vector_collection_as_target(self) -> None:
        """EdgeDef accepts a VectorCollection subclass as target."""

        class Artists(DocumentCollection):
            _name = "artists"

        class ArtistEmbeddings(VectorCollection):
            _name = "artist_embeddings"
            VECTOR_TIER = "hot"
            NAME_PATTERN = "artist_embeddings_{tier}__{lib}"

        class ArtistEmbeddingEdges(EdgeCollection):
            _name = "artist_embedding_edges"
            FROM_COLLECTION = Artists
            TO_COLLECTION = Artists

        edge_def = EdgeDef(
            via=ArtistEmbeddingEdges,
            direction=OUTBOUND,
            target=ArtistEmbeddings,
            on_delete=DETACH,
        )

        assert edge_def.target is ArtistEmbeddings


@pytest.mark.unit
class TestAllExports:
    """Tests for module exports."""

    def test_exports_expected_public_names(self) -> None:
        """__all__ exposes the full supported public API."""
        assert base.__all__ == [
            "CASCADE",
            "DETACH",
            "INBOUND",
            "OUTBOUND",
            "DocumentCollection",
            "EdgeCollection",
            "EdgeDef",
            "Field",
            "FieldMarker",
            "StateGraphCollection",
            "UniqueField",
            "VectorCollection",
        ]


@pytest.mark.unit
class TestFieldAnnotationInternals:
    """Direct tests for Field/UniqueField subscription machinery."""

    def test_field_subscription_syntax_returns_non_unique_annotation(self) -> None:
        """Field[str] uses Field.__class_getitem__ to attach a non-unique marker."""
        annotation = Field[str]
        marker = get_args(annotation)[1]

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[0] is str
        assert marker == FieldMarker(unique=False)

    def test_field_annotation_base_cannot_be_instantiated(self) -> None:
        """_FieldAnnotation is annotation-only and rejects direct instantiation."""
        with pytest.raises(TypeError, match="only for type annotations"):
            base._FieldAnnotation()

    def test_unique_field_subscription_syntax_returns_unique_annotation(self) -> None:
        """UniqueField[str] uses _FieldAnnotation.__class_getitem__ with a unique marker."""
        annotation = UniqueField[str]
        marker = get_args(annotation)[1]

        assert get_origin(annotation) is Annotated
        assert get_args(annotation)[0] is str
        assert marker == FieldMarker(unique=True)
