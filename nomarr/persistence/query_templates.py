"""Fixed first-party AQL template assets for collection-first persistence.

This module is intentionally side-effect free. It defines a closed, reviewed
registry of AQL template assets that later validation/binding code can use
without accepting raw AQL fragments from callers.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from .query_specs import CapabilityFamily, QueryOperator


class QueryTemplateId(StrEnum):
    """Closed identifiers for reviewed first-party AQL templates."""

    DOCUMENT_READ_LIST_BY_CRITERIA = "document_read.list_by_criteria"
    DOCUMENT_WRITE_INSERT_MANY = "document_write.insert_many"
    DOCUMENT_WRITE_UPSERT_MANY = "document_write.upsert_many"
    AGGREGATION_COUNT_BY_CRITERIA = "aggregation.count_by_criteria"
    AGGREGATION_FIELD_COUNTS = "aggregation.field_counts"
    ANN_SEARCH_APPROX_NEAR_COSINE = "ann_search.approx_near_cosine"


class TemplateBindValueKind(StrEnum):
    """Typed categories for supported bind variables."""

    COLLECTION = "collection"
    CRITERIA = "criteria"
    SORT_FIELD = "sort_field"
    SORT_DIRECTION = "sort_direction"
    LIMIT = "limit"
    OFFSET = "offset"
    DOCUMENTS = "documents"
    MATCH_FIELDS = "match_fields"
    AGGREGATE_FIELD = "aggregate_field"
    QUERY_VECTOR = "query_vector"
    NPROBE = "nprobe"
    FILTER_FIELD = "filter_field"
    FILTER_VALUE = "filter_value"


class TemplateResultShape(StrEnum):
    """Normalized result shapes promised by first-party templates."""

    DOCUMENT_LIST = "document_list"
    DOCUMENT_ID_LIST = "document_id_list"
    COUNT_SCALAR = "count_scalar"
    AGGREGATE_ROWS = "aggregate_rows"
    ANN_SEARCH_ROWS = "ann_search_rows"


@dataclass(frozen=True)
class QueryTemplateBindSpec:
    """One reviewed bind-variable contract for a first-party template."""

    name: str
    value_kind: TemplateBindValueKind
    description: str
    required: bool = True


@dataclass(frozen=True)
class QueryTemplateAsset:
    """Reviewed first-party AQL template plus its bind/result contract."""

    template_id: QueryTemplateId
    capability_family: CapabilityFamily
    aql: str
    bind_specs: tuple[QueryTemplateBindSpec, ...]
    supported_operators: frozenset[QueryOperator]
    result_shape: TemplateResultShape
    description: str

    def bind_names(self) -> frozenset[str]:
        """Return all accepted bind-variable names for this template."""

        return frozenset(spec.name for spec in self.bind_specs)

    def required_bind_names(self) -> frozenset[str]:
        """Return the required bind-variable names for this template."""

        return frozenset(spec.name for spec in self.bind_specs if spec.required)


@dataclass(frozen=True)
class BoundQueryTemplate:
    """A validated binding of a reviewed first-party template asset."""

    template_id: QueryTemplateId
    capability_family: CapabilityFamily
    aql: str
    bind_vars: Mapping[str, object]
    result_shape: TemplateResultShape


FORBIDDEN_RAW_AQL_BIND_NAMES = frozenset(
    {
        "aql",
        "raw_aql",
        "filter_fragment",
        "filter_clause",
        "sort_fragment",
        "sort_clause",
        "return_fragment",
        "collection_fragment",
    }
)

_CRITERIA_FILTER_BLOCK = """
FILTER LENGTH(@criteria) == 0
    OR ALL criterion IN @criteria SATISFIES
        (
            criterion.operator == \"eq\" AND doc[criterion.field_name] == criterion.value
        )
        OR (
            criterion.operator == \"in\" AND criterion.value != null AND doc[criterion.field_name] IN criterion.value
        )
        OR (
            criterion.operator == \"gte\" AND doc[criterion.field_name] >= criterion.value
        )
        OR (
            criterion.operator == \"lte\" AND doc[criterion.field_name] <= criterion.value
        )
        OR (
            criterion.operator == \"like\" AND LIKE(TO_STRING(doc[criterion.field_name]), criterion.value, true)
        )
    END
