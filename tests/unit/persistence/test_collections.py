"""Tests for typed persistence collection declarations."""

from __future__ import annotations

from typing import get_args, get_type_hints

import pytest

from nomarr.persistence.base import (
    CASCADE,
    DETACH,
    DocumentCollection,
    EdgeCollection,
    EdgeDef,
    FieldMarker,
    StateGraphCollection,
    VectorCollection,
)
from nomarr.persistence.collections import (
    CalibrationHistory,
    CalibrationState,
    FileHasSegmentStats,
    FileHasState,
    FileHasVectors,
    FileStates,
    HasNdId,
    HasPlays,
    Health,
    Libraries,
    LibraryContainsFile,
    LibraryContainsFolder,
    LibraryFiles,
    LibraryFolders,
    LibraryHasPipelineState,
    LibraryHasScan,
    LibraryPipelineStates,
    LibraryScans,
    Locks,
    Meta,
    Migrations,
    MlCapacity,
    MlModelOutputs,
    MlModels,
    ModelHasCalibration,
    ModelHasOutput,
    NavidromePlaycounts,
    NavidromeTracks,
    SegmentScoresStats,
    Sessions,
    SongHasTags,
    TagModelOutput,
    Tags,
    VectorsTrackCold,
    VectorsTrackHot,
    VramPromises,
    WorkerClaims,
    WorkerRestartPolicy,
    __all__,
)

EXPECTED_ALL = [
    "CalibrationHistory",
    "CalibrationState",
    "FileHasSegmentStats",
    "FileHasState",
    "FileHasVectors",
    "FileStates",
    "HasNdId",
    "HasPlays",
    "Health",
    "Libraries",
    "LibraryContainsFile",
    "LibraryContainsFolder",
    "LibraryFiles",
    "LibraryFolders",
    "LibraryHasPipelineState",
    "LibraryHasScan",
    "LibraryPipelineStates",
    "LibraryScans",
    "Locks",
    "Meta",
    "Migrations",
    "MlCapacity",
    "MlModelOutputs",
    "MlModels",
    "ModelHasCalibration",
    "ModelHasOutput",
    "NavidromePlaycounts",
    "NavidromeTracks",
    "SegmentScoresStats",
    "Sessions",
    "SongHasTags",
    "TagModelOutput",
    "Tags",
    "VectorsTrackCold",
    "VectorsTrackHot",
    "VramPromises",
    "WorkerClaims",
    "WorkerRestartPolicy",
]

DOCUMENT_COLLECTION_CLASSES = [
    Meta,
    Migrations,
    Health,
    Sessions,
    Locks,
    VramPromises,
    WorkerClaims,
    WorkerRestartPolicy,
    MlCapacity,
    LibraryPipelineStates,
    LibraryScans,
    LibraryFolders,
    Libraries,
    LibraryFiles,
    Tags,
    FileStates,
    CalibrationState,
    CalibrationHistory,
    MlModels,
    MlModelOutputs,
    NavidromeTracks,
    NavidromePlaycounts,
    SegmentScoresStats,
]

DIRECT_DOCUMENT_COLLECTION_CLASSES = [
    Meta,
    Migrations,
    Health,
    Sessions,
    Locks,
    VramPromises,
    WorkerClaims,
    WorkerRestartPolicy,
    MlCapacity,
    LibraryPipelineStates,
    LibraryScans,
    LibraryFolders,
    Libraries,
    LibraryFiles,
    Tags,
    CalibrationState,
    CalibrationHistory,
    MlModels,
    MlModelOutputs,
    NavidromeTracks,
    NavidromePlaycounts,
    SegmentScoresStats,
]

EDGE_COLLECTION_CLASSES = [
    SongHasTags,
    FileHasState,
    TagModelOutput,
    LibraryContainsFile,
    LibraryContainsFolder,
    LibraryHasScan,
    FileHasVectors,
    FileHasSegmentStats,
    ModelHasOutput,
    ModelHasCalibration,
    LibraryHasPipelineState,
    HasNdId,
    HasPlays,
]

