"""Unit tests for collection-first AQL validation helpers."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nomarr.persistence.aql_validation import (
    AQLParseExplainValidationError,
    AQLValidationStatus,
    DuplicateCollectionMetadataError,
    InvalidCapabilityForCollectionError,
    InvalidPaginationError,
    InvalidPayloadError,
    InvalidSortError,
    InvalidTemplateBindValueError,
    InvalidUniquenessAssumptionError,
    RawAQLBindEscapeHatchError,
    TemplateBindValidationError,
    TemplateContractValidationError,
    UnknownCollectionError,
    UnknownFieldError,
    UnsupportedOperatorError,
    ValidatedTemplateContract,
    materialize_collection_metadata,
    validate_bound_aql,
    validate_query_spec,
    validate_spec_template_contract,
    validate_template_bindings,
)
from nomarr.persistence.collections import LibraryFiles
from nomarr.persistence.query_specs import (
    AggregateQuerySpec,
    CapabilityFamily,
    CollectionFamily,
    PaginationSpec,
    QueryCollectionMetadata,
    QueryCriterion,
    QueryFieldMetadata,
    QueryOperator,
    ReadQuerySpec,
    SortFieldSpec,
    WriteQuerySpec,
    collection_metadata_from_provider,
)
from nomarr.persistence.query_templates import (
    QueryTemplateId,
    bind_first_party_query_template,
    iter_first_party_query_templates,
)


@pytest.fixture
def library_files_metadata() -> QueryCollectionMetadata:
    """Provide real collection metadata from the persistence wrapper."""
    return collection_metadata_from_provider(LibraryFiles(MagicMock()))


@pytest.fixture
def collections(library_files_metadata: QueryCollectionMetadata) -> dict[str, QueryCollectionMetadata]:
    """Provide a minimal metadata index for validation tests."""
    return {"library_files": library_files_metadata}


@pytest.mark.unit
@pytest.mark.mocked
class TestMaterializeCollectionMetadata:
    """Tests for metadata normalization."""

    def test_rejects_conflicting_duplicate_collection_metadata(self) -> None:
        """Two different metadata definitions must not collapse to one collection name."""
        first = QueryCollectionMetadata(
            collection_name="library_files",
            collection_family=CollectionFamily.DOCUMENT,
            fields={"path": QueryFieldMetadata(name="path", unique=True)},
        )
        second = QueryCollectionMetadata(
            collection_name="library_files",
            collection_family=CollectionFamily.DOCUMENT,
            fields={"artist": QueryFieldMetadata(name="artist", unique=False)},
        )

        with pytest.raises(DuplicateCollectionMetadataError, match="same collection name"):
            materialize_collection_metadata(
                {
                    "library_files": first,
                    "library_files_alias": second,
                },
            )


@pytest.mark.unit
@pytest.mark.mocked
class TestValidateQuerySpec:
    """Tests for spec-time validation against collection metadata."""

    def test_accepts_valid_read_spec_against_real_collection_metadata(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Valid collection-first read specs should resolve to collection metadata."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            criteria=(
                QueryCriterion(
                    field_name="artist",
                    operator=QueryOperator.EQ,
                    value="Boards of Canada",
                ),
            ),
            sort=(SortFieldSpec(field_name="artist"),),
            pagination=PaginationSpec(limit=10, offset=0),
        )

        metadata = validate_query_spec(spec, collections)

        assert metadata.collection_name == "library_files"

    def test_rejects_unknown_collection(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Unknown collections should fail before any template work happens."""
        spec = ReadQuerySpec(
            collection_name="missing_collection",
            pagination=PaginationSpec(limit=10, offset=0),
        )

        with pytest.raises(UnknownCollectionError, match="Unknown collection"):
            validate_query_spec(spec, collections)

    def test_rejects_capability_family_when_collection_family_is_unsupported(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Read specs should reject capability families that do not match document collections."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            pagination=PaginationSpec(limit=10, offset=0),
        )
        object.__setattr__(spec, "capability_family", CapabilityFamily.ANN_SEARCH)

        with pytest.raises(
            InvalidCapabilityForCollectionError,
            match="not valid for collection family",
        ):
            validate_query_spec(spec, collections)

    def test_rejects_pagination_when_limit_is_negative(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Negative limits should fail spec validation for reviewed reads."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            pagination=PaginationSpec(limit=-1, offset=0),
        )

        with pytest.raises(InvalidPaginationError, match="Pagination limit must be >= 0"):
            validate_query_spec(spec, collections)

    def test_rejects_pagination_when_offset_is_negative(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Negative offsets should fail spec validation for reviewed reads."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            pagination=PaginationSpec(limit=10, offset=-1),
        )

        with pytest.raises(InvalidPaginationError, match="Pagination offset must be >= 0"):
            validate_query_spec(spec, collections)

    def test_rejects_pagination_when_offset_has_no_limit(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Offsets without explicit limits should be rejected for reviewed reads."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            pagination=PaginationSpec(limit=None, offset=5),
        )

        with pytest.raises(InvalidPaginationError, match="offset requires an explicit limit"):
            validate_query_spec(spec, collections)

    def test_rejects_payload_when_raw_aql_bind_name_is_present(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Payloads should reject raw-AQL bind names before field validation runs."""
        spec = WriteQuerySpec(
            collection_name="library_files",
            payload={"raw_aql": "injected"},
        )

        with pytest.raises(InvalidPayloadError, match="Raw AQL fragment keys are not allowed"):
            validate_query_spec(spec, collections)

    def test_rejects_sort_when_multiple_sort_fields_are_provided(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Reviewed reads currently allow at most one explicit sort field."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            sort=(
                SortFieldSpec(field_name="artist"),
                SortFieldSpec(field_name="path"),
            ),
            pagination=PaginationSpec(limit=10, offset=0),
        )

        with pytest.raises(InvalidSortError, match="at most one sort field"):
            validate_query_spec(spec, collections)

    def test_rejects_unsupported_operator_for_write_specs(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Write-family operators should stay constrained to the reviewed allowlist."""
        spec = WriteQuerySpec(
            collection_name="library_files",
            criteria=(
                QueryCriterion(
                    field_name="artist",
                    operator=QueryOperator.LIKE,
                    value="Boards%",
                ),
            ),
            payload={"artist": "Boards of Canada"},
        )

        with pytest.raises(UnsupportedOperatorError, match="not allowed"):
            validate_query_spec(spec, collections)

    def test_rejects_non_unique_match_fields(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Upsert match fields should require explicit uniqueness-backed metadata."""
        spec = WriteQuerySpec(
            collection_name="library_files",
            payload={"artist": "Boards of Canada"},
            match_fields=("artist",),
        )

        with pytest.raises(
            InvalidUniquenessAssumptionError,
            match="is not declared unique",
        ):
            validate_query_spec(spec, collections)

    def test_rejects_sort_fields_not_present_in_metadata(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Sort fields should be metadata-approved rather than arbitrary strings."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            sort=(SortFieldSpec(field_name="missing_field"),),
            pagination=PaginationSpec(limit=10, offset=0),
        )

        with pytest.raises(UnknownFieldError, match="Unknown field 'missing_field'"):
            validate_query_spec(spec, collections)

    def test_rejects_unknown_aggregate_fields(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Aggregate field allowlists should be enforced at spec time."""
        spec = AggregateQuerySpec(
            collection_name="library_files",
            aggregate_fields=("missing_field",),
            pagination=PaginationSpec(limit=10, offset=0),
        )

        with pytest.raises(UnknownFieldError, match="Unknown field 'missing_field'"):
            validate_query_spec(spec, collections)


@pytest.mark.unit
@pytest.mark.mocked
class TestValidateSpecTemplateContract:
    """Tests for spec-to-template contract validation."""

    def test_accepts_matching_capability_family_and_operators(
        self, collections: dict[str, QueryCollectionMetadata]
    ) -> None:
        """Matching read specs and document-read templates should validate successfully."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            criteria=(
                QueryCriterion(
                    field_name="artist",
                    operator=QueryOperator.EQ,
                    value="Boards of Canada",
                ),
            ),
            pagination=PaginationSpec(limit=10, offset=0),
        )
        template = next(
            asset
            for asset in iter_first_party_query_templates(capability_family=CapabilityFamily.DOCUMENT_READ)
            if asset.template_id is QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA
        )

        contract = validate_spec_template_contract(spec, template, collections)

        assert isinstance(contract, ValidatedTemplateContract)
        assert contract.collection_metadata.collection_name == "library_files"
        assert contract.template_asset.template_id is QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA

    def test_rejects_mismatched_capability_family(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Templates from a different capability family should be rejected."""
        spec = ReadQuerySpec(
            collection_name="library_files",
            pagination=PaginationSpec(limit=10, offset=0),
        )
        template = next(
            asset
            for asset in iter_first_party_query_templates(capability_family=CapabilityFamily.AGGREGATION)
            if asset.template_id is QueryTemplateId.AGGREGATION_COUNT_BY_CRITERIA
        )

        with pytest.raises(TemplateContractValidationError, match="targets capability family"):
            validate_spec_template_contract(spec, template, collections)

    def test_rejects_operator_not_supported_by_template(self, collections: dict[str, QueryCollectionMetadata]) -> None:
        """Write templates without criteria support should reject even otherwise-valid operators."""
        spec = WriteQuerySpec(
            collection_name="library_files",
            criteria=(
                QueryCriterion(
                    field_name="artist",
                    operator=QueryOperator.EQ,
                    value="Boards of Canada",
                ),
            ),
            payload={"artist": "Boards of Canada"},
        )
        template = next(
            asset
            for asset in iter_first_party_query_templates(capability_family=CapabilityFamily.DOCUMENT_WRITE)
            if asset.template_id is QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY
        )

        with pytest.raises(TemplateContractValidationError, match="does not support operators"):
            validate_spec_template_contract(spec, template, collections)


@pytest.mark.unit
@pytest.mark.mocked
class TestValidateTemplateBindings:
    """Tests for bind-time validation and metadata affinity."""

    def test_accepts_metadata_approved_document_read_bindings(
        self, library_files_metadata: QueryCollectionMetadata
    ) -> None:
        """Reviewed bind payloads should bind cleanly when they match metadata."""
        bound = validate_template_bindings(
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
                "sort_field": "artist",
                "sort_direction": "asc",
                "limit": 5,
                "offset": 0,
            },
            collection_metadata=library_files_metadata,
        )

        assert bound.template_id is QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA
        assert bound.bind_vars["sort_field"] == "artist"

    def test_rejects_collection_metadata_mismatches(self, library_files_metadata: QueryCollectionMetadata) -> None:
        """The bound collection name should agree with the validated metadata."""
        with pytest.raises(TemplateBindValidationError, match="metadata targets 'library_files'"):
            validate_template_bindings(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "tags",
                    "criteria": [],
                    "limit": 5,
                    "offset": 0,
                },
                collection_metadata=library_files_metadata,
            )

    def test_rejects_sort_direction_without_sort_field(self, library_files_metadata: QueryCollectionMetadata) -> None:
        """Direction-only sorting should fail fast."""
        with pytest.raises(InvalidTemplateBindValueError, match="sort_direction requires"):
            validate_template_bindings(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "library_files",
                    "criteria": [],
                    "sort_direction": "asc",
                    "limit": 5,
                    "offset": 0,
                },
                collection_metadata=library_files_metadata,
            )

    def test_rejects_raw_aql_escape_hatches(self, library_files_metadata: QueryCollectionMetadata) -> None:
        """Raw-AQL bind keys should surface as explicit validation errors."""
        with pytest.raises(RawAQLBindEscapeHatchError, match="Raw AQL fragments"):
            validate_template_bindings(
                QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
                {
                    "@collection": "library_files",
                    "criteria": [],
                    "limit": 5,
                    "offset": 0,
                    "raw_aql": "FOR doc IN library_files RETURN doc",
                },
                collection_metadata=library_files_metadata,
            )


