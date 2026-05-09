"""Canonical Part A metadata contracts for collection-first query specs.

This module is intentionally side-effect free. It separates:

- capability-family taxonomy
- validated query-spec payload shapes
- collection metadata contracts
- public naming grammar metadata

It does **not** define the public Python API surface or compile AQL directly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol


class CollectionFamily(StrEnum):
    """Normalized collection-family types used by query-spec validation."""

    BASE = "base"
    DOCUMENT = "document"
    EDGE = "edge"
    VECTOR = "vector"
    STATE_GRAPH = "state_graph"


class CapabilityFamily(StrEnum):
    """Closed capability-family taxonomy for collection-first persistence."""

    DOCUMENT_READ = "document_read"
    DOCUMENT_WRITE = "document_write"
    AGGREGATION = "aggregation"
    RELATIONSHIP_NATIVE = "relationship_native"
    STATE_NATIVE = "state_native"
    ANN_SEARCH = "ann_search"
    ADMINISTRATIVE_MAINTENANCE = "administrative_maintenance"


class QueryOperator(StrEnum):
    """Operator forms carried as data inside validated query specs."""

    EQ = "eq"
    IN = "in"
    GTE = "gte"
    LTE = "lte"
    LIKE = "like"


class SortDirection(StrEnum):
    """Supported sort directions for declarative collection-first reads."""

    ASC = "asc"
    DESC = "desc"


class PublicCapabilityRoot(StrEnum):
    """Closed naming roots reserved for normalized persistence families."""

    READ = "read"
    WRITE = "write"
    AGGREGATE = "aggregate"
    RELATIONSHIP = "relationship"
    STATE = "state"
    ANN_SEARCH = "ann_search"
    ADMIN = "admin"


@dataclass(frozen=True)
class CapabilityFamilyMetadata:
    """Metadata describing one normalized persistence capability family."""

    family: CapabilityFamily
    allowed_collection_families: frozenset[CollectionFamily]
    allowed_operators: frozenset[QueryOperator]
    storage_native: bool
    description: str


@dataclass(frozen=True)
class PublicNamingGrammar:
    """Closed naming grammar for future normalized collection-first APIs."""

    allowed_roots_by_family: Mapping[CapabilityFamily, frozenset[PublicCapabilityRoot]]
    generic_roots: frozenset[PublicCapabilityRoot]
    storage_native_roots: frozenset[PublicCapabilityRoot]
    operator_names: frozenset[str]


@dataclass(frozen=True)
class QueryFieldMetadata:
    """Minimal field metadata needed for query-spec validation."""

    name: str
    unique: bool = False


@dataclass(frozen=True)
class QueryCollectionMetadata:
    """Minimal collection metadata needed for query-spec validation."""

    collection_name: str
    collection_family: CollectionFamily
    fields: Mapping[str, QueryFieldMetadata]

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(self.fields)

    @property
    def unique_field_names(self) -> frozenset[str]:
        return frozenset(field_name for field_name, metadata in self.fields.items() if metadata.unique)


@dataclass(frozen=True)
class QueryCriterion:
    """One validated criterion inside a collection-first query spec."""

    field_name: str
    operator: QueryOperator
    value: object


@dataclass(frozen=True)
class SortFieldSpec:
    """Declarative sort clause for a collection-first read/aggregate spec."""

    field_name: str
    direction: SortDirection = SortDirection.ASC


@dataclass(frozen=True)
class PaginationSpec:
    """Declarative pagination payload for collection-first query specs."""

    limit: int | None = None
    offset: int = 0


@dataclass(frozen=True)
class ReadQuerySpec:
    """Validated payload shape for generic document-read operations."""

    collection_name: str
    criteria: tuple[QueryCriterion, ...] = ()
    sort: tuple[SortFieldSpec, ...] = ()
    pagination: PaginationSpec = field(default_factory=PaginationSpec)
    capability_family: CapabilityFamily = field(
        default=CapabilityFamily.DOCUMENT_READ,
        init=False,
    )


@dataclass(frozen=True)
class WriteQuerySpec:
    """Validated payload shape for generic document-write operations."""

    collection_name: str
    criteria: tuple[QueryCriterion, ...] = ()
    payload: Mapping[str, object] = field(default_factory=dict)
    match_fields: tuple[str, ...] = ()
    capability_family: CapabilityFamily = field(
        default=CapabilityFamily.DOCUMENT_WRITE,
        init=False,
    )


@dataclass(frozen=True)
class AggregateQuerySpec:
    """Validated payload shape for generic aggregation/count operations."""

    collection_name: str
    criteria: tuple[QueryCriterion, ...] = ()
    aggregate_fields: tuple[str, ...] = ()
    pagination: PaginationSpec = field(default_factory=PaginationSpec)
    capability_family: CapabilityFamily = field(
        default=CapabilityFamily.AGGREGATION,
        init=False,
    )


GenericCollectionQuerySpec = ReadQuerySpec | WriteQuerySpec | AggregateQuerySpec

GENERIC_COLLECTION_FAMILIES = frozenset(
    {
        CollectionFamily.DOCUMENT,
        CollectionFamily.EDGE,
        CollectionFamily.VECTOR,
        CollectionFamily.STATE_GRAPH,
    }
)

GENERIC_CAPABILITY_FAMILIES = frozenset(
    {
        CapabilityFamily.DOCUMENT_READ,
        CapabilityFamily.DOCUMENT_WRITE,
        CapabilityFamily.AGGREGATION,
        CapabilityFamily.ADMINISTRATIVE_MAINTENANCE,
    }
)

STORAGE_NATIVE_CAPABILITY_FAMILIES = frozenset(
    {
        CapabilityFamily.RELATIONSHIP_NATIVE,
        CapabilityFamily.STATE_NATIVE,
        CapabilityFamily.ANN_SEARCH,
    }
)

CAPABILITY_FAMILY_METADATA = MappingProxyType(
    {
        CapabilityFamily.DOCUMENT_READ: CapabilityFamilyMetadata(
            family=CapabilityFamily.DOCUMENT_READ,
            allowed_collection_families=GENERIC_COLLECTION_FAMILIES,
            allowed_operators=frozenset(QueryOperator),
            storage_native=False,
            description="Generic collection-first document reads with criteria as data.",
        ),
        CapabilityFamily.DOCUMENT_WRITE: CapabilityFamilyMetadata(
            family=CapabilityFamily.DOCUMENT_WRITE,
            allowed_collection_families=GENERIC_COLLECTION_FAMILIES,
            allowed_operators=frozenset(
                {
                    QueryOperator.EQ,
                    QueryOperator.IN,
                }
            ),
            storage_native=False,
            description="Generic collection-first document writes matched by reviewed criteria.",
        ),
        CapabilityFamily.AGGREGATION: CapabilityFamilyMetadata(
            family=CapabilityFamily.AGGREGATION,
            allowed_collection_families=GENERIC_COLLECTION_FAMILIES,
            allowed_operators=frozenset(QueryOperator),
            storage_native=False,
            description="Storage-shaped counts and aggregate summaries over reviewed fields.",
        ),
        CapabilityFamily.RELATIONSHIP_NATIVE: CapabilityFamilyMetadata(
            family=CapabilityFamily.RELATIONSHIP_NATIVE,
            allowed_collection_families=frozenset(
                {
                    CollectionFamily.DOCUMENT,
                    CollectionFamily.STATE_GRAPH,
                }
            ),
            allowed_operators=frozenset(),
            storage_native=True,
            description="Graph-native traversal/cascade capabilities justified by EDGES metadata.",
        ),
        CapabilityFamily.STATE_NATIVE: CapabilityFamilyMetadata(
            family=CapabilityFamily.STATE_NATIVE,
            allowed_collection_families=frozenset({CollectionFamily.STATE_GRAPH}),
            allowed_operators=frozenset(),
            storage_native=True,
            description="Atomic state-graph primitives that remain storage-native.",
        ),
        CapabilityFamily.ANN_SEARCH: CapabilityFamilyMetadata(
            family=CapabilityFamily.ANN_SEARCH,
            allowed_collection_families=frozenset({CollectionFamily.VECTOR}),
            allowed_operators=frozenset(
                {
                    QueryOperator.EQ,
                    QueryOperator.IN,
                }
            ),
            storage_native=True,
            description="ANN/vector-native search separated from ordinary generic helpers.",
        ),
        CapabilityFamily.ADMINISTRATIVE_MAINTENANCE: CapabilityFamilyMetadata(
            family=CapabilityFamily.ADMINISTRATIVE_MAINTENANCE,
            allowed_collection_families=GENERIC_COLLECTION_FAMILIES,
            allowed_operators=frozenset(),
            storage_native=False,
            description="Narrow storage-maintenance primitives such as truncate.",
        ),
    }
)

PUBLIC_NAMING_GRAMMAR = PublicNamingGrammar(
    allowed_roots_by_family=MappingProxyType(
        {
            CapabilityFamily.DOCUMENT_READ: frozenset({PublicCapabilityRoot.READ}),
            CapabilityFamily.DOCUMENT_WRITE: frozenset({PublicCapabilityRoot.WRITE}),
            CapabilityFamily.AGGREGATION: frozenset({PublicCapabilityRoot.AGGREGATE}),
            CapabilityFamily.RELATIONSHIP_NATIVE: frozenset({PublicCapabilityRoot.RELATIONSHIP}),
            CapabilityFamily.STATE_NATIVE: frozenset({PublicCapabilityRoot.STATE}),
            CapabilityFamily.ANN_SEARCH: frozenset({PublicCapabilityRoot.ANN_SEARCH}),
            CapabilityFamily.ADMINISTRATIVE_MAINTENANCE: frozenset({PublicCapabilityRoot.ADMIN}),
        }
    ),
    generic_roots=frozenset(
        {
            PublicCapabilityRoot.READ,
            PublicCapabilityRoot.WRITE,
            PublicCapabilityRoot.AGGREGATE,
            PublicCapabilityRoot.ADMIN,
        }
    ),
    storage_native_roots=frozenset(
        {
            PublicCapabilityRoot.RELATIONSHIP,
            PublicCapabilityRoot.STATE,
            PublicCapabilityRoot.ANN_SEARCH,
        }
    ),
    operator_names=frozenset(operator.value for operator in QueryOperator),
)


class SupportsQueryMetadata(Protocol):
    """Protocol for persistence objects that can expose query metadata."""

    def _query_collection_metadata(self) -> Mapping[str, object]: ...


def capability_metadata(family: CapabilityFamily) -> CapabilityFamilyMetadata:
    """Return metadata for one normalized capability family."""

    return CAPABILITY_FAMILY_METADATA[family]


def supported_collection_families(
    family: CapabilityFamily,
) -> frozenset[CollectionFamily]:
    """Return the allowed collection families for one capability family."""

    return capability_metadata(family).allowed_collection_families


def supported_operators(family: CapabilityFamily) -> frozenset[QueryOperator]:
    """Return the allowed operators for one capability family."""

    return capability_metadata(family).allowed_operators


def is_collection_family_supported(
    capability_family: CapabilityFamily,
    collection_family: CollectionFamily,
) -> bool:
    """Return whether a collection family supports the given capability family."""

    return collection_family in supported_collection_families(capability_family)


def is_storage_native_capability_family(family: CapabilityFamily) -> bool:
    """Return whether a capability family is reserved for storage-native semantics."""

    return capability_metadata(family).storage_native


def allowed_public_roots(
    family: CapabilityFamily,
) -> frozenset[PublicCapabilityRoot]:
    """Return the closed set of public naming roots allowed for a family."""

    return PUBLIC_NAMING_GRAMMAR.allowed_roots_by_family[family]


def is_operator_name(name: str) -> bool:
    """Return whether ``name`` is reserved as a data operator, not an API root."""

    return name in PUBLIC_NAMING_GRAMMAR.operator_names


def is_allowed_public_capability_root(
    root_name: str,
    family: CapabilityFamily,
) -> bool:
    """Return whether a public capability root obeys the normalized naming grammar."""

    try:
        root = PublicCapabilityRoot(root_name)
    except ValueError:
        return False
    return root in allowed_public_roots(family)


def collection_metadata_from_provider(
    provider: SupportsQueryMetadata,
) -> QueryCollectionMetadata:
    """Build typed collection metadata from a persistence metadata provider."""

    raw_metadata = provider._query_collection_metadata()
    collection_name = str(raw_metadata["collection_name"])
    collection_family = CollectionFamily(str(raw_metadata["collection_family"]))
    raw_fields = raw_metadata["fields"]
    if not isinstance(raw_fields, Mapping):
        msg = "fields metadata must be a mapping"
        raise TypeError(msg)

    fields: dict[str, QueryFieldMetadata] = {}
    for field_name, raw_field in raw_fields.items():
        if not isinstance(raw_field, Mapping):
            msg = "field metadata entries must be mappings"
            raise TypeError(msg)
        normalized_name = str(raw_field.get("name", field_name))
        fields[str(field_name)] = QueryFieldMetadata(
            name=normalized_name,
            unique=bool(raw_field.get("unique", False)),
        )

    return QueryCollectionMetadata(
        collection_name=collection_name,
        collection_family=collection_family,
        fields=fields,
    )


__all__ = [
    "CAPABILITY_FAMILY_METADATA",
    "GENERIC_CAPABILITY_FAMILIES",
    "GENERIC_COLLECTION_FAMILIES",
    "PUBLIC_NAMING_GRAMMAR",
    "STORAGE_NATIVE_CAPABILITY_FAMILIES",
    "AggregateQuerySpec",
    "CapabilityFamily",
    "CapabilityFamilyMetadata",
    "CollectionFamily",
    "GenericCollectionQuerySpec",
    "PaginationSpec",
    "PublicCapabilityRoot",
    "PublicNamingGrammar",
    "QueryCollectionMetadata",
    "QueryCriterion",
    "QueryFieldMetadata",
    "QueryOperator",
    "ReadQuerySpec",
    "SortDirection",
    "SortFieldSpec",
    "SupportsQueryMetadata",
    "WriteQuerySpec",
    "allowed_public_roots",
    "capability_metadata",
    "collection_metadata_from_provider",
    "is_allowed_public_capability_root",
    "is_collection_family_supported",
    "is_operator_name",
    "is_storage_native_capability_family",
    "supported_collection_families",
    "supported_operators",
]
