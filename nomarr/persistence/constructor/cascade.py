"""Cascade engine for the schema-driven persistence constructor.

Implements recursive delete with orphan detection per DD §3.7.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, cast

from nomarr.persistence.arango_client import SafeDatabase
from nomarr.persistence.constructor.verbs import _execute_aql
from nomarr.persistence.schema import CollectionType


class CascadeEngine:
    """Recursive cascade delete engine.

    Walks schema-declared cascade targets, removes connected edges,
    detects orphaned documents (no remaining edges in any collection),
    and recursively deletes them.
    """

    def cascade(
        self,
        db: SafeDatabase,
        collection_name: str,
        ids: list[str],
        cascade_targets: list[str],
        schema: dict[str, Any],
        registry: dict[str, Any] | None = None,
    ) -> int:
        """Cascade delete documents and their connected edge/orphan data.

        Args:
            db: ArangoDB database handle.
            collection_name: The collection being deleted from.
            ids: Document IDs to cascade from.
            cascade_targets: List of edge collection names to walk.
            schema: The full SCHEMA dict (for orphan detection).
            registry: Optional dict of registered template collection instances.

        Returns:
            Total count of documents deleted (seed vertices + edges + orphaned vertices).

        """
        normalized_ids = list(dict.fromkeys(ids))
        if not normalized_ids:
            return 0

        total_deleted = 0
        active_registry = registry or {}

        for edge_col in cascade_targets:
            cursor = _execute_aql(
                db,
                """
                FOR e IN @@edge_col
                    FILTER e._from IN @ids OR e._to IN @ids
                    RETURN {_key: e._key, _from: e._from, _to: e._to}
                """,
                bind_vars={"@edge_col": edge_col, "ids": normalized_ids},
            )
            edges = list(cursor)

            if not edges:
                continue

            id_set = set(normalized_ids)
            target_ids = list(dict.fromkeys(self._extract_connected_target_ids(edges=edges, source_ids=id_set)))

            edge_keys = [edge["_key"] for edge in edges]
            _execute_aql(
                db,
                "FOR key IN @keys REMOVE key IN @@edge_col",
                bind_vars={"@edge_col": edge_col, "keys": edge_keys},
            )
            total_deleted += len(edge_keys)

            orphan_ids = self._find_orphans(db, target_ids, schema, active_registry)

            for orphan_collection, orphan_collection_ids in orphan_ids.items():
                orphan_spec = self._resolve_collection_spec(
                    orphan_collection,
                    schema,
                    active_registry,
                )
                orphan_cascade_targets = list(orphan_spec.get("cascade", []))
                total_deleted += self.cascade(
                    db,
                    orphan_collection,
                    orphan_collection_ids,
                    orphan_cascade_targets,
                    schema,
                    active_registry,
                )

        _execute_aql(
            db,
            "FOR doc_id IN @ids REMOVE PARSE_IDENTIFIER(doc_id).key IN @@col",
            bind_vars={"@col": collection_name, "ids": normalized_ids},
        )
        total_deleted += len(normalized_ids)

        return total_deleted

    def _find_orphans(
        self,
        db: SafeDatabase,
        candidate_ids: list[str],
        schema: dict[str, Any],
        registry: dict[str, Any],
    ) -> dict[str, list[str]]:
        """Find which candidate document IDs are now orphaned (no remaining edges).

        Returns a dict mapping collection_name -> list of orphaned doc IDs.
        """
        if not candidate_ids:
            return {}

        by_collection: dict[str, list[str]] = {}
        for doc_id in candidate_ids:
            collection_name = self._collection_from_id(doc_id)
            if collection_name is not None:
                by_collection.setdefault(collection_name, []).append(doc_id)

        orphans: dict[str, list[str]] = {}

        for collection_name, collection_ids in by_collection.items():
            referencing_edges = self._find_referencing_edge_collections(
                collection_name,
                schema,
                registry,
            )

            for doc_id in dict.fromkeys(collection_ids):
                remaining = 0
                for edge_col in referencing_edges:
                    cursor = _execute_aql(
                        db,
                        "RETURN LENGTH(FOR e IN @@ec FILTER e._from == @id OR e._to == @id RETURN 1)",
                        bind_vars={"@ec": edge_col, "id": doc_id},
                    )
                    remaining += next(cursor, 0)
                    if remaining > 0:
                        break

                if remaining == 0:
                    orphans.setdefault(collection_name, []).append(doc_id)

        return orphans

    def _find_referencing_edge_collections(
        self,
        collection_name: str,
        schema: dict[str, Any],
        registry: dict[str, Any],
    ) -> list[str]:
        """Find all edge collections that reference the given collection."""
        refs: list[str] = []
        template_name = self._resolve_template_name(collection_name, schema, registry)

        for spec in schema.values():
            if spec.get("type") == CollectionType.EDGE:
                continue

            edges = spec.get("edges", {})
            for edge_col, edge_spec in edges.items():
                edge_target = edge_spec.get("target")
                if edge_target in (collection_name, template_name) and edge_col not in refs:
                    refs.append(edge_col)

        return refs

    def _extract_connected_target_ids(
        self,
        *,
        edges: list[dict[str, str]],
        source_ids: set[str],
    ) -> list[str]:
        """Extract the opposite endpoint IDs for edges touching the source IDs."""
        target_ids: list[str] = []
        for edge in edges:
            if edge["_from"] not in source_ids:
                target_ids.append(edge["_from"])
            elif edge["_to"] not in source_ids:
                target_ids.append(edge["_to"])
        return target_ids

    def _resolve_collection_spec(
        self,
        collection_name: str,
        schema: dict[str, Any],
        registry: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve a concrete or template-backed collection spec from the schema."""
        if collection_name in schema:
            return cast("dict[str, Any]", schema[collection_name])

        template_name = self._resolve_template_name(collection_name, schema, registry)
        return cast("dict[str, Any]", schema.get(template_name, {}))

    def _resolve_template_name(
        self,
        collection_name: str,
        schema: dict[str, Any],
        registry: dict[str, Any],
    ) -> str:
        """Resolve the template schema name for a dynamic collection instance."""
        if collection_name in schema:
            return collection_name

        for template_name, spec in schema.items():
            if spec.get("type") != CollectionType.TEMPLATE:
                continue

            if collection_name in self._registered_template_collections(template_name, registry):
                return template_name

            if collection_name.startswith(f"{template_name}_"):
                return template_name

        return collection_name

    def _registered_template_collections(
        self,
        template_name: str,
        registry: dict[str, Any],
    ) -> set[str]:
        """Collect concrete collection names registered for a template collection."""
        collection_names: set[str] = set()

        for key, value in registry.items():
            if key.startswith(template_name):
                collection_names.add(key)

            for candidate in self._candidate_collection_names(value):
                if candidate.startswith(template_name):
                    collection_names.add(candidate)

            if isinstance(value, dict):
                for nested_key, nested_value in value.items():
                    if isinstance(nested_key, str) and nested_key.startswith(template_name):
                        collection_names.add(nested_key)
                    for candidate in self._candidate_collection_names(nested_value):
                        if candidate.startswith(template_name):
                            collection_names.add(candidate)

        return collection_names

    def _candidate_collection_names(self, value: Any) -> Iterable[str]:
        """Yield plausible Arango collection names from a registry value."""
        if value is None:
            return ()

        candidates: list[str] = []

        if isinstance(value, str):
            candidates.append(value)

        named_collection = getattr(value, "collection", None)
        if named_collection is not None:
            candidates.extend(self._extract_name_from_collection(named_collection))

        private_collection = getattr(value, "_collection", None)
        if private_collection is not None:
            candidates.extend(self._extract_name_from_collection(private_collection))

        for attr_name in ("collection_name", "_collection_name", "name", "_name"):
            attr_value = getattr(value, attr_name, None)
            if isinstance(attr_value, str):
                candidates.append(attr_value)

        return tuple(candidate for candidate in candidates if isinstance(candidate, str))

    def _extract_name_from_collection(self, collection: Any) -> Iterable[str]:
        """Extract the concrete collection name from a python-arango collection-like object."""
        names: list[str] = []
        name_attr = getattr(collection, "name", None)
        if callable(name_attr):
            maybe_name = cast("Any", name_attr)()
            if isinstance(maybe_name, str):
                names.append(maybe_name)
        elif isinstance(name_attr, str):
            names.append(name_attr)

        return tuple(names)

    def _collection_from_id(self, doc_id: str) -> str | None:
        """Extract the collection segment from an Arango document ID."""
        return doc_id.split("/", 1)[0] if "/" in doc_id else None