@pytest.mark.unit
@pytest.mark.mocked
class TestValidateBoundAql:
    """Tests for optional Arango-backed parse/explain validation."""

    def test_skips_when_database_handle_is_unavailable(self) -> None:
        """The parse/explain layer should skip explicitly without a database handle."""
        bound = bind_first_party_query_template(
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [],
                "limit": 5,
                "offset": 0,
            },
        )

        report = validate_bound_aql(None, bound)

        assert report.status is AQLValidationStatus.SKIPPED
        assert report.skip_reason == "database handle unavailable"
        assert report.syntax_validated is False
        assert report.explained is False

    def test_runs_validate_and_explain_when_database_hooks_exist(self) -> None:
        """Validation should call Arango validate/explain exactly once."""
        aql = MagicMock()
        aql.validate.return_value = {"parsed": True}
        aql.explain.return_value = {"plan": []}
        database = SimpleNamespace(aql=aql)
        bound = bind_first_party_query_template(
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [],
                "limit": 5,
                "offset": 0,
            },
        )

        report = validate_bound_aql(database, bound)

        assert report.status is AQLValidationStatus.VALIDATED
        assert report.syntax_validated is True
        assert report.explained is True
        assert report.validate_result == {"parsed": True}
        assert report.explain_result == {"plan": []}
        aql.validate.assert_called_once_with(bound.aql)
        aql.explain.assert_called_once_with(bound.aql, bind_vars=bound.bind_vars)

    def test_wraps_validate_errors_as_explicit_parse_explain_failures(self) -> None:
        """Unexpected AQL-hook failures should be normalized to one error type."""
        aql = MagicMock()
        aql.validate.side_effect = RuntimeError("boom")
        database = SimpleNamespace(aql=aql)
        bound = bind_first_party_query_template(
            QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            {
                "@collection": "library_files",
                "criteria": [],
                "limit": 5,
                "offset": 0,
            },
        )

        with pytest.raises(AQLParseExplainValidationError, match="syntax validation failed"):
            validate_bound_aql(database, bound)
