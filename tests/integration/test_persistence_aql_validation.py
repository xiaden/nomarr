"""Integration tests for collection-first AQL validation flows."""

from __future__ import annotations

import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from nomarr.persistence.aql_validation import (
    AQLValidationStatus,
    validate_bound_aql,
    validate_first_party_aql,
    validate_spec_template_contract,
    validate_template_bindings,
)
from nomarr.persistence.arango_client import create_arango_client
from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    CollectionFamily,
    PaginationSpec,
    QueryCollectionMetadata,
    QueryCriterion,
    QueryFieldMetadata,
    QueryOperator,
    ReadQuerySpec,
    WriteQuerySpec,
    collection_metadata_from_provider,
)
from nomarr.persistence.query_templates import QueryTemplateId, iter_first_party_query_templates


def _library_files_metadata() -> QueryCollectionMetadata:
    """Build representative static collection metadata from the real wrapper."""
    return collection_metadata_from_provider(LibraryFiles(MagicMock()))


def _vector_collection_metadata(collection_name: str) -> QueryCollectionMetadata:
    """Build representative vector metadata for ANN template validation."""
    return QueryCollectionMetadata(
        collection_name=collection_name,
        collection_family=CollectionFamily.VECTOR,
        fields={
            "file_id": QueryFieldMetadata(name="file_id", unique=False),
            "vector_n": QueryFieldMetadata(name="vector_n", unique=False),
            "genres": QueryFieldMetadata(name="genres", unique=False),
        },
    )


def _static_template_cases() -> list[tuple[object, QueryTemplateId, dict[str, object]]]:
    """Return representative static spec/template/bind combinations."""
    return [
        (
            ReadQuerySpec(
                collection_name="library_files",
                criteria=(
                    QueryCriterion(
                        field_name="artist",
                        operator=QueryOperator.EQ,
                        value="Boards of Canada",
                    ),
                ),
                pagination=PaginationSpec(limit=10, offset=0),
            ),
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [
                    {
                        "field_name": "artist",
                        "operator": "eq",
                        "value": "Boards of Canada",
                    },
                ],
                "limit": 10,
                "offset": 0,
            },
        ),
        (
            WriteQuerySpec(
                collection_name="library_files",
                payload={"path": "D:/music/test.flac", "artist": "Boards of Canada"},
            ),
            QueryTemplateId.DOCUMENT_WRITE_INSERT_MANY,
            {
                "@collection": "library_files",
                "docs": [{"path": "D:/music/test.flac", "artist": "Boards of Canada"}],
            },
        ),
        (
            WriteQuerySpec(
                collection_name="library_files",
                payload={"path": "D:/music/test.flac", "artist": "Boards of Canada"},
                match_fields=("path",),
            ),
            QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY,
            {
                "@collection": "library_files",
                "docs": [{"path": "D:/music/test.flac", "artist": "Boards of Canada"}],
                "match_fields": ["path"],
            },
        ),
        (
            AggregateQuerySpec(
                collection_name="library_files",
                criteria=(
                    QueryCriterion(
                        field_name="artist",
                        operator=QueryOperator.EQ,
                        value="Boards of Canada",
                    ),
                ),
            ),
            QueryTemplateId.AGGREGATION_COUNT_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [
                    {
                        "field_name": "artist",
                        "operator": "eq",
                        "value": "Boards of Canada",
                    },
                ],
            },
        ),
        (
            AggregateQuerySpec(
                collection_name="library_files",
                criteria=(
                    QueryCriterion(
                        field_name="artist",
                        operator=QueryOperator.EQ,
                        value="Boards of Canada",
                    ),
                ),
                aggregate_fields=("artist",),
                pagination=PaginationSpec(limit=10, offset=0),
            ),
            QueryTemplateId.AGGREGATION_FIELD_COUNTS,
            {
                "@collection": "library_files",
                "criteria": [
                    {
                        "field_name": "artist",
                        "operator": "eq",
                        "value": "Boards of Canada",
                    },
                ],
                "aggregate_field": "artist",
                "limit": 10,
                "offset": 0,
            },
        ),
    ]


