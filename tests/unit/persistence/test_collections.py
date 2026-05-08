"""Tests for typed persistence collection declarations."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from nomarr.persistence.base_types import CASCADE, DETACH, EdgeDef
from nomarr.persistence.collections import (
    CalibrationHistory,
    CalibrationState,
    FileHasOutputStream,
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
    MlOutputStreams,
    ModelHasCalibration,
    ModelHasOutput,
    NavidromePlaycounts,
    NavidromeTracks,
    OutputHasStream,
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
from nomarr.persistence.collections_base import (
    DocumentCollection,
    EdgeCollection,
    StateGraphCollection,
    VectorCollection,
)

EXPECTED_ALL = [
    "CalibrationHistory",
    "CalibrationState",
    "FileHasOutputStream",
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
    "MlOutputStreams",
    "ModelHasCalibration",
    "ModelHasOutput",
    "NavidromePlaycounts",
    "NavidromeTracks",
    "OutputHasStream",
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
    MlOutputStreams,
    NavidromeTracks,
    NavidromePlaycounts,
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
    MlOutputStreams,
    NavidromeTracks,
    NavidromePlaycounts,
]

EDGE_COLLECTION_CLASSES = [
    SongHasTags,
    FileHasState,
    TagModelOutput,
    LibraryContainsFile,
    LibraryContainsFolder,
    LibraryHasScan,
    FileHasVectors,
    FileHasOutputStream,
    ModelHasOutput,
    ModelHasCalibration,
    OutputHasStream,
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
        assert len(__all__) == 39


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

    @pytest.mark.mocked
    def test_file_states_init_sets_edge_name_and_returns_document_collection(self) -> None:
        """`FileStates` delegates to the state-graph base with the expected edge wiring."""
        mock_db = MagicMock()

        instance = FileStates(mock_db)

        assert isinstance(instance, DocumentCollection)
        assert instance._edge_name == "file_has_state"


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
class TestLibraryFilesCustomMethods:
    """Tests for concrete `LibraryFiles` helper methods."""

    def test_get_files_by_paths_bulk_uses_single_exact_query(self) -> None:
        mock_db = MagicMock()
        mock_db.aql.execute.return_value = [
            {
                "_id": "library_files/1",
                "_key": "1",
                "normalized_path": "artist/song.flac",
                "path": "D:/Music/artist/song.flac",
            },
            {
                "_id": "library_files/2",
                "_key": "2",
                "normalized_path": "artist/other.flac",
                "path": "D:/Music/artist/other.flac",
            },
        ]
        instance = LibraryFiles(mock_db)

        result = instance.get_files_by_paths_bulk(
            ["artist/song.flac", "D:/Music/artist/other.flac", "missing.flac"],
        )

        assert result == {
            "artist/song.flac": {
                "_id": "library_files/1",
                "_key": "1",
                "normalized_path": "artist/song.flac",
                "path": "D:/Music/artist/song.flac",
            },
            "D:/Music/artist/other.flac": {
                "_id": "library_files/2",
                "_key": "2",
                "normalized_path": "artist/other.flac",
                "path": "D:/Music/artist/other.flac",
            },
        }
        mock_db.aql.execute.assert_called_once_with(
            """
            FOR doc IN @@collection
                FILTER doc.normalized_path IN @paths OR doc.path IN @paths
                SORT doc._key
                RETURN doc
            """,
            bind_vars={
                "@collection": "library_files",
                "paths": ["artist/song.flac", "D:/Music/artist/other.flac", "missing.flac"],
            },
        )

    def test_get_files_by_paths_bulk_prefers_normalized_path_match(self) -> None:
        mock_db = MagicMock()
        normalized_match = {
            "_id": "library_files/1",
            "_key": "1",
            "normalized_path": "artist/song.flac",
            "path": "D:/Music/artist/song.flac",
        }
        absolute_match = {
            "_id": "library_files/2",
            "_key": "2",
            "normalized_path": "other/song.flac",
            "path": "artist/song.flac",
        }
        mock_db.aql.execute.return_value = [normalized_match, absolute_match]
        instance = LibraryFiles(mock_db)

        result = instance.get_files_by_paths_bulk(["artist/song.flac"])

        assert result == {"artist/song.flac": normalized_match}


@pytest.mark.unit
class TestCustomCollectionNames:
    """Tests for custom physical collection names."""

    def test_migrations_uses_applied_migrations_name(self) -> None:
        """`Migrations` maps to the applied migrations collection."""
        mock_db = MagicMock()

        assert Migrations(mock_db)._name == "applied_migrations"

    def test_ml_capacity_uses_capacity_estimates_name(self) -> None:
        """`MlCapacity` maps to the renamed capacity estimates collection."""
        mock_db = MagicMock()

        assert MlCapacity(mock_db)._name == "ml_capacity_estimates"


@pytest.mark.unit
class TestEdgeCollectionEndpoints:
    """Tests for edge endpoint declarations."""

    @pytest.mark.parametrize("collection_cls", EDGE_COLLECTION_CLASSES)
    def test_edge_collections_define_from_and_to_collection(self, collection_cls: type) -> None:
        """Every edge class declares source and destination collection classes."""
        assert hasattr(collection_cls, "FROM_COLLECTION")
        assert hasattr(collection_cls, "TO_COLLECTION")

    @pytest.mark.parametrize(
        ("collection_cls", "from_collection", "to_collection"),
        [
            (SongHasTags, LibraryFiles, Tags),
            (TagModelOutput, Tags, MlModelOutputs),
            (FileHasOutputStream, LibraryFiles, MlOutputStreams),
            (OutputHasStream, MlModelOutputs, MlOutputStreams),
            (HasPlays, NavidromeTracks, NavidromePlaycounts),
        ],
    )
    def test_selected_edge_collections_point_to_expected_endpoints(
        self,
        collection_cls: type,
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
            "score": "FieldAccessor",
            "created_at": "FieldAccessor",
            "updated_at": "FieldAccessor",
        }


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
                LibraryFiles,
                EdgeDef(
                    via=FileHasOutputStream,
                    direction="OUTBOUND",
                    target=MlOutputStreams,
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
            (
                MlOutputStreams,
                EdgeDef(
                    via=OutputHasStream,
                    direction="INBOUND",
                    target=MlModelOutputs,
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