""".strip()

FIRST_PARTY_QUERY_TEMPLATES: Mapping[QueryTemplateId, QueryTemplateAsset] = MappingProxyType(
    {
        QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA: QueryTemplateAsset(
            template_id=QueryTemplateId.DOCUMENT_READ_LIST_BY_CRITERIA,
            capability_family=CapabilityFamily.DOCUMENT_READ,
            aql=(
                "FOR doc IN @@collection\n"
                f"    {_CRITERIA_FILTER_BLOCK}\n"
                "    SORT\n"
                '        @sort_field == null OR @sort_direction != "asc" ? null : doc[@sort_field] ASC,\n'
                '        @sort_field == null OR @sort_direction != "desc" ? null : doc[@sort_field] DESC\n'
                "    LIMIT @offset, @limit\n"
                "    RETURN doc"
            ),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target collection bind variable for the reviewed read template.",
                ),
                QueryTemplateBindSpec(
                    name="criteria",
                    value_kind=TemplateBindValueKind.CRITERIA,
                    description="Validated collection-first criteria payload.",
                ),
                QueryTemplateBindSpec(
                    name="sort_field",
                    value_kind=TemplateBindValueKind.SORT_FIELD,
                    description="Optional metadata-approved field name for sorting.",
                    required=False,
                ),
                QueryTemplateBindSpec(
                    name="sort_direction",
                    value_kind=TemplateBindValueKind.SORT_DIRECTION,
                    description="Optional sort direction for the chosen sort field.",
                    required=False,
                ),
                QueryTemplateBindSpec(
                    name="offset",
                    value_kind=TemplateBindValueKind.OFFSET,
                    description="Pagination offset for reviewed read queries.",
                ),
                QueryTemplateBindSpec(
                    name="limit",
                    value_kind=TemplateBindValueKind.LIMIT,
                    description="Pagination limit for reviewed read queries.",
                ),
            ),
            supported_operators=frozenset(QueryOperator),
            result_shape=TemplateResultShape.DOCUMENT_LIST,
            description="Generic collection-first document reads with validated criteria, optional single-field sort, and pagination.",
        ),
        QueryTemplateId.DOCUMENT_WRITE_INSERT_MANY: QueryTemplateAsset(
            template_id=QueryTemplateId.DOCUMENT_WRITE_INSERT_MANY,
            capability_family=CapabilityFamily.DOCUMENT_WRITE,
            aql=("FOR doc IN @docs\n    INSERT doc INTO @@collection\n    RETURN NEW._id"),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target collection bind variable for batch inserts.",
                ),
                QueryTemplateBindSpec(
                    name="docs",
                    value_kind=TemplateBindValueKind.DOCUMENTS,
                    description="Documents to insert with no raw AQL fragments.",
                ),
            ),
            supported_operators=frozenset(),
            result_shape=TemplateResultShape.DOCUMENT_ID_LIST,
            description="Batch insert of reviewed document payloads into a target collection.",
        ),
        QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY: QueryTemplateAsset(
            template_id=QueryTemplateId.DOCUMENT_WRITE_UPSERT_MANY,
            capability_family=CapabilityFamily.DOCUMENT_WRITE,
            aql=(
                "FOR doc IN @docs\n"
                "    LET search = MERGE(\n"
                "        FOR field_name IN @match_fields\n"
                "            RETURN { [field_name]: doc[field_name] }\n"
                "    )\n"
                "    UPSERT search\n"
                "        INSERT doc\n"
                "        UPDATE doc\n"
                "    IN @@collection\n"
                "    RETURN NEW._id"
            ),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target collection bind variable for batch upserts.",
                ),
                QueryTemplateBindSpec(
                    name="docs",
                    value_kind=TemplateBindValueKind.DOCUMENTS,
                    description="Documents to upsert with reviewed match keys.",
                ),
                QueryTemplateBindSpec(
                    name="match_fields",
                    value_kind=TemplateBindValueKind.MATCH_FIELDS,
                    description="Validated unique/match field names used to build the UPSERT search object.",
                ),
            ),
            supported_operators=frozenset(),
            result_shape=TemplateResultShape.DOCUMENT_ID_LIST,
            description="Batch upsert using reviewed match-field metadata rather than caller-provided raw AQL.",
        ),
        QueryTemplateId.AGGREGATION_COUNT_BY_CRITERIA: QueryTemplateAsset(
            template_id=QueryTemplateId.AGGREGATION_COUNT_BY_CRITERIA,
            capability_family=CapabilityFamily.AGGREGATION,
            aql=(
                "FOR doc IN @@collection\n"
                f"    {_CRITERIA_FILTER_BLOCK}\n"
                "    COLLECT WITH COUNT INTO count\n"
                "    RETURN count"
            ),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target collection bind variable for reviewed count queries.",
                ),
                QueryTemplateBindSpec(
                    name="criteria",
                    value_kind=TemplateBindValueKind.CRITERIA,
                    description="Validated criteria payload used for counting.",
                ),
            ),
            supported_operators=frozenset(QueryOperator),
            result_shape=TemplateResultShape.COUNT_SCALAR,
            description="Count documents using the same validated criteria model as collection-first reads.",
        ),
        QueryTemplateId.AGGREGATION_FIELD_COUNTS: QueryTemplateAsset(
            template_id=QueryTemplateId.AGGREGATION_FIELD_COUNTS,
            capability_family=CapabilityFamily.AGGREGATION,
            aql=(
                "FOR doc IN @@collection\n"
                f"    {_CRITERIA_FILTER_BLOCK}\n"
                "    COLLECT value = doc[@aggregate_field] WITH COUNT INTO count\n"
                "    LIMIT @offset, @limit\n"
                "    RETURN {value: value, count: count}"
            ),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target collection bind variable for reviewed aggregation queries.",
                ),
                QueryTemplateBindSpec(
                    name="criteria",
                    value_kind=TemplateBindValueKind.CRITERIA,
                    description="Validated criteria payload used before aggregation.",
                ),
                QueryTemplateBindSpec(
                    name="aggregate_field",
                    value_kind=TemplateBindValueKind.AGGREGATE_FIELD,
                    description="Metadata-approved field to aggregate/count by.",
                ),
                QueryTemplateBindSpec(
                    name="offset",
                    value_kind=TemplateBindValueKind.OFFSET,
                    description="Pagination offset for aggregate result rows.",
                ),
                QueryTemplateBindSpec(
                    name="limit",
                    value_kind=TemplateBindValueKind.LIMIT,
                    description="Pagination limit for aggregate result rows.",
                ),
            ),
            supported_operators=frozenset(QueryOperator),
            result_shape=TemplateResultShape.AGGREGATE_ROWS,
            description="Distinct field-value counts for collection-first aggregation work.",
        ),
        QueryTemplateId.ANN_SEARCH_APPROX_NEAR_COSINE: QueryTemplateAsset(
            template_id=QueryTemplateId.ANN_SEARCH_APPROX_NEAR_COSINE,
            capability_family=CapabilityFamily.ANN_SEARCH,
            aql=(
                "FOR doc IN @@collection\n"
                "    LET score = APPROX_NEAR_COSINE(doc.vector_n, @query_vector, {nProbe: @nprobe})\n"
                "    FILTER @filter_field == null\n"
                "        OR @filter_value IN doc[@filter_field]\n"
                "        OR doc[@filter_field] == @filter_value\n"
                "    SORT score DESC\n"
                "    LIMIT @limit\n"
                "    RETURN MERGE(doc, {score: score})"
            ),
            bind_specs=(
                QueryTemplateBindSpec(
                    name="@collection",
                    value_kind=TemplateBindValueKind.COLLECTION,
                    description="Target vector collection bind variable for ANN search.",
                ),
                QueryTemplateBindSpec(
                    name="query_vector",
                    value_kind=TemplateBindValueKind.QUERY_VECTOR,
                    description="Query vector for APPROX_NEAR_COSINE.",
                ),
                QueryTemplateBindSpec(
                    name="nprobe",
                    value_kind=TemplateBindValueKind.NPROBE,
                    description="ANN search probe count.",
                ),
                QueryTemplateBindSpec(
                    name="limit",
                    value_kind=TemplateBindValueKind.LIMIT,
                    description="Maximum ANN hits to return.",
                ),
                QueryTemplateBindSpec(
                    name="filter_field",
                    value_kind=TemplateBindValueKind.FILTER_FIELD,
                    description="Optional metadata-approved filter field for representative ANN validation cases.",
                    required=False,
                ),
                QueryTemplateBindSpec(
                    name="filter_value",
                    value_kind=TemplateBindValueKind.FILTER_VALUE,
                    description="Optional single filter value paired with filter_field.",
                    required=False,
                ),
            ),
            supported_operators=frozenset({QueryOperator.EQ, QueryOperator.IN}),
            result_shape=TemplateResultShape.ANN_SEARCH_ROWS,
            description="Representative vector-native ANN search template with optional single-field filtering.",
        ),
    }
)

FIRST_PARTY_TEMPLATE_IDS = frozenset(FIRST_PARTY_QUERY_TEMPLATES)

FIRST_PARTY_QUERY_TEMPLATES_BY_FAMILY: Mapping[CapabilityFamily, tuple[QueryTemplateAsset, ...]] = MappingProxyType(
    {
        family: tuple(
            template for template in FIRST_PARTY_QUERY_TEMPLATES.values() if template.capability_family == family
        )
        for family in CapabilityFamily
    }
)


def template_asset(template_id: QueryTemplateId | str) -> QueryTemplateAsset:
    """Return one reviewed first-party template asset by its fixed identifier."""

    try:
        normalized_template_id = QueryTemplateId(template_id)
    except ValueError as exc:
        msg = f"Unknown first-party query template: {template_id}"
        raise KeyError(msg) from exc
    return FIRST_PARTY_QUERY_TEMPLATES[normalized_template_id]


def iter_first_party_query_templates(
    *,
    capability_family: CapabilityFamily | None = None,
) -> tuple[QueryTemplateAsset, ...]:
    """Enumerate reviewed first-party query template assets for tests and CI."""

    if capability_family is None:
        return tuple(FIRST_PARTY_QUERY_TEMPLATES.values())
    return FIRST_PARTY_QUERY_TEMPLATES_BY_FAMILY[capability_family]


def validate_template_bind_contract(
    template: QueryTemplateAsset | QueryTemplateId | str,
    bind_vars: Mapping[str, object],
) -> None:
    """Reject incomplete or non-reviewed bind contracts for a first-party template."""

    asset = template if isinstance(template, QueryTemplateAsset) else template_asset(template)
    provided_names = frozenset(bind_vars)
    forbidden_names = provided_names & FORBIDDEN_RAW_AQL_BIND_NAMES
    if forbidden_names:
        forbidden_list = ", ".join(sorted(forbidden_names))
        msg = f"Raw AQL fragments are not allowed in template binds: {forbidden_list}"
        raise ValueError(msg)

    missing_names = asset.required_bind_names() - provided_names
    if missing_names:
        missing_list = ", ".join(sorted(missing_names))
        msg = f"Incomplete bind contract for {asset.template_id}: missing {missing_list}"
        raise ValueError(msg)

    unexpected_names = provided_names - asset.bind_names()
    if unexpected_names:
        unexpected_list = ", ".join(sorted(unexpected_names))
        msg = f"Unexpected bind variables for {asset.template_id}: {unexpected_list}"
        raise ValueError(msg)


def bind_first_party_query_template(
    template_id: QueryTemplateId | str,
    bind_vars: Mapping[str, object],
) -> BoundQueryTemplate:
    """Bind a reviewed first-party template after enforcing its closed contract."""

    asset = template_asset(template_id)
    validate_template_bind_contract(asset, bind_vars)
    return BoundQueryTemplate(
        template_id=asset.template_id,
        capability_family=asset.capability_family,
        aql=asset.aql,
        bind_vars=MappingProxyType(dict(bind_vars)),
        result_shape=asset.result_shape,
    )


__all__ = [
    "FIRST_PARTY_QUERY_TEMPLATES",
    "FIRST_PARTY_QUERY_TEMPLATES_BY_FAMILY",
    "FIRST_PARTY_TEMPLATE_IDS",
    "FORBIDDEN_RAW_AQL_BIND_NAMES",
    "BoundQueryTemplate",
    "QueryTemplateAsset",
    "QueryTemplateBindSpec",
    "QueryTemplateId",
    "TemplateBindValueKind",
    "TemplateResultShape",
    "bind_first_party_query_template",
    "iter_first_party_query_templates",
    "template_asset",
    "validate_template_bind_contract",
]