def _live_validation_database() -> object:
    """Return a live Arango database handle or skip explicitly."""
    host = os.getenv("ARANGO_HOST")
    root_password = os.getenv("ARANGO_ROOT_PASSWORD")
    if not host or not root_password:
        pytest.skip("ARANGO_HOST and ARANGO_ROOT_PASSWORD are not configured for live AQL validation")

    db_name = os.getenv("ARANGO_DB", "nomarr")
    username = os.getenv("ARANGO_USERNAME", "root")

    try:
        return create_arango_client(
            hosts=host,
            username=username,
            password=root_password,
            db_name=db_name,
        )
    except ModuleNotFoundError:
        pytest.skip("python-arango is not installed for live AQL validation")
    except Exception as exc:  # pragma: no cover - environment-specific skip path
        pytest.skip(f"Unable to connect to live ArangoDB for AQL validation: {exc}")


def _find_live_vector_collection(database: object) -> str | None:
    """Return one representative cold vector collection name if available."""
    collections = getattr(database, "collections", None)
    if collections is None:
        return None

    for raw_collection in collections():
        collection_name = str(raw_collection.get("name", ""))
        if collection_name.startswith("vectors_track_cold__") and not raw_collection.get("system", False):
            return collection_name
    return None


@pytest.mark.integration
@pytest.mark.mocked
class TestTemplateCoverageIntegration:
    """Integration coverage for the Part A validation foundation."""

    def test_enumerates_all_templates_and_compiles_static_plus_vector_representatives(self) -> None:
        """Every first-party template should have one representative binding path."""
        static_metadata = _library_files_metadata()
        collections = {"library_files": static_metadata}

        seen_template_ids: set[QueryTemplateId] = set()
        for query_spec, template_id, bind_vars in _static_template_cases():
            contract = validate_spec_template_contract(query_spec, template_id, collections)
            bound = validate_template_bindings(
                contract.template_asset,
                bind_vars,
                collection_metadata=contract.collection_metadata,
            )
            assert bound.template_id is template_id
            seen_template_ids.add(template_id)

        vector_template_id = QueryTemplateId.ANN_SEARCH_APPROX_NEAR_COSINE
        vector_metadata = _vector_collection_metadata("vectors_track_cold__discogs_effnet__lib1")
        vector_bound = validate_template_bindings(
            vector_template_id,
            {
                "@collection": vector_metadata.collection_name,
                "query_vector": [0.1, 0.2, 0.3],
                "limit": 5,
                "nprobe": 10,
                "filter_field": "file_id",
                "filter_value": "library_files/1",
            },
            collection_metadata=vector_metadata,
        )
        assert vector_bound.template_id is vector_template_id
        seen_template_ids.add(vector_template_id)

        assert seen_template_ids == {asset.template_id for asset in iter_first_party_query_templates()}


@pytest.mark.integration
@pytest.mark.requires_database
class TestLiveParseExplainValidation:
    """Optional live-Arango parse/explain validation coverage."""

    def test_static_first_party_templates_validate_and_explain_when_arango_is_configured(self) -> None:
        """Static reviewed templates should validate against a live Arango handle when available."""
        database = _live_validation_database()
        has_collection = getattr(database, "has_collection", None)
        if has_collection is None or not has_collection("library_files"):
            pytest.skip("library_files collection is unavailable in the live Arango database")

        collections = {"library_files": _library_files_metadata()}
        for query_spec, template_id, bind_vars in _static_template_cases():
            report = validate_first_party_aql(
                database,
                query_spec,
                template_id,
                bind_vars,
                collections=collections,
                explain=True,
            )
            assert report.status is AQLValidationStatus.VALIDATED
            assert report.syntax_validated is True
            assert report.explained is True

    def test_ann_template_validates_against_a_live_vector_collection_when_available(self) -> None:
        """ANN parse/explain validation should run when a cold vector collection exists."""
        database = _live_validation_database()
        vector_collection_name = _find_live_vector_collection(database)
        if vector_collection_name is None:
            pytest.skip("No non-system vectors_track_cold__* collection is available for ANN validation")

        vector_metadata = _vector_collection_metadata(vector_collection_name)
        bound = validate_template_bindings(
            QueryTemplateId.ANN_SEARCH_APPROX_NEAR_COSINE,
            {
                "@collection": vector_collection_name,
                "query_vector": [0.1, 0.2, 0.3],
                "limit": 5,
                "nprobe": 10,
                "filter_field": "file_id",
                "filter_value": "library_files/1",
            },
            collection_metadata=vector_metadata,
        )

        report = validate_bound_aql(database, bound, explain=True)

        assert report.status is AQLValidationStatus.VALIDATED
        assert report.syntax_validated is True
        assert report.explained is True


