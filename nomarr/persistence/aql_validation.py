"""AQL validation helpers for collection-first query-spec persistence.

This module is intentionally side-effect free. It separates:

- spec-time validation against collection/field metadata
- template-contract validation for reviewed first-party AQL assets
- bind-time validation for template bind payloads
- optional parse/explain validation hooks for Arango-backed tests and CI

It does **not** expose a new public persistence API surface or execute queries.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from .query_specs import (
    AggregateQuerySpec,
    CapabilityFamily,
    GenericCollectionQuerySpec,
    PaginationSpec,
    QueryCollectionMetadata,
    QueryCriterion,
    QueryFieldMetadata,
    QueryOperator,
    ReadQuerySpec,
    SortDirection,
    SortFieldSpec,
    SupportsQueryMetadata,
    WriteQuerySpec,
    collection_metadata_from_provider,
    is_collection_family_supported,
    supported_operators,
)
from .query_templates import (
    FORBIDDEN_RAW_AQL_BIND_NAMES,
    BoundQueryTemplate,
    QueryTemplateAsset,
    QueryTemplateBindSpec,
    QueryTemplateId,
    TemplateBindValueKind,
    TemplateResultShape,
    bind_first_party_query_template,
    template_asset,
    validate_template_bind_contract,
)

type CollectionMetadataInput = QueryCollectionMetadata | SupportsQueryMetadata
type CollectionMetadataMap = Mapping[str, CollectionMetadataInput]
type CriterionInput = QueryCriterion | Mapping[str, object]

_COLLECTION_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


class AQLValidationError(ValueError):
    """Base error for collection-first AQL validation failures."""


class QuerySpecValidationError(AQLValidationError):
    """Raised when a query spec fails metadata-backed validation."""


class TemplateContractValidationError(AQLValidationError):
    """Raised when a reviewed first-party template is incompatible with a spec."""


class TemplateBindValidationError(AQLValidationError):
    """Raised when a template bind payload fails closed-contract validation."""


class UnknownCollectionError(QuerySpecValidationError):
    """Raised when a query spec references an unknown collection."""


class DuplicateCollectionMetadataError(QuerySpecValidationError):
    """Raised when multiple metadata providers resolve to the same collection."""


class UnknownFieldError(QuerySpecValidationError):
    """Raised when a query spec or bind payload references an unknown field."""


class InvalidCapabilityForCollectionError(QuerySpecValidationError):
    """Raised when a capability family is not valid for the target collection."""


class UnsupportedOperatorError(QuerySpecValidationError):
    """Raised when a criterion operator is not allowed for the capability family."""


class InvalidUniquenessAssumptionError(QuerySpecValidationError):
    """Raised when a query implies uniqueness without explicit unique metadata."""


class InvalidPaginationError(QuerySpecValidationError):
    """Raised when a pagination payload is structurally invalid."""


class InvalidSortError(QuerySpecValidationError):
    """Raised when a sort payload is structurally invalid."""


class InvalidAggregateFieldError(QuerySpecValidationError):
    """Raised when an aggregate field payload is structurally invalid."""


class InvalidPayloadError(QuerySpecValidationError):
    """Raised when a write payload references unsupported fields or values."""


class InvalidTemplateResultShapeError(TemplateContractValidationError):
    """Raised when a template result shape is incompatible with a query spec."""


class InvalidTemplateBindValueError(TemplateBindValidationError):
    """Raised when a reviewed bind variable has the wrong structural type."""


class RawAQLBindEscapeHatchError(TemplateBindValidationError):
    """Raised when a bind payload attempts to smuggle raw AQL fragments."""


class AQLParseExplainValidationError(AQLValidationError):
    """Raised when Arango parse/explain validation rejects reviewed AQL."""


@dataclass(frozen=True)
class ValidatedTemplateContract:
    """A successfully validated spec/template pairing."""

    query_spec: GenericCollectionQuerySpec
    collection_metadata: QueryCollectionMetadata
    template_asset: QueryTemplateAsset


class AQLValidationStatus(StrEnum):
    """Outcome for optional Arango-backed parse/explain validation."""

    VALIDATED = "validated"
    SKIPPED = "skipped"


@dataclass(frozen=True)
class AQLValidationReport:
    """Structured parse/explain validation outcome for tests and CI."""

    template_id: QueryTemplateId
    status: AQLValidationStatus
    syntax_validated: bool
    explained: bool
    skip_reason: str | None = None
    validate_result: object | None = None
    explain_result: object | None = None


class SupportsAQLValidationInterface(Protocol):
    """Protocol for the subset of the Arango AQL interface used here."""

    def validate(self, query: str) -> object:
        """Validate AQL syntax without executing the query."""

    def explain(
        self,
        query: str,
        *,
        bind_vars: Mapping[str, object] | None = None,
        **kwargs: object,
    ) -> object:
        """Return an execution plan without executing the query."""


class SupportsAQLValidationDatabase(Protocol):
    """Protocol for database-like objects that expose ``.aql`` hooks."""

    aql: SupportsAQLValidationInterface


def materialize_collection_metadata(
    collections: CollectionMetadataMap,
) -> Mapping[str, QueryCollectionMetadata]:
    """Normalize a metadata-provider map into immutable collection metadata."""

    normalized: dict[str, QueryCollectionMetadata] = {}
    for provider_name, raw_provider in collections.items():
        metadata = (
            raw_provider
            if isinstance(raw_provider, QueryCollectionMetadata)
            else collection_metadata_from_provider(raw_provider)
        )
        existing = normalized.get(metadata.collection_name)
        if existing is not None and existing != metadata:
            msg = f"Multiple metadata providers resolved to the same collection name {metadata.collection_name!r}"
            raise DuplicateCollectionMetadataError(msg)
        normalized[metadata.collection_name] = metadata
        if provider_name != metadata.collection_name and provider_name not in normalized:
            normalized[provider_name] = metadata
    return MappingProxyType(normalized)


def validate_query_spec(
    query_spec: GenericCollectionQuerySpec,
    collections: CollectionMetadataMap,
) -> QueryCollectionMetadata:
    """Validate one generic collection-first query spec against metadata."""

    metadata_index = materialize_collection_metadata(collections)
    collection_metadata = metadata_index.get(query_spec.collection_name)
    if collection_metadata is None:
        msg = f"Unknown collection for query spec: {query_spec.collection_name}"
        raise UnknownCollectionError(msg)

    if not is_collection_family_supported(
        query_spec.capability_family,
        collection_metadata.collection_family,
    ):
        msg = (
            "Capability family "
            f"{query_spec.capability_family.value!r} is not valid for collection "
            f"family {collection_metadata.collection_family.value!r} on "
            f"{collection_metadata.collection_name!r}"
        )
        raise InvalidCapabilityForCollectionError(msg)

    _validate_criteria(
        criteria=query_spec.criteria,
        collection_metadata=collection_metadata,
        capability_family=query_spec.capability_family,
    )

    if isinstance(query_spec, ReadQuerySpec):
        _validate_sort(
            query_spec.sort,
            collection_metadata=collection_metadata,
        )
        _validate_pagination(query_spec.pagination)
    elif isinstance(query_spec, AggregateQuerySpec):
        _validate_aggregate_fields(
            query_spec.aggregate_fields,
            collection_metadata=collection_metadata,
        )
        _validate_pagination(query_spec.pagination)
    elif isinstance(query_spec, WriteQuerySpec):
        _validate_write_payload(
            query_spec.payload,
            collection_metadata=collection_metadata,
        )
        _validate_match_fields(
            query_spec.match_fields,
            collection_metadata=collection_metadata,
        )
    else:
        msg = f"Unsupported generic query spec type: {type(query_spec).__name__}"
        raise QuerySpecValidationError(msg)

    return collection_metadata


def validate_spec_template_contract(
    query_spec: GenericCollectionQuerySpec,
    template: QueryTemplateAsset | QueryTemplateId | str,
    collections: CollectionMetadataMap,
) -> ValidatedTemplateContract:
    """Validate that a reviewed template is compatible with a query spec."""

    collection_metadata = validate_query_spec(query_spec, collections)
    asset = _normalize_template_asset(template)

    if asset.capability_family != query_spec.capability_family:
        msg = (
            f"Template {asset.template_id.value!r} targets capability family "
            f"{asset.capability_family.value!r}, not {query_spec.capability_family.value!r}"
        )
        raise TemplateContractValidationError(msg)

    spec_operators = frozenset(criterion.operator for criterion in query_spec.criteria)
    unsupported_spec_operators = spec_operators - asset.supported_operators
    if unsupported_spec_operators:
        operator_list = ", ".join(sorted(operator.value for operator in unsupported_spec_operators))
        msg = f"Template {asset.template_id.value!r} does not support operators: {operator_list}"
        raise TemplateContractValidationError(msg)

    _validate_template_result_shape(asset, query_spec)
    _validate_template_bind_requirements(asset, query_spec)

    return ValidatedTemplateContract(
        query_spec=query_spec,
        collection_metadata=collection_metadata,
        template_asset=asset,
    )


def validate_template_bindings(
    template: QueryTemplateAsset | QueryTemplateId | str,
    bind_vars: Mapping[str, object],
    *,
    collection_metadata: QueryCollectionMetadata | None = None,
) -> BoundQueryTemplate:
    """Validate and bind a reviewed first-party template payload."""

    asset = _normalize_template_asset(template)
    _validate_template_bind_contract(asset, bind_vars)

    for bind_spec in asset.bind_specs:
        if bind_spec.name not in bind_vars:
            continue
        _validate_bind_value(
            bind_spec,
            bind_vars[bind_spec.name],
            asset=asset,
            collection_metadata=collection_metadata,
        )

    if collection_metadata is not None:
        _validate_template_bind_metadata_affinity(
            bind_vars,
            asset=asset,
            collection_metadata=collection_metadata,
        )

    return bind_first_party_query_template(asset.template_id, bind_vars)


def validate_bound_aql(
    database: SupportsAQLValidationDatabase | None,
    bound_template: BoundQueryTemplate,
    *,
    explain: bool = True,
) -> AQLValidationReport:
    """Run side-effect-free parse/explain validation where Arango hooks exist."""

    if database is None:
        return AQLValidationReport(
            template_id=bound_template.template_id,
            status=AQLValidationStatus.SKIPPED,
            syntax_validated=False,
            explained=False,
            skip_reason="database handle unavailable",
        )

    aql = getattr(database, "aql", None)
    if aql is None:
        return AQLValidationReport(
            template_id=bound_template.template_id,
            status=AQLValidationStatus.SKIPPED,
            syntax_validated=False,
            explained=False,
            skip_reason="database handle does not expose .aql",
        )

    if not hasattr(aql, "validate"):
        return AQLValidationReport(
            template_id=bound_template.template_id,
            status=AQLValidationStatus.SKIPPED,
            syntax_validated=False,
            explained=False,
            skip_reason="database AQL interface does not expose validate()",
        )

    if explain and not hasattr(aql, "explain"):
        return AQLValidationReport(
            template_id=bound_template.template_id,
            status=AQLValidationStatus.SKIPPED,
            syntax_validated=False,
            explained=False,
            skip_reason="database AQL interface does not expose explain()",
        )

    try:
        validate_result = aql.validate(bound_template.aql)
    except Exception as exc:
        msg = f"AQL syntax validation failed for template {bound_template.template_id.value!r}: {exc}"
        raise AQLParseExplainValidationError(msg) from exc

    explain_result: object | None = None
    if explain:
        try:
            explain_result = aql.explain(
                bound_template.aql,
                bind_vars=bound_template.bind_vars,
            )
        except Exception as exc:
            msg = f"AQL explain validation failed for template {bound_template.template_id.value!r}: {exc}"
            raise AQLParseExplainValidationError(msg) from exc

    return AQLValidationReport(
        template_id=bound_template.template_id,
        status=AQLValidationStatus.VALIDATED,
        syntax_validated=True,
        explained=explain,
        validate_result=validate_result,
        explain_result=explain_result,
    )


def validate_first_party_aql(
    database: SupportsAQLValidationDatabase | None,
    query_spec: GenericCollectionQuerySpec,
    template: QueryTemplateAsset | QueryTemplateId | str,
    bind_vars: Mapping[str, object],
    *,
    collections: CollectionMetadataMap,
    explain: bool = True,
) -> AQLValidationReport:
    """Convenience helper that validates spec, template, binds, and AQL hooks."""

    validated_contract = validate_spec_template_contract(
        query_spec,
        template,
        collections,
    )
    bound_template = validate_template_bindings(
        validated_contract.template_asset,
        bind_vars,
        collection_metadata=validated_contract.collection_metadata,
    )
    return validate_bound_aql(
        database,
        bound_template,
        explain=explain,
    )


def _normalize_template_asset(
    template: QueryTemplateAsset | QueryTemplateId | str,
) -> QueryTemplateAsset:
    if isinstance(template, QueryTemplateAsset):
        return template
    try:
        return template_asset(template)
    except KeyError as exc:
        msg = str(exc).strip('"')
        raise TemplateContractValidationError(msg) from exc


def _validate_template_bind_contract(
    asset: QueryTemplateAsset,
    bind_vars: Mapping[str, object],
) -> None:
    try:
        validate_template_bind_contract(asset, bind_vars)
    except ValueError as exc:
        message = str(exc)
        if any(name in message for name in FORBIDDEN_RAW_AQL_BIND_NAMES):
            raise RawAQLBindEscapeHatchError(message) from exc
        if "Raw AQL fragments" in message:
            raise RawAQLBindEscapeHatchError(message) from exc
        raise TemplateBindValidationError(message) from exc


def _validate_criteria(
    criteria: Sequence[QueryCriterion],
    *,
    collection_metadata: QueryCollectionMetadata,
    capability_family: CapabilityFamily,
    template_supported_operators: frozenset[QueryOperator] | None = None,
) -> None:
    allowed_operators = supported_operators(capability_family)
    if template_supported_operators is not None:
        allowed_operators = allowed_operators & template_supported_operators

    for criterion in criteria:
        _validate_field_name(criterion.field_name, collection_metadata)
        if criterion.operator not in allowed_operators:
            msg = (
                f"Operator {criterion.operator.value!r} is not allowed for capability "
                f"family {capability_family.value!r} on {collection_metadata.collection_name!r}"
            )
            raise UnsupportedOperatorError(msg)


def _validate_sort(
    sort_fields: Sequence[SortFieldSpec],
    *,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    if len(sort_fields) > 1:
        msg = "Reviewed collection-first reads currently support at most one sort field"
        raise InvalidSortError(msg)

    seen_fields: set[str] = set()
    for sort_field in sort_fields:
        _validate_field_name(sort_field.field_name, collection_metadata)
        if sort_field.field_name in seen_fields:
            msg = f"Duplicate sort field {sort_field.field_name!r} is not allowed"
            raise InvalidSortError(msg)
        seen_fields.add(sort_field.field_name)
        if sort_field.direction not in frozenset(SortDirection):
            msg = f"Unsupported sort direction: {sort_field.direction!r}"
            raise InvalidSortError(msg)


def _validate_pagination(pagination: PaginationSpec) -> None:
    if pagination.limit is not None and pagination.limit < 0:
        msg = "Pagination limit must be >= 0 or None"
        raise InvalidPaginationError(msg)
    if pagination.offset < 0:
        msg = "Pagination offset must be >= 0"
        raise InvalidPaginationError(msg)
    if pagination.limit is None and pagination.offset != 0:
        msg = "Pagination offset requires an explicit limit for reviewed templates"
        raise InvalidPaginationError(msg)


def _validate_aggregate_fields(
    aggregate_fields: Sequence[str],
    *,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    if len(aggregate_fields) > 1:
        msg = "Reviewed aggregation templates currently support at most one aggregate field"
        raise InvalidAggregateFieldError(msg)

    seen_fields: set[str] = set()
    for field_name in aggregate_fields:
        _validate_field_name(field_name, collection_metadata)
        if field_name in seen_fields:
            msg = f"Duplicate aggregate field {field_name!r} is not allowed"
            raise InvalidAggregateFieldError(msg)
        seen_fields.add(field_name)


def _validate_write_payload(
    payload: Mapping[str, object],
    *,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    payload_keys = frozenset(payload)
    forbidden_names = payload_keys & FORBIDDEN_RAW_AQL_BIND_NAMES
    if forbidden_names:
        forbidden_list = ", ".join(sorted(forbidden_names))
        msg = f"Raw AQL fragment keys are not allowed in payloads: {forbidden_list}"
        raise InvalidPayloadError(msg)

    for field_name in payload:
        _validate_field_name(field_name, collection_metadata)


def _validate_match_fields(
    match_fields: Sequence[str],
    *,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    seen_fields: set[str] = set()
    for field_name in match_fields:
        _validate_field_name(field_name, collection_metadata)
        if field_name in seen_fields:
            msg = f"Duplicate match field {field_name!r} is not allowed"
            raise InvalidUniquenessAssumptionError(msg)
        seen_fields.add(field_name)
        field_metadata = collection_metadata.fields[field_name]
        if not field_metadata.unique:
            msg = f"Match field {field_name!r} is not declared unique on {collection_metadata.collection_name!r}"
            raise InvalidUniquenessAssumptionError(msg)


def _validate_field_name(
    field_name: str,
    collection_metadata: QueryCollectionMetadata,
) -> QueryFieldMetadata:
    field_metadata = collection_metadata.fields.get(field_name)
    if field_metadata is None:
        msg = f"Unknown field {field_name!r} for collection {collection_metadata.collection_name!r}"
        raise UnknownFieldError(msg)
    return field_metadata


def _validate_template_result_shape(
    asset: QueryTemplateAsset,
    query_spec: GenericCollectionQuerySpec,
) -> None:
    if isinstance(query_spec, ReadQuerySpec):
        expected_shape = TemplateResultShape.DOCUMENT_LIST
    elif isinstance(query_spec, WriteQuerySpec):
        expected_shape = TemplateResultShape.DOCUMENT_ID_LIST
    elif isinstance(query_spec, AggregateQuerySpec):
        expected_shape = (
            TemplateResultShape.AGGREGATE_ROWS if query_spec.aggregate_fields else TemplateResultShape.COUNT_SCALAR
        )
    else:
        msg = f"Unsupported generic query spec type: {type(query_spec).__name__}"
        raise InvalidTemplateResultShapeError(msg)

    if asset.result_shape != expected_shape:
        msg = (
            f"Template {asset.template_id.value!r} returns {asset.result_shape.value!r}, "
            f"expected {expected_shape.value!r}"
        )
        raise InvalidTemplateResultShapeError(msg)


def _validate_template_bind_requirements(
    asset: QueryTemplateAsset,
    query_spec: GenericCollectionQuerySpec,
) -> None:
    required_bind_names = asset.required_bind_names()
    if "@collection" not in required_bind_names:
        msg = f"Template {asset.template_id.value!r} must bind @collection"
        raise TemplateContractValidationError(msg)

    if isinstance(query_spec, ReadQuerySpec):
        required_names = frozenset({"criteria", "offset", "limit"})
        if query_spec.sort:
            required_names |= frozenset({"sort_field", "sort_direction"})
    elif isinstance(query_spec, WriteQuerySpec):
        required_names = frozenset({"docs"}) if not query_spec.match_fields else frozenset({"docs", "match_fields"})
    elif isinstance(query_spec, AggregateQuerySpec):
        required_names = frozenset({"criteria"})
        if query_spec.aggregate_fields:
            required_names |= frozenset({"aggregate_field", "offset", "limit"})
    else:
        required_names = frozenset()

    missing_required_names = required_names - asset.bind_names()
    if missing_required_names:
        missing_list = ", ".join(sorted(missing_required_names))
        msg = f"Template {asset.template_id.value!r} does not expose required bind names: {missing_list}"
        raise TemplateContractValidationError(msg)


def _validate_bind_value(
    bind_spec: QueryTemplateBindSpec,
    value: object,
    *,
    asset: QueryTemplateAsset,
    collection_metadata: QueryCollectionMetadata | None,
) -> None:
    kind = bind_spec.value_kind
    if kind is TemplateBindValueKind.COLLECTION:
        _validate_collection_bind_value(value)
    elif kind is TemplateBindValueKind.CRITERIA:
        if collection_metadata is None:
            _require_sequence(value, bind_spec.name)
            return
        _validate_bound_criteria(value, asset=asset, collection_metadata=collection_metadata)
    elif kind is TemplateBindValueKind.SORT_FIELD:
        _validate_optional_field_bind(value, bind_spec.name, collection_metadata)
    elif kind is TemplateBindValueKind.SORT_DIRECTION:
        _validate_optional_sort_direction(value, bind_spec.name)
    elif kind is TemplateBindValueKind.LIMIT or kind is TemplateBindValueKind.OFFSET:
        _validate_non_negative_int(value, bind_spec.name)
    elif kind is TemplateBindValueKind.DOCUMENTS:
        _validate_documents_bind(value, bind_spec.name)
    elif kind is TemplateBindValueKind.MATCH_FIELDS:
        _validate_match_fields_bind(value, bind_spec.name, collection_metadata)
    elif kind is TemplateBindValueKind.AGGREGATE_FIELD:
        _validate_required_field_bind(value, bind_spec.name, collection_metadata)
    elif kind is TemplateBindValueKind.QUERY_VECTOR:
        _validate_query_vector(value, bind_spec.name)
    elif kind is TemplateBindValueKind.NPROBE:
        _validate_positive_int(value, bind_spec.name)
    elif kind is TemplateBindValueKind.FILTER_FIELD:
        _validate_optional_field_bind(value, bind_spec.name, collection_metadata)
    elif kind is TemplateBindValueKind.FILTER_VALUE:
        return
    else:
        msg = f"Unhandled bind kind {kind.value!r} for template {asset.template_id.value!r}"
        raise InvalidTemplateBindValueError(msg)


def _validate_template_bind_metadata_affinity(
    bind_vars: Mapping[str, object],
    *,
    asset: QueryTemplateAsset,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    collection_name = bind_vars.get("@collection")
    if collection_name is not None and collection_name != collection_metadata.collection_name:
        msg = (
            f"Template {asset.template_id.value!r} bound @collection={collection_name!r} "
            f"but metadata targets {collection_metadata.collection_name!r}"
        )
        raise TemplateBindValidationError(msg)

    sort_field = bind_vars.get("sort_field")
    sort_direction = bind_vars.get("sort_direction")
    if sort_field is None and sort_direction is not None:
        msg = "sort_direction requires a metadata-approved sort_field"
        raise InvalidTemplateBindValueError(msg)

    filter_field = bind_vars.get("filter_field")
    filter_value = bind_vars.get("filter_value")
    if filter_field is None and filter_value is not None:
        msg = "filter_value requires a metadata-approved filter_field"
        raise InvalidTemplateBindValueError(msg)


def _validate_collection_bind_value(value: object) -> None:
    if not isinstance(value, str) or not value:
        msg = "@collection bind value must be a non-empty string"
        raise InvalidTemplateBindValueError(msg)
    if not _COLLECTION_NAME_PATTERN.fullmatch(value):
        msg = f"@collection bind value {value!r} is not a reviewed collection name"
        raise InvalidTemplateBindValueError(msg)


def _validate_bound_criteria(
    value: object,
    *,
    asset: QueryTemplateAsset,
    collection_metadata: QueryCollectionMetadata,
) -> None:
    criteria_values = _require_sequence(value, "criteria")
    normalized_criteria = tuple(_coerce_query_criterion(item) for item in criteria_values)
    _validate_criteria(
        normalized_criteria,
        collection_metadata=collection_metadata,
        capability_family=asset.capability_family,
        template_supported_operators=asset.supported_operators,
    )


def _coerce_query_criterion(value: object) -> QueryCriterion:
    if isinstance(value, QueryCriterion):
        return value
    if not isinstance(value, Mapping):
        msg = "criteria entries must be QueryCriterion objects or mappings"
        raise InvalidTemplateBindValueError(msg)

    field_name = value.get("field_name")
    operator = value.get("operator")
    if not isinstance(field_name, str):
        msg = "criteria field_name must be a string"
        raise InvalidTemplateBindValueError(msg)
    try:
        normalized_operator = operator if isinstance(operator, QueryOperator) else QueryOperator(str(operator))
    except ValueError as exc:
        msg = f"criteria operator {operator!r} is not a reviewed query operator"
        raise InvalidTemplateBindValueError(msg) from exc

    return QueryCriterion(
        field_name=field_name,
        operator=normalized_operator,
        value=value.get("value"),
    )


def _validate_optional_field_bind(
    value: object,
    bind_name: str,
    collection_metadata: QueryCollectionMetadata | None,
) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value:
        msg = f"{bind_name} must be a non-empty string or None"
        raise InvalidTemplateBindValueError(msg)
    if collection_metadata is not None:
        _validate_field_name(value, collection_metadata)


def _validate_required_field_bind(
    value: object,
    bind_name: str,
    collection_metadata: QueryCollectionMetadata | None,
) -> None:
    if not isinstance(value, str) or not value:
        msg = f"{bind_name} must be a non-empty string"
        raise InvalidTemplateBindValueError(msg)
    if collection_metadata is not None:
        _validate_field_name(value, collection_metadata)


def _validate_optional_sort_direction(value: object, bind_name: str) -> None:
    if value is None:
        return
    try:
        SortDirection(str(value))
    except ValueError as exc:
        msg = f"{bind_name} must be one of: asc, desc"
        raise InvalidTemplateBindValueError(msg) from exc


def _validate_non_negative_int(value: object, bind_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool):
        msg = f"{bind_name} must be an integer"
        raise InvalidTemplateBindValueError(msg)
    if value < 0:
        msg = f"{bind_name} must be >= 0"
        raise InvalidTemplateBindValueError(msg)


def _validate_positive_int(value: object, bind_name: str) -> None:
    _validate_non_negative_int(value, bind_name)
    assert isinstance(value, int)
    if value <= 0:
        msg = f"{bind_name} must be > 0"
        raise InvalidTemplateBindValueError(msg)


def _validate_documents_bind(value: object, bind_name: str) -> None:
    docs = _require_sequence(value, bind_name)
    for index, doc in enumerate(docs):
        if not isinstance(doc, Mapping):
            msg = f"{bind_name}[{index}] must be a mapping"
            raise InvalidTemplateBindValueError(msg)
        forbidden_names = frozenset(doc) & FORBIDDEN_RAW_AQL_BIND_NAMES
        if forbidden_names:
            forbidden_list = ", ".join(sorted(forbidden_names))
            msg = f"{bind_name}[{index}] contains raw-AQL fragment keys: {forbidden_list}"
            raise RawAQLBindEscapeHatchError(msg)


def _validate_match_fields_bind(
    value: object,
    bind_name: str,
    collection_metadata: QueryCollectionMetadata | None,
) -> None:
    match_fields = _require_sequence(value, bind_name)
    if collection_metadata is None:
        for index, field_name in enumerate(match_fields):
            if not isinstance(field_name, str) or not field_name:
                msg = f"{bind_name}[{index}] must be a non-empty string"
                raise InvalidTemplateBindValueError(msg)
        return
    _validate_match_fields(
        tuple(str(field_name) for field_name in match_fields),
        collection_metadata=collection_metadata,
    )


def _validate_query_vector(value: object, bind_name: str) -> None:
    vector = _require_sequence(value, bind_name)
    if not vector:
        msg = f"{bind_name} must contain at least one numeric element"
        raise InvalidTemplateBindValueError(msg)
    for index, element in enumerate(vector):
        if not isinstance(element, int | float) or isinstance(element, bool):
            msg = f"{bind_name}[{index}] must be numeric"
            raise InvalidTemplateBindValueError(msg)


def _require_sequence(value: object, bind_name: str) -> Sequence[object]:
    if isinstance(value, str | bytes | bytearray) or not isinstance(value, Sequence):
        msg = f"{bind_name} must be a sequence"
        raise InvalidTemplateBindValueError(msg)
    return value


__all__ = [
    "AQLParseExplainValidationError",
    "AQLValidationError",
    "AQLValidationReport",
    "AQLValidationStatus",
    "CollectionMetadataInput",
    "CollectionMetadataMap",
    "CriterionInput",
    "DuplicateCollectionMetadataError",
    "InvalidAggregateFieldError",
    "InvalidCapabilityForCollectionError",
    "InvalidPaginationError",
    "InvalidPayloadError",
    "InvalidSortError",
    "InvalidTemplateBindValueError",
    "InvalidTemplateResultShapeError",
    "InvalidUniquenessAssumptionError",
    "QuerySpecValidationError",
    "RawAQLBindEscapeHatchError",
    "TemplateBindValidationError",
    "TemplateContractValidationError",
    "UnknownCollectionError",
    "UnknownFieldError",
    "UnsupportedOperatorError",
    "ValidatedTemplateContract",
    "materialize_collection_metadata",
    "validate_bound_aql",
    "validate_first_party_aql",
    "validate_query_spec",
    "validate_spec_template_contract",
    "validate_template_bindings",
]
