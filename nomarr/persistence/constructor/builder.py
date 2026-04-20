"""Schema constructor — builds namespace objects from declarative schema.

SchemaConstructor validates the schema at instantiation time and builds
CollectionNamespace objects that provide the nested accessor API.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.namespaces import CollectionNamespace
from nomarr.persistence.schema import SCHEMA, CollectionType, SchemaValidationError


class SchemaConstructor:
    """Builds namespace objects from the persistence schema.

    Validates the schema at import time. Raises SchemaValidationError
    immediately if the schema contains invalid declarations.
    """

    def __init__(self, db: SafeDatabase) -> None:
        """Initialize with an ArangoDB database handle.

        Args:
            db: ArangoDB database handle (python-arango StandardDatabase or SafeDatabase).

        """
        self._db = db
        self._schema = SCHEMA
        self.validate_schema(self._schema)

    def validate_schema(self, schema: dict[str, Any]) -> None:
        """Validate schema declarations.

        Raises SchemaValidationError on violations.

        Validation rules:
        1. ann_search only on TEMPLATE collections
        2. transition only on STATE_GRAPH collections
        3. cascade targets must be declared as edge collections (EDGE type)
        4. .get.one only generated for unique fields (enforced in namespace construction)

        """
        edge_collections = {name for name, spec in schema.items() if spec.get("type") == CollectionType.EDGE}

        for col_name, spec in schema.items():
            col_type = spec.get("type")
            capabilities = spec.get("capabilities", [])

            if "ann_search" in capabilities and col_type != CollectionType.TEMPLATE:
                raise SchemaValidationError(
                    f"Collection '{col_name}' declares ann_search but has type={col_type}. "
                    "ann_search is restricted to TEMPLATE collections (vector search only)."
                )

            if "transition" in capabilities and col_type != CollectionType.STATE_GRAPH:
                raise SchemaValidationError(
                    f"Collection '{col_name}' declares transition but has type={col_type}. "
                    "transition is restricted to STATE_GRAPH collections."
                )

            for cascade_target in spec.get("cascade", []):
                if cascade_target not in schema:
                    raise SchemaValidationError(
                        f"Collection '{col_name}' declares cascade target '{cascade_target}' "
                        "which is not declared in SCHEMA."
                    )
                if cascade_target not in edge_collections:
                    raise SchemaValidationError(
                        f"Collection '{col_name}' declares cascade target '{cascade_target}' "
                        f"but that collection has type={schema[cascade_target].get('type')}, "
                        "not EDGE. Cascade targets must be edge collections."
                    )

    def build_collection_namespace(
        self,
        name: str,
        spec: dict[str, Any],
        registry: dict[str, Any] | None = None,
    ) -> CollectionNamespace:
        """Build a CollectionNamespace from a collection schema spec.

        Args:
            name: Collection name.
            spec: Collection schema spec from SCHEMA.
            registry: Optional template collection registry for cascade.

        Returns:
            Fully constructed CollectionNamespace.

        """
        collection_name = cast("str", spec.get("collection_name", name))

        return CollectionNamespace(
            db=self._db,
            collection_name=collection_name,
            spec=spec,
            schema=self._schema,
            registry=registry,
        )

    def build_template_namespace(
        self,
        name: str,
        tier: str,
        backbone_id: str,
        library_key: str,
        collection_suffix: str | None = None,
        registry: dict[str, Any] | None = None,
    ) -> CollectionNamespace:
        """Build a namespace for a dynamically-resolved template collection."""
        template_spec = cast("dict[str, Any]", self._schema[name])
        if template_spec.get("type") != CollectionType.TEMPLATE:
            msg = f"Collection '{name}' is not a template collection"
            raise SchemaValidationError(msg)

        tiers = cast("dict[str, Any]", template_spec.get("tiers", {}))
        if tier not in tiers:
            msg = f"Template '{name}' does not define tier '{tier}'"
            raise SchemaValidationError(msg)

        resolved_name = cast("str", template_spec["name_pattern"]).format(
            tier=tier,
            backbone_id=backbone_id,
            library_key=library_key,
        )
        if collection_suffix:
            resolved_name = f"{resolved_name}__{collection_suffix}"

        resolved_spec = deepcopy(template_spec)
        resolved_spec["collection_name"] = resolved_name
        resolved_spec["fields"] = deepcopy(tiers[tier]["fields"])
        resolved_spec["template_family"] = name
        resolved_spec["template_tier"] = tier
        if tier != "cold":
            resolved_spec["capabilities"] = [
                capability
                for capability in cast("list[str]", template_spec.get("capabilities", []))
                if capability != "ann_search"
            ]

        return self.build_collection_namespace(name, resolved_spec, registry=registry)

    def build(
        self,
        schema: dict[str, Any] | None = None,
        registry: dict[str, Any] | None = None,
    ) -> dict[str, CollectionNamespace]:
        """Validate and build all collection namespaces.

        Args:
            schema: Schema dict (defaults to SCHEMA from persistence.schema).
            registry: Optional template collection registry.

        Returns:
            Dict mapping collection names to CollectionNamespace objects.

        """
        target = schema or self._schema
        self.validate_schema(target)

        namespaces: dict[str, CollectionNamespace] = {}
        for name, spec in target.items():
            if spec.get("type") == CollectionType.TEMPLATE:
                continue

            collection_name = cast("str", spec.get("collection_name", name))
            namespaces[name] = CollectionNamespace(
                db=self._db,
                collection_name=collection_name,
                spec=spec,
                schema=target,
                registry=registry,
            )

        return namespaces