@pytest.mark.integration
@pytest.mark.requires_database
class TestCollectionFirstPersistenceSurfaceIntegration:
    """Optional live-Arango coverage for the collection-first persistence surface."""

    def test_library_files_collection_first_round_trip(self) -> None:
        """Collection-first read/write/delete/count/aggregate paths should round-trip on a live DB."""
        database = _live_validation_database()
        has_collection = getattr(database, "has_collection", None)
        if has_collection is None or not has_collection("library_files"):
            pytest.skip("library_files collection is unavailable in the live Arango database")

        collection = LibraryFiles(database)
        token = uuid4().hex
        artist = f"phase4-{token}"
        first_path = f"D:/tmp/{token}-a.flac"
        second_path = f"D:/tmp/{token}-b.flac"
        delete_spec = WriteQuerySpec(
            collection_name="library_files",
            criteria=(QueryCriterion("artist", QueryOperator.EQ, artist),),
        )
        count_spec = AggregateQuerySpec(
            collection_name="library_files",
            criteria=(QueryCriterion("artist", QueryOperator.EQ, artist),),
        )

        collection.delete(query_spec=delete_spec)

        try:
            inserted_ids = collection.insert(
                [
                    {"path": first_path, "artist": artist, "title": "Alpha"},
                    {"path": second_path, "artist": artist, "title": "Beta"},
                ]
            )
            assert len(inserted_ids) == 2

            read_spec = ReadQuerySpec(
                collection_name="library_files",
                criteria=(QueryCriterion("artist", QueryOperator.EQ, artist),),
                pagination=PaginationSpec(limit=10, offset=0),
            )
            rows = collection.get.many(query_spec=read_spec)
            assert {row["path"] for row in rows} == {first_path, second_path}

            assert collection.count(query_spec=count_spec) == 2

            aggregate_rows = collection.aggregate(
                query_spec=AggregateQuerySpec(
                    collection_name="library_files",
                    criteria=(QueryCriterion("artist", QueryOperator.EQ, artist),),
                    aggregate_fields=("artist",),
                    pagination=PaginationSpec(limit=10, offset=0),
                )
            )
            assert any(
                isinstance(row, dict) and row.get("value") == artist and row.get("count") == 2 for row in aggregate_rows
            )

            upsert_ids = collection.upsert(
                query_spec=WriteQuerySpec(
                    collection_name="library_files",
                    criteria=(QueryCriterion("path", QueryOperator.EQ, first_path),),
                    payload={"artist": artist, "title": "Updated"},
                    match_fields=("path",),
                )
            )
            assert len(upsert_ids) == 1

            updated = collection.get(
                query_spec=ReadQuerySpec(
                    collection_name="library_files",
                    criteria=(QueryCriterion("path", QueryOperator.EQ, first_path),),
                )
            )
            assert isinstance(updated, dict)
            assert updated["title"] == "Updated"

            deleted = collection.delete(query_spec=delete_spec)
            assert deleted == 2
            assert collection.count(query_spec=count_spec) == 0
        finally:
            collection.delete(query_spec=delete_spec)
