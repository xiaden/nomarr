"""ArangoDB client factory for Nomarr.

Connection pooling handled automatically by python-arango client.
Thread-safe within a single process. Each process creates its own pool.
"""

from __future__ import annotations

from typing import Any

from arango import ArangoClient
from arango.aql import AQL
from arango.collection import StandardCollection
from arango.database import StandardDatabase

# =============================================================================
# JSON Serialization Boundary
# =============================================================================
# ArangoDB requires JSON-serializable bind_vars. Our codebase uses wrapper types
# (Milliseconds, Seconds, etc.) for type safety. This module provides a single
# choke point that converts wrapper types to primitives before execution.
#
# STRICT CONTRACT:
# - Only JSON primitives (str/int/float/bool/None) and dict/list containers allowed
# - Wrapper types with `.value` that is a primitive are unwrapped automatically
# - Complex DTOs (LibraryPath, etc.) are NOT auto-converted - they raise TypeError
# - Call sites must explicitly convert DTOs to primitives before persistence
# =============================================================================

_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _jsonify_for_arango(obj: Any, *, _path: str = "$") -> Any:
    """Recursively normalize bind_vars to JSON-serializable primitives.

    STRICT normalizer that only allows:
    - JSON primitives: str, int, float, bool, None
    - Containers: dict, list, tuple (recursed)
    - Wrapper types with `.value` that is a primitive (unwrapped)

    Complex DTOs (dataclasses without .value, custom objects) are NOT
    auto-converted. Call sites must explicitly convert them to primitives.

    Args:
        obj: Any object to convert
        _path: Internal path tracking for error messages (e.g., "$.docs[0].scanned_at")

    Returns:
        JSON-serializable equivalent of obj

    Raises:
        TypeError: If obj contains non-serializable types (with path context)
    """
    # Fast path: primitives pass through unchanged
    if isinstance(obj, _JSON_PRIMITIVES):
        return obj

    # Containers: recurse into dict/list/tuple
    if isinstance(obj, dict):
        return {str(k): _jsonify_for_arango(v, _path=f"{_path}.{k}") for k, v in obj.items()}
    if isinstance(obj, list | tuple):
        return [_jsonify_for_arango(v, _path=f"{_path}[{i}]") for i, v in enumerate(obj)]

    # Wrapper types with .value (Milliseconds, Seconds, InternalMilliseconds, etc.)
    # Only unwrap if .value is a JSON primitive
    if hasattr(obj, "value"):
        v = obj.value
        if isinstance(v, _JSON_PRIMITIVES):
            return v
        # .value exists but isn't a primitive - fail loudly
        raise TypeError(
            f"Non-primitive .value at {_path}: {type(obj).__name__}.value is {type(v).__name__}, "
            f"expected JSON primitive"
        )

    # Everything else is rejected - call sites must convert explicitly
    raise TypeError(
        f"Object at {_path} not JSON-serializable for Arango: {type(obj).__name__}. "
        f"Convert to primitive before passing to persistence layer."
    )


class _SafeAQL:
    """Minimal wrapper around AQL that sanitizes bind_vars before execution.

    Only intercepts execute() - all other methods delegate to underlying AQL.
    """

    def __init__(self, aql: AQL) -> None:
        self._aql = aql

    def execute(
        self,
        query: str,
        bind_vars: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute AQL query with sanitized bind_vars."""
        safe_bind_vars = _jsonify_for_arango(bind_vars or {})
        return self._aql.execute(query, bind_vars=safe_bind_vars, **kwargs)

    def __getattr__(self, name: str) -> Any:
        """Proxy all other attributes to the underlying AQL object."""
        return getattr(self._aql, name)


class SafeDatabase:
    """Minimal wrapper around StandardDatabase that provides safe AQL execution.

    Only overrides `.aql` property - all other attributes proxy to underlying db.
    This class is designed to be a drop-in replacement for StandardDatabase
    with automatic JSON serialization of bind_vars.
    """

    def __init__(self, db: StandardDatabase) -> None:
        self._db = db
        self._safe_aql = _SafeAQL(db.aql)

    @property
    def aql(self) -> _SafeAQL:
        """Return SafeAQL wrapper that sanitizes bind_vars."""
        return self._safe_aql

    def collection(self, name: str) -> StandardCollection:
        """Get a collection by name. Explicitly typed for mypy compatibility."""
        return self._db.collection(name)  # type: ignore[return-value]

    def __getattr__(self, name: str) -> Any:
        """Proxy all other attributes to the underlying database."""
        return getattr(self._db, name)


# Type alias for database objects that can be used by operations classes.
# Both StandardDatabase and SafeDatabase are acceptable.
DatabaseLike = StandardDatabase | SafeDatabase


def create_arango_client(
    hosts: str = "http://nomarr-arangodb:8529",
    username: str = "nomarr",
    password: str = "nomarr_password",
    db_name: str = "nomarr",
) -> SafeDatabase:
    """Create ArangoDB client and return database handle with safe serialization.

    Connection pooling is handled automatically by python-arango.
    Thread-safe within a single process. Each process creates its own pool.

    The returned SafeDatabase wraps StandardDatabase and automatically converts
    wrapper types (Milliseconds, Seconds, etc.) to primitives before AQL execution.

    Normal operation: Connects as app user to existing database.
    First-run only: May connect as root (see first_run_provision component).

    Args:
        hosts: ArangoDB server URL(s)
        username: Database username
        password: Database password
        db_name: Database name

    Returns:
        SafeDatabase instance (wraps StandardDatabase with safe serialization)

    Raises:
        DatabaseGetError: If database doesn't exist (signals first-run needed)
        ServerConnectionError: If cannot connect to ArangoDB service
    """
    client = ArangoClient(hosts=hosts)
    db = client.db(db_name, username=username, password=password)
    return SafeDatabase(db)