VECTOR_COLLECTION_CLASSES = [VectorsTrackHot, VectorsTrackCold]


@pytest.mark.unit
class TestModuleExports:
    """Tests for module export declarations."""

    def test_all_contains_exactly_expected_class_names(self) -> None:
        """`__all__` exports the complete typed collection surface."""
        assert __all__ == EXPECTED_ALL
        assert len(__all__) == 38


@pytest.mark.unit
class TestDocumentCollectionSubclasses:
    """Tests for document collection inheritance."""

    @pytest.mark.parametrize("collection_cls", DOCUMENT_COLLECTION_CLASSES)
    def test_document_collections_subclass_document_collection(self, collection_cls: type[object]) -> None:
        """All non-edge, non-vector collections are document collections."""
        assert issubclass(collection_cls, DocumentCollection)

    @pytest.mark.parametrize("collection_cls", DIRECT_DOCUMENT_COLLECTION_CLASSES)
    def test_non_state_graph_document_collections_subclass_document_collection_directly(
        self,
        collection_cls: type[object],
    ) -> None:
        """All document collections except `FileStates` inherit directly from `DocumentCollection`."""
        assert DocumentCollection in collection_cls.__bases__

    def test_file_states_subclasses_state_graph_collection(self) -> None:
        """`FileStates` uses the state-graph-aware document base."""
        assert issubclass(FileStates, StateGraphCollection)
        assert StateGraphCollection in FileStates.__bases__


@pytest.mark.unit
class TestEdgeCollectionSubclasses:
    """Tests for edge collection inheritance."""

    @pytest.mark.parametrize("collection_cls", EDGE_COLLECTION_CLASSES)
    def test_edge_collections_subclass_edge_collection(self, collection_cls: type[object]) -> None:
        """All declared edge collections inherit from `EdgeCollection`."""
        assert issubclass(collection_cls, EdgeCollection)


@pytest.mark.unit
class TestVectorCollectionSubclasses:
    """Tests for vector collection inheritance."""

    @pytest.mark.parametrize("collection_cls", VECTOR_COLLECTION_CLASSES)
    def test_vector_collections_subclass_vector_collection(self, collection_cls: type[object]) -> None:
        """All declared vector collections inherit from `VectorCollection`."""
        assert issubclass(collection_cls, VectorCollection)


@pytest.mark.unit
class TestCustomCollectionNames:
    """Tests for custom physical collection names."""

    def test_migrations_uses_applied_migrations_name(self) -> None:
        """`Migrations` maps to the applied migrations collection."""
        assert Migrations._name == "applied_migrations"

    def test_ml_capacity_uses_capacity_estimates_name(self) -> None:
        """`MlCapacity` maps to the renamed capacity estimates collection."""
        assert MlCapacity._name == "ml_capacity_estimates"


@pytest.mark.unit
class TestEdgeCollectionEndpoints:
    """Tests for edge endpoint declarations."""

    @pytest.mark.parametrize("collection_cls", EDGE_COLLECTION_CLASSES)
    def test_edge_collections_define_from_and_to_collection(self, collection_cls: type[EdgeCollection]) -> None:
        """Every edge class declares source and destination collection classes."""
        assert hasattr(collection_cls, "FROM_COLLECTION")
        assert hasattr(collection_cls, "TO_COLLECTION")

    @pytest.mark.parametrize(
        ("collection_cls", "from_collection", "to_collection"),
        [
            (SongHasTags, LibraryFiles, Tags),
            (TagModelOutput, Tags, MlModelOutputs),
            (HasPlays, NavidromeTracks, NavidromePlaycounts),
        ],
    )
    def test_selected_edge_collections_point_to_expected_endpoints(
        self,
        collection_cls: type[EdgeCollection],
        from_collection: type[DocumentCollection],
        to_collection: type[DocumentCollection],
    ) -> None:
        """Representative edges bind the expected endpoint collections."""
        assert collection_cls.FROM_COLLECTION is from_collection
        assert collection_cls.TO_COLLECTION is to_collection


@pytest.mark.unit
class TestTagModelOutputFields:
    """Tests for payload annotations on `TagModelOutput`."""

    def test_tag_model_output_declares_expected_payload_fields(self) -> None:
        """`TagModelOutput` exposes score and timestamp payload annotations."""
        assert TagModelOutput.__annotations__ == {
            "score": "Field[float]",
            "created_at": "Field[int]",
            "updated_at": "Field[int]",
        }

    @pytest.mark.parametrize(
        ("field_name", "expected_type"),
        [("score", float), ("created_at", int), ("updated_at", int)],
    )
    def test_tag_model_output_payload_fields_are_non_unique_field_annotations(
        self,
        field_name: str,
        expected_type: type[object],
    ) -> None:
        """The payload fields resolve to non-unique `Field[...]` annotations."""
        annotation = get_type_hints(TagModelOutput, include_extras=True)[field_name]
        args = get_args(annotation)

        assert args[0] is expected_type
        assert args[1] == FieldMarker(unique=False)


@pytest.mark.unit
class TestVectorCollectionMetadata:
    """Tests for vector collection metadata constants."""

    @pytest.mark.parametrize(
        ("collection_cls", "expected_tier", "expected_pattern"),
        [
            (
                VectorsTrackHot,
                "hot",
                "vectors_track_hot__{backbone_id}__{library_key}",
            ),
            (
                VectorsTrackCold,
                "cold",
                "vectors_track_cold__{backbone_id}__{library_key}",
            ),
        ],
    )
    def test_vector_collections_define_expected_metadata(
        self,
        collection_cls: type[VectorCollection],
        expected_tier: str,
        expected_pattern: str,
    ) -> None:
        """Hot and cold vector collections declare their tier and naming template."""
        assert expected_tier == collection_cls.VECTOR_TIER
        assert expected_pattern == collection_cls.NAME_PATTERN


@pytest.mark.unit
class TestEdgesAssignments:
    """Tests for selected `EDGES` assignment policies."""

    @pytest.mark.parametrize(
        ("owner", "expected_edge"),
        [
            (
                Libraries,
                EdgeDef(
                    via=LibraryContainsFile,
                    direction="OUTBOUND",
                    target=LibraryFiles,
                    on_delete=CASCADE,
                ),
            ),
            (
                LibraryScans,
                EdgeDef(
                    via=LibraryHasScan,
                    direction="INBOUND",
                    target=Libraries,
                    on_delete=DETACH,
                ),
            ),
            (
                LibraryPipelineStates,
                EdgeDef(
                    via=LibraryHasPipelineState,
                    direction="INBOUND",
                    target=Libraries,
                    on_delete=DETACH,
                ),
            ),
            (
                LibraryFiles,
                EdgeDef(
                    via=SongHasTags,
                    direction="OUTBOUND",
                    target=Tags,
                    on_delete=CASCADE,
                ),
            ),
            (
                FileStates,
                EdgeDef(
                    via=FileHasState,
                    direction="INBOUND",
                    target=LibraryFiles,
                    on_delete=DETACH,
                ),
            ),
            (
                NavidromePlaycounts,
                EdgeDef(
                    via=HasPlays,
                    direction="INBOUND",
                    target=NavidromeTracks,
                    on_delete=DETACH,
                ),
            ),
            (
                CalibrationState,
                EdgeDef(
                    via=ModelHasCalibration,
                    direction="INBOUND",
                    target=MlModels,
                    on_delete=CASCADE,
                ),
            ),
        ],
    )
    def test_selected_collections_expose_expected_edge_policies(
        self,
        owner: type[DocumentCollection],
        expected_edge: EdgeDef,
    ) -> None:
        """Selected edge definitions preserve their expected cascade/detach behavior."""
        assert expected_edge in owner.EDGES
