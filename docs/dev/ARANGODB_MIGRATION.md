# SQLite → ArangoDB Migration

## Executive Summary

Migrating from SQLite to ArangoDB to solve multi-process concurrency issues and enable horizontal scaling.

**Why ArangoDB:**
- ✅ True multi-process, multi-threaded concurrency (no write locks)
- ✅ Built-in connection pooling and clustering support
- ✅ Flexible schema (JSON documents) - natural fit for our data
- ✅ Graph capabilities (model file→tag relationships as edges)
- ✅ Web UI for database administration
- ✅ Supports horizontal scaling when needed

**Migration Scope:**
- Replace `sqlite3` with `python-arango` client
- Convert 10 SQL tables to ArangoDB collections
- Rewrite all SQL queries to AQL (ArangoDB Query Language)
- Update 12 `*Operations` classes in `persistence/database/`
- Update docker-compose to include ArangoDB service
- Migrate existing SQLite data to ArangoDB

**Breaking Change:** Pre-alpha, no backward compatibility. Users must re-scan libraries.

---

## Architecture Changes

### Connection Model

**Before (SQLite):**
```python
import sqlite3
conn = sqlite3.connect(path, check_same_thread=False, timeout=30.0)
conn.execute("PRAGMA journal_mode=WAL;")
```

**After (ArangoDB):**
```python
from arango import ArangoClient
client = ArangoClient(hosts='http://arangodb:8529')
db = client.db('nomarr', username='nomarr', password='***')
```

**Key Differences:**
- ArangoDB is a service (not embedded file)
- Connection pooling built-in (thread-safe by default)
- No `check_same_thread` workarounds
- No WAL mode configuration (handled by ArangoDB)

### Data Model

**Relational (SQLite) → Document (ArangoDB):**

```python
# SQLite: Normalized tables with foreign keys
library_files:
  id INTEGER PRIMARY KEY
  path TEXT
  library_id INTEGER REFERENCES libraries(id)
  artist TEXT
  album TEXT
  calibration TEXT  # JSON blob

file_tags:  # Many-to-many join table
  file_id INTEGER
  tag_id INTEGER

# ArangoDB: Flexible documents + graph edges
library_files:  # Document collection
  _key: "12345"
  _id: "library_files/12345"
  path: "Artist/Album/song.mp3"  # Relative to library root
  library_id: 1
  artist: "Artist Name"
  album: "Album Name"
  calibration: {...}  # Native JSON

file_tags:  # Edge collection (graph relationship)
  _from: "library_files/12345"
  _to: "library_tags/67890"
```

**Benefits:**
- Native JSON storage (no TEXT serialization)
- Graph queries for tag relationships
- Flexible schema evolution
- Subdocument support (nested calibration data)
- **Relative paths**: Portable across library root changes and container mounts

---

## Schema Translation

### 1. Collections (tables → collections)

| SQLite Table | ArangoDB Collection | Type | Notes |
|---|---|---|---|
| `tag_queue` | `tag_queue` | Document | Job queue for ML tagging |
| `meta` | `meta` | Document | Key-value config store |
| `libraries` | `libraries` | Document | Library definitions |
| `library_files` | `library_files` | Document | Music file metadata |
| `calibration_queue` | `calibration_queue` | Document | Calibration job queue |
| `library_tags` | `library_tags` | Document | Tag definitions (deduplicated) |
| `file_tags` | `file_tags` | **Edge** | File→Tag relationships (graph) |
| `sessions` | `sessions` | Document | Web UI sessions |
| `calibration_runs` | `calibration_runs` | Document | Calibration history |
| `health` | `health` | Document | Component health monitoring |

**Key Decision: `file_tags` as Edge Collection**

Using ArangoDB's graph capabilities for file→tag relationships:
- Enables efficient graph traversals ("all files with tag X")
- Natural fit for many-to-many relationships
- Faster than JOIN queries

### 2. Indexes

**SQLite indexes → ArangoDB indexes:**

```javascript
// tag_queue indexes
db.tag_queue.ensureIndex({ type: "persistent", fields: ["status"] });
db.tag_queue.ensureIndex({ type: "persistent", fields: ["created_at"] });

// library_files indexes
db.library_files.ensureIndex({ type: "persistent", fields: ["library_id"] });
db.library_files.ensureIndex({ 
  type: "persistent", 
  fields: ["library_id", "path"],  // path is relative to library root
  unique: true 
});
db.library_files.ensureIndex({ 
  type: "persistent", 
  fields: ["chromaprint"], 
  sparse: true  // Only index non-null values
});

// library_tags indexes
db.library_tags.ensureIndex({ 
  type: "persistent", 
  fields: ["key", "value", "is_nomarr_tag"], 
  unique: true 
});

// sessions TTL index (auto-expire based on expiry_timestamp unix timestamp)
db.sessions.ensureIndex({ 
  type: "ttl", 
  fields: ["expiry_timestamp"], 
  expireAfter: 0  // Expire immediately when timestamp passes
});
```

**ArangoDB Index Types:**
- `persistent`: Standard B-tree index (like SQLite indexes)
- `ttl`: Auto-delete expired documents (perfect for sessions!)
- `hash`: Fast equality lookups
- `skiplist`: Range queries
- `fulltext`: Full-text search (future: search song titles/artists)
- `geo`: Geospatial (not needed)

### 4. Named Graph Definition

**Define explicit graph for file→tag relationships:**

```javascript
// Create named graph "file_tag_graph"
db._create({
  name: "file_tag_graph",
  edgeDefinitions: [{
    collection: "file_tags",  // Edge collection
    from: ["library_files"],  // Source vertex collection
    to: ["library_tags"]       // Target vertex collection
  }]
});
```

**Benefits:**
- Cleaner traversal syntax
- Graph-aware tools and UI
- Future-proof for complex graph queries

### 5. ID Strategy: DB-Primary Architecture

**Nomarr is DB-primary: The database record IS the song.**

**Identity model:**
- `_id` (e.g., `library_files/12345`) is the **primary identity**
- `path` is a **filesystem locator attribute**, not identity
- Filesystem is read at controlled phases (ingestion, ML), but DB is authoritative

**ArangoDB identity fields:**

```python
# ArangoDB auto-generates _key, _id is derived
result = collection.insert({
    "path": "Artist/Album/song.mp3",  # Relative path
    "library_id": 1,
})

file_key = result["_key"]  # String like "12345" (collection-local)
file_id = result["_id"]    # String like "library_files/12345" (globally unique)
```

**Recommendation: Use `_id` everywhere as the DB handle**

Why `_id` instead of `_key`:
- Graph edges require `_id` format (`_from`, `_to`)
- Globally unique across all collections
- No string concatenation needed for traversals
- Future-proof as graph usage expands
- Simpler: one identity, works everywhere

**Trade-off accepted:**
- `_id` is slightly heavier than `_key` (includes collection prefix)
- More Arango-specific than integer IDs
- **But**: Nomarr is already DB-centric, so this is explicit commitment, not accidental coupling

**Migration note:** Since we're pre-alpha and require library re-scan, we do NOT preserve SQLite IDs. Auto-generated keys are simpler and avoid migration complexity.

**Filesystem interaction boundaries:**

1. **Ingestion** (read filesystem → create DB records)
   - Discover files
   - Create DB documents with `_id`
   - Emit Song DTOs with `_id` populated

2. **ML processing** (read audio bytes via path)
   - Accepts Song DTOs with `_id` (required)
   - Re-reads audio file using `path` attribute
   - Writes results back to DB using `_id`

3. **Tag writeback** (write DB tags → filesystem)
   - Query DB for tag state
   - Write to filesystem using `path` attribute
   - DB remains authoritative

**Outside these phases:** All workflows operate entirely on DB state.

**Critical invariant:**
> `_id` is the operational identity. `path` is a pointer to bytes. These are not competing identities.

---

## Query Translation Examples

### Simple SELECT

**SQLite:**
```sql
SELECT id, path, artist, album 
FROM library_files 
WHERE library_id = ? 
LIMIT 100
```

**AQL:**
```python
cursor = db.aql.execute(
    """
    FOR file IN library_files
        FILTER file.library_id == @library_id
        LIMIT 100
        RETURN {
            id: file._id,
            path: file.path,
            artist: file.artist,
            album: file.album
        }
    """,
    bind_vars={"library_id": library_id}
)
results = list(cursor)
```

### UPDATE

**SQLite:**
```sql
UPDATE library_files 
SET tagged = 1, tagged_version = ?, last_tagged_at = ? 
WHERE id = ?
```

**AQL:**
```python
db.aql.execute(
    """
    UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
        tagged: 1,
        tagged_version: @version,
        last_tagged_at: @timestamp
    } IN library_files
    """,
    bind_vars={
        "file_id": file_id,  # _id like "library_files/12345"
        "version": version,
        "timestamp": timestamp
    }
)
```

**Note:** `PARSE_IDENTIFIER(@file_id).key` extracts the document key from the full `_id` string. This is required because ArangoDB's `UPDATE <key> WITH ...` expects a document key, not the full `_id` handle.

**CRITICAL RULE: All persistence mutations by _id must use PARSE_IDENTIFIER**

When writing UPDATE or REMOVE operations that accept `_id` as input:
```python
# ✅ CORRECT - Extract _key from _id
UPDATE PARSE_IDENTIFIER(@file_id).key WITH {...} IN library_files
REMOVE PARSE_IDENTIFIER(@file_id).key IN library_files

# ❌ WRONG - Cannot use _id directly
UPDATE @file_id WITH {...} IN library_files  # Fails: @file_id is a string
REMOVE @file_id IN library_files             # Fails: @file_id is a string
```

This pattern is universal across all `*_aql.py` modules. DB-primary architecture requires `_id` everywhere, but AQL UPDATE/REMOVE syntax requires extracted keys.

### JOIN (File + Tags)

**SQLite:**
```sql
SELECT lf.id, lf.path, lt.key, lt.value
FROM library_files lf
JOIN file_tags ft ON lf.id = ft.file_id
JOIN library_tags lt ON ft.tag_id = lt.id
WHERE lf.library_id = ?
```

**AQL (Using Graph Traversal):**
```python
cursor = db.aql.execute(
    """
    FOR file IN library_files
        FILTER file.library_id == @library_id
        LET tags = (
            FOR v, e IN 1..1 OUTBOUND file._id file_tags
                RETURN {key: v.key, value: v.value}
        )
        RETURN {
            id: file._id,
            path: file.path,
            tags: tags
        }
    """,
    bind_vars={"library_id": library_id}
)
```

**Alternative: Using Named Graph:**
```python
cursor = db.aql.execute(
    """
    FOR file IN library_files
        FILTER file.library_id == @library_id
        LET tags = (
            FOR v IN 1..1 OUTBOUND file._id GRAPH 'file_tag_graph'
                RETURN {key: v.key, value: v.value}
        )
        RETURN {
            id: file._id,
            path: file.path,
            tags: tags
        }
    """,
    bind_vars={"library_id": library_id}
)
```

**Rules for Graph Traversal Usage:**

Use graph traversal (`FOR v IN OUTBOUND ... GRAPH`) only when:
1. Crossing more than one relationship hop (e.g., file → tag → related_files)
2. The relationship itself is the primary query axis (e.g., "find all connected nodes")

Otherwise, prefer direct document queries with edge lookups:
- Single-hop queries: Use subquery with edge scan
- Performance: Direct queries often faster for simple cases
- Maintainability: Simpler queries easier to optimize

Without this discipline, you'll get inconsistent query styles across persistence modules.

### UPSERT (INSERT ... ON CONFLICT)

**SQLite:**
```sql
INSERT INTO library_files (path, library_id, ...) VALUES (?, ?, ...)
ON CONFLICT(path) DO UPDATE SET library_id = excluded.library_id, ...
```

**AQL:**
```python
db.aql.execute(
    """
    UPSERT { library_id: @library_id, path: @path }
    INSERT {
        library_id: @library_id,
        path: @path,
        file_size: @file_size,
        created_at: @now
    }
    UPDATE {
        file_size: @file_size,
        modified_time: @modified_time,
        updated_at: @now
    }
    IN library_files
    RETURN NEW
    """,
    bind_vars={
        "library_id": library_id,
        "path": path,
        "file_size": file_size,
        "modified_time": modified_time,
        "now": now_ms()
    }
)
```

---

## Code Changes

### 1. Dependencies

**Add to `requirements.txt`:**
```txt
python-arango==7.9.0  # ArangoDB Python driver
```

**Remove:**
- No SQLite dependencies to remove (stdlib)

### 2. New Connection Module: `persistence/arango_client.py`

```python
"""ArangoDB client factory for Nomarr."""

from arango import ArangoClient
from arango.database import StandardDatabase


def create_arango_client(
    hosts: str = "http://nomarr-arangodb:8529",
    username: str = "nomarr",
    password: str = "nomarr_password",
    db_name: str = "nomarr",
) -> StandardDatabase:
    """
    Create ArangoDB client and return database handle.
    
    Connection pooling is handled automatically by python-arango.
    Thread-safe within a single process. Each process creates its own pool.
    
    Normal operation: Connects as app user to existing database.
    First-run only: May connect as root (see first_run_provision component).
    
    Args:
        hosts: ArangoDB server URL(s)
        username: Database username
        password: User password
        db_name: Database name
        
    Returns:
        StandardDatabase instance
        
    Raises:
        DatabaseGetError: If database doesn't exist (signals first-run needed)
        AuthenticationError: If credentials are invalid
    """
    client = ArangoClient(hosts=hosts)
    db = client.db(db_name, username=username, password=password)
    return db
```

### 2. New First-Run Provisioning Component: `components/infrastructure/arango_first_run_comp.py`

**Purpose**: One-time DB/user creation during application first boot. Privilege separation enforced.

```python
"""ArangoDB first-run provisioning component.

This module handles FIRST-RUN ONLY privileged operations:
  - Create database
  - Create application user
  - Generate credentials
  - Write to persistent config

CRITICAL INVARIANTS:
  1. Only runs when explicitly triggered by first-run detection
  2. Root credentials used ONCE and never stored in app config
  3. After completion, app connects as least-privileged user forever
  4. Privileged access is a one-way door (cannot be re-entered)

This is not "lazy provisioning" - it's explicit onboarding.
"""

import secrets
from pathlib import Path

from arango import ArangoClient
from arango.exceptions import DatabaseCreateError, UserCreateError


def provision_database_and_user(
    hosts: str,
    root_password: str,
    app_username: str = "nomarr",
    db_name: str = "nomarr",
) -> str:
    """
    Provision ArangoDB database and application user.
    
    THIS FUNCTION MUST ONLY BE CALLED DURING FIRST-RUN ONBOARDING.
    
    Connects as root, creates DB + user, returns generated password.
    Root connection is dropped immediately after provisioning.
    
    Args:
        hosts: ArangoDB server URL
        root_password: Root password (from onboarding UI/env, NOT stored)
        app_username: Application username to create
        db_name: Database name to create
        
    Returns:
        Generated strong password for app user
        
    Raises:
        DatabaseCreateError: If DB creation fails
        UserCreateError: If user creation fails
    """
    # Generate strong random password for app user
    app_password = secrets.token_urlsafe(32)
    
    # Connect as root (FIRST-RUN ONLY)
    client = ArangoClient(hosts=hosts)
    sys_db = client.db("_system", username="root", password=root_password)
    
    # Create database
    if not sys_db.has_database(db_name):
        sys_db.create_database(db_name)
    
    # Create application user
    if not sys_db.has_user(app_username):
        sys_db.create_user(
            username=app_username,
            password=app_password,
            active=True,
        )
    
    # Grant permissions
    sys_db.update_permission(
        username=app_username,
        permission="rw",
        database=db_name,
    )
    
    # Root connection dropped here (goes out of scope)
    return app_password


def is_first_run(config_path: Path) -> bool:
    """
    Detect if this is first run (no DB config exists).
    
    Args:
        config_path: Path to persistent config file
        
    Returns:
        True if first run, False if already configured
    """
    return not config_path.exists() or not _has_db_config(config_path)


def _has_db_config(config_path: Path) -> bool:
    """Check if config file has ArangoDB credentials."""
    # Implementation: Check for ARANGO_PASSWORD or similar
    # Return False if missing or empty
    pass


def write_db_config(config_path: Path, password: str, db_name: str = "nomarr") -> None:
    """
    Write ArangoDB credentials to persistent config.
    
    After this, app will connect as 'nomarr' user forever.
    Root credentials are never written.
    
    Args:
        config_path: Path to persistent config file
        password: Generated app user password
        db_name: Database name
    """
    # Implementation: Write to config.yaml or .env
    # Store: ARANGO_PASSWORD, ARANGO_DB_NAME, etc.
    pass
```

**CRITICAL: Component Placement & Layering**

First-run provisioning lives in `components/infrastructure/` (NOT `persistence/`).

**Rationale:**
- Persistence layer is "AQL only" - database operations, no upward dependencies
- First-run provisioning requires reading/writing config files (higher-level concern)
- Schema bootstrap may evolve to include non-DB setup (directories, default configs)
- Components may call persistence; persistence may NOT call components

**Enforcement:**
- `persistence/` modules import ONLY: `arango.database`, `nomarr.helpers`
- NO imports of `nomarr.components` or `nomarr.services` in persistence layer
- import-linter will catch violations

### 3. Schema Bootstrap Component: `components/infrastructure/arango_bootstrap_comp.py`

**Purpose**: Schema initialization (collections, indexes, graphs) - separated from persistence layer

```python
"""ArangoDB schema bootstrap component."""

from arango.database import StandardDatabase


def ensure_schema(db: StandardDatabase) -> None:
    """
    Ensure all collections, indexes, and graphs exist.
    
    This is a component (domain logic), not persistence (queries).
    Idempotent - safe to call on every startup.
    
    Args:
        db: ArangoDB database handle
    """
    _create_collections(db)
    _create_indexes(db)
    _create_graphs(db)


def _create_collections(db: StandardDatabase) -> None:
    """Create document and edge collections."""
    # Document collections
    for collection_name in [
        "tag_queue",
        "meta",
        "libraries",
        "library_files",
        "calibration_queue",
        "library_tags",
        "sessions",
        "calibration_runs",
        "health",
    ]:
        if not db.has_collection(collection_name):
            db.create_collection(collection_name)
    
    # Edge collection for file_tags (graph relationship)
    if not db.has_collection("file_tags"):
        db.create_collection("file_tags", edge=True)


def _create_indexes(db: StandardDatabase) -> None:
    """Create indexes for performance."""
    # tag_queue indexes
    tag_queue = db.collection("tag_queue")
    tag_queue.add_persistent_index(fields=["status"], unique=False)
    tag_queue.add_persistent_index(fields=["created_at"], unique=False)
    
    # library_files indexes
    library_files = db.collection("library_files")
    library_files.add_persistent_index(fields=["library_id"], unique=False)
    library_files.add_persistent_index(
        fields=["library_id", "path"],  # Composite key for multi-library
        unique=True
    )
    library_files.add_persistent_index(
        fields=["chromaprint"], 
        unique=False, 
        sparse=True  # Only index non-null chromaprints
    )
    
    # library_tags indexes
    library_tags = db.collection("library_tags")
    library_tags.add_persistent_index(
        fields=["key", "value", "is_nomarr_tag"], 
        unique=True
    )
    
    # sessions TTL index (auto-expire)
    sessions = db.collection("sessions")
    sessions.add_ttl_index(
        fields=["expiry_timestamp"],  # Unix timestamp
        expiry_time=0  # Expire immediately when timestamp passes
    )


def _create_graphs(db: StandardDatabase) -> None:
    """Create named graphs for traversals."""
    if not db.has_graph("file_tag_graph"):
        db.create_graph(
            name="file_tag_graph",
            edge_definitions=[{
                "edge_collection": "file_tags",
                "from_vertex_collections": ["library_files"],
                "to_vertex_collections": ["library_tags"],
            }]
        )
```

### 3. Update `persistence/db.py`

**Replace SQLite connection with ArangoDB:**

```python
"""Database layer for Nomarr."""

from arango.database import StandardDatabase

from nomarr.persistence.arango_client import create_arango_client

# Import operation classes
from nomarr.persistence.database.calibration_queue_aql import CalibrationQueueOperations
from nomarr.persistence.database.calibration_runs_aql import CalibrationRunsOperations
from nomarr.persistence.database.file_tags_aql import FileTagOperations
from nomarr.persistence.database.health_aql import HealthOperations
from nomarr.persistence.database.libraries_aql import LibrariesOperations
from nomarr.persistence.database.library_files_aql import LibraryFilesOperations
from nomarr.persistence.database.library_tags_aql import LibraryTagOperations
from nomarr.persistence.database.meta_aql import MetaOperations
from nomarr.persistence.database.sessions_aql import SessionOperations
from nomarr.persistence.database.tag_queue_aql import QueueOperations

__all__ = ["Database", "SCHEMA_VERSION"]

SCHEMA_VERSION = 2  # Incremented for ArangoDB migration

# ==================== SCHEMA VERSIONING POLICY ====================
# Schema versioning is ADDITIVE ONLY.
#
# SCHEMA_VERSION is stored in meta but NOT enforced at runtime.
# Schema bootstrap (ensure_schema) is idempotent and creates missing
# collections/indexes, but does NOT handle:
#   - Index changes (must drop manually)
#   - Collection renames (manual intervention)
#   - Data migrations (not supported)
#
# Future schema changes require:
#   1. Increment SCHEMA_VERSION
#   2. Add new collections/indexes to bootstrap
#   3. Document manual intervention steps if destructive
#
# Pre-alpha: Breaking changes are acceptable.
# Post-1.0: Must build migration framework or maintain additive-only.
# ==================================================================


class Database:
    """
    Application database (ArangoDB).
    
    Handles all data persistence: queues, library, sessions, meta config.
    Thread-safe and multi-process safe (connection pooling built-in).
    """
    
    def __init__(
        self,
        hosts: str = "http://nomarr-arangodb:8529",
        username: str = "nomarr",
        password: str = "nomarr_password",
        db_name: str = "nomarr",
    ):
        """
        Initialize database connection.
        
        Args:
            hosts: ArangoDB server URL (default: http://nomarr-arangodb:8529)
            username: Database username
            password: Database password
            db_name: Database name
        """
        self.db: StandardDatabase = create_arango_client(
            hosts=hosts,
            username=username,
            password=password,
            db_name=db_name,
        )
        
        # Initialize operation classes (persistence layer only)
        self.meta = MetaOperations(self.db)
        self.libraries = LibrariesOperations(self.db)
        self.tag_queue = QueueOperations(self.db)
        self.library_files = LibraryFilesOperations(self.db)
        self.library_tags = LibraryTagOperations(self.db)
        self.file_tags = FileTagOperations(self.db)
        self.sessions = SessionOperations(self.db)
        self.calibration_queue = CalibrationQueueOperations(self.db)
        self.calibration_runs = CalibrationRunsOperations(self.db)
        self.health = HealthOperations(self.db)
        
        # Lazy import for joined queries
        from nomarr.persistence.database.joined_queries_aql import JoinedQueryOperations
        self.joined_queries = JoinedQueryOperations(self.db)
        
        # Store schema version
        if not self.meta.get("schema_version"):
            self.meta.set("schema_version", str(SCHEMA_VERSION))
    
    def close(self):
        """
        Close database connection.
        
        Note: ArangoDB client manages connection pool,
        explicit close is optional.
        """
        pass  # Connection pool managed by client


# ==================== ARCHITECTURAL NOTE ====================
# Database class is a service locator pattern:
#   - Every consumer gets all persistence capabilities
#   - Weakens ability to reason about which workflows touch which data
#   - Consistent with existing architecture, but has implications
#
# Future consideration:
#   - joined_queries module will accumulate graph-heavy queries
#   - Discipline required to prevent it from ballooning
#   - Consider splitting into domain-specific query modules if needed
# ============================================================
```

### 5. Application Startup Wiring

**Two modes: First-run onboarding vs normal operation**

**In `app.py` or service initialization:**

```python
from nomarr.components.infrastructure.arango_bootstrap_comp import ensure_schema
from nomarr.components.infrastructure.arango_first_run_comp import (
    is_first_run,
    provision_database_and_user,
    write_db_config,
)
from nomarr.persistence.db import Database
from nomarr.helpers.config import get_config_path, load_config


class Application:
    def __init__(self):
        config_path = get_config_path()
        
        # ==================== FIRST-RUN DETECTION ====================
        if is_first_run(config_path):
            # User sees: "Welcome to Nomarr! Let's set things up."
            # This triggers onboarding UI/CLI flow
            self._run_first_boot_onboarding(config_path)
            # After onboarding: config exists, restart or continue
        
        # ==================== NORMAL OPERATION ====================
        config = load_config(config_path)
        
        # 1. Create database connection (persistence layer)
        # Connects as 'nomarr' user (NOT root)
        self.db = Database(
            hosts=config.arango_hosts,
            username="nomarr",
            password=config.arango_password,  # From first-run provisioning
            db_name=config.arango_db_name,
        )
        
        # 2. Ensure schema exists (component layer)
        ensure_schema(self.db.db)  # Pass StandardDatabase handle
        
        # 3. Initialize services with injected dependencies
        self.library_service = LibraryService(db=self.db)
        self.processing_service = ProcessingService(db=self.db)
    
    def _run_first_boot_onboarding(self, config_path: Path) -> None:
        """
        First-boot onboarding flow.
        
        This is where you guide users through:
          - What Nomarr is
          - How to configure libraries
          - Database setup
          - First scan tutorials
        
        Privileged DB access happens ONLY here, ONCE.
        """
        # Get root password (from env var ARANGO_ROOT_PASSWORD)
        # NO DEFAULT - must be explicitly set for security
        root_password = os.getenv("ARANGO_ROOT_PASSWORD")
        if not root_password:
            raise RuntimeError(
                "ARANGO_ROOT_PASSWORD environment variable must be set for first-run provisioning"
            )
        
        # Provision DB + user (uses root credentials ONCE)
        app_password = provision_database_and_user(
            hosts="http://nomarr-arangodb:8529",
            root_password=root_password,
        )
        
        # Write config (app user credentials only, NOT root)
        write_db_config(config_path, password=app_password)
        
        # Root password never stored, provisioning code path unreachable after this
        # Show success message, continue to app or prompt restart
```

**Benefits:**
- Clean separation: Database is connection-only, schema is components
- Testable: Can mock schema bootstrap in unit tests
- Explicit: Bootstrap happens once at startup, not hidden in constructor

### 4. Rewrite Operation Classes

**Example: `library_files_aql.py` (simplified)**

```python
"""Library files operations for ArangoDB."""

from typing import Any

from arango.database import StandardDatabase

from nomarr.helpers.dto import LibraryPath
from nomarr.helpers.time_helper import now_ms


class LibraryFilesOperations:
    """Operations for the library_files collection."""
    
    def __init__(self, db: StandardDatabase):
        self.db = db
        self.collection = db.collection("library_files")
    
    def upsert_library_file(
        self,
        path: LibraryPath,
        library_id: int,
        file_size: int,
        modified_time: int,
        duration_seconds: float | None = None,
        artist: str | None = None,
        album: str | None = None,
        title: str | None = None,
        calibration: dict[str, Any] | None = None,  # Native dict, not JSON string!
        last_tagged_at: int | None = None,
    ) -> str:
        """
        Insert or update library file.
        
        Returns:
            File _id (e.g., "library_files/12345")
        """
        if not path.is_valid():
            raise ValueError(f"Cannot upsert invalid path ({path.status}): {path.reason}")
        
        scanned_at = now_ms()
        
        cursor = self.db.aql.execute(
            """
            UPSERT { library_id: @library_id, path: @path }
            INSERT {
                library_id: @library_id,
                path: @path,  # Relative to library root
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                calibration: @calibration,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at,
                needs_tagging: 0,
                is_valid: 1,
                tagged: 0
            }
            UPDATE {
                library_id: @library_id,
                file_size: @file_size,
                modified_time: @modified_time,
                duration_seconds: @duration_seconds,
                artist: @artist,
                album: @album,
                title: @title,
                calibration: @calibration,
                scanned_at: @scanned_at,
                last_tagged_at: @last_tagged_at != null ? @last_tagged_at : OLD.last_tagged_at
            }
            IN library_files
            RETURN NEW._id
            """,
            bind_vars={
                "library_id": library_id,
                "path": str(path.relative),  # Store relative path
                "file_size": file_size,
                "modified_time": modified_time,
                "duration_seconds": duration_seconds,
                "artist": artist,
                "album": album,
                "title": title,
                "calibration": calibration or {},
                "scanned_at": scanned_at,
                "last_tagged_at": last_tagged_at,
            }
        )
        
        result = next(cursor)
        return result  # Returns _id (e.g., "library_files/12345")
    
    def get_file_by_path(self, path: str) -> dict[str, Any] | None:
        """Get file by path."""
        cursor = self.db.aql.execute(
            """
            FOR file IN library_files
                FILTER file.path == @path
                LIMIT 1
                RETURN file
            """,
            bind_vars={"path": path}
        )
        
        results = list(cursor)
        return results[0] if results else None
    
    def mark_file_tagged(self, file_id: str, tagged_version: str) -> None:
        """Mark file as tagged.
        
        Accepts _id directly (no lookup needed).
        
        Args:
            file_id: Document _id (e.g., "library_files/12345")
            tagged_version: Tagged version string
        """
        self.db.aql.execute(
            """
            UPDATE PARSE_IDENTIFIER(@file_id).key WITH {
                tagged: 1,
                tagged_version: @version,
                last_tagged_at: @timestamp,
                needs_tagging: 0
            } IN library_files
            """,
            bind_vars={
                "file_id": file_id,
                "version": tagged_version,
                "timestamp": now_ms()
            }
        )
```

### 6. Docker Compose Changes

**Simplified compose - no init container needed:**

**Update `docker-compose.yml`:**

```yaml
services:
  # ArangoDB database service
  nomarr-arangodb:
    image: arangodb:3.11
    container_name: nomarr-arangodb
    networks:
      - internal_network  # Internal only, no public exposure
    environment:
      - ARANGO_ROOT_PASSWORD=${ARANGO_ROOT_PASSWORD}  # From .env file
      - ARANGO_NO_AUTH=0
    volumes:
      - ./config/arangodb:/var/lib/arangodb3
    # CRITICAL: NO PORT EXPOSURE - Internal network only
    # External access ONLY via nginx proxy manager (reverse proxy)
    # Uncomment for development debugging only, never in production
    # ports:
    #   - "8529:8529"  # ArangoDB Web UI (DEVELOPMENT ONLY)
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8529/_api/version"]
      interval: 10s
      timeout: 5s
      retries: 5

  nomarr:
    image: ghcr.io/xiaden/nomarr:latest
    container_name: nomarr
    user: "1000:1000"
    networks:
      - internal_network
    volumes:
      - ./config:/app/config
      - /media:/media
    environment:
      # Root password ONLY for first-run provisioning
      # App will create DB/user on first boot, then never use root again
      - ARANGO_ROOT_PASSWORD=${ARANGO_ROOT_PASSWORD}
      - ARANGO_HOSTS=http://nomarr-arangodb:8529
    depends_on:
      nomarr-arangodb:
        condition: service_healthy
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
    restart: unless-stopped

networks:
  internal_network:
    internal: true  # Isolated network (external access via nginx proxy manager)
  lidarr_network:
    external: true
```

**Add `.env` file for secrets:**

```bash
# .env (DO NOT COMMIT TO GIT)
# Root password used ONLY during first-run onboarding
# App generates and stores its own password in config after first boot
ARANGO_ROOT_PASSWORD=change_this_root_password_in_production
```

**First-Run Flow:**

1. **User runs `docker-compose up`**
   - ArangoDB starts with root password from `.env`
   - Nomarr starts, detects no config file

2. **First-boot onboarding**
   - Nomarr shows: "Welcome! Let's set up Nomarr."
   - Uses `ARANGO_ROOT_PASSWORD` from env to provision DB/user
   - Generates strong random password for `nomarr` user
   - Writes app credentials to `config/nomarr.yaml`
   - Root credentials never stored in app config

3. **Normal operation (all future boots)**
   - Config exists, first-run code path unreachable
   - App connects as `nomarr` user (NOT root)
   - Root password in `.env` is never used again

**Security improvements:**
- Root password used ONCE during onboarding
- App generates its own strong password (not user-chosen)
- No init container = simpler mental model for users
- No exposed ports (internal network only, NPM for external access)
- App connects as least-privileged user after first boot

**UX improvements:**
- Single `docker-compose up` command (no scary init containers)
- Natural onboarding flow with tutorials
- Consistent with modern self-hosted apps (GitLab, Immich, etc.)
- Easier to understand for non-DevOps users

### 7. Configuration Changes

**Update `config.yaml`:**

```yaml
# Database configuration (ArangoDB)
arango_hosts: http://nomarr-arangodb:8529
arango_username: nomarr
arango_password: nomarr_password  # Change in production!
arango_db_name: nomarr

# Legacy SQLite path (for migration tool)
db_path: /app/config/db/nomarr.db
```

**Environment variable mapping:**

```python
# config_svc.py
ENV_MAPPINGS = {
    "ARANGO_HOSTS": "arango_hosts",
    "ARANGO_USERNAME": "arango_username",
    "ARANGO_PASSWORD": "arango_password",
    "ARANGO_DB_NAME": "arango_db_name",
}
```

---

## Migration Strategy

### Phase 1: Add ArangoDB Support (Parallel)

1. Install `python-arango` dependency
2. Create `arango_client.py` connection factory
3. Create new `*_aql.py` operation classes alongside `*_sql.py`
4. Update `db.py` to support both SQLite and ArangoDB (feature flag)
5. Run tests against both databases

### Phase 2: Migration from SQLite (Optional - Not Recommended)

**Recommendation: Skip migration, require library re-scan**

Given:
- Pre-alpha status (breaking changes acceptable)
- Relative path storage (different from SQLite absolute paths)
- Auto-generated `_key` strategy (simpler than preserving old IDs)
- Library scanning is fast and non-destructive

**Best approach:** Delete SQLite DB, re-scan libraries with new ArangoDB backend.

**If you absolutely need migration**, see below script (complex, not recommended):

<details>
<summary>Migration script (optional, complex)</summary>

**Script: `scripts/migrate_sqlite_to_arango.py`**

```python
"""Migrate existing SQLite database to ArangoDB.

WARNING: This migration is complex and may not preserve all data correctly.
Recommendation: Skip migration and re-scan libraries instead.
"""

import json
import sqlite3
from pathlib import Path

from nomarr.persistence.arango_client import create_arango_client


def convert_absolute_to_relative(abs_path: str, library_root: str) -> str:
    """Convert absolute path to relative path."""
    try:
        return str(Path(abs_path).relative_to(library_root))
    except ValueError:
        # Path not within library root - skip
        return None


def migrate_library_files(sqlite_conn, arango_db, library_root: str):
    """Migrate library_files table to ArangoDB collection."""
    cursor = sqlite_conn.execute("SELECT * FROM library_files")
    collection = arango_db.collection("library_files")
    
    batch = []
    skipped = 0
    for row in cursor:
        # Convert absolute path to relative
        rel_path = convert_absolute_to_relative(row["path"], library_root)
        if not rel_path:
            skipped += 1
            continue
        
        doc = {
            # Use old ID as _key for deterministic mapping
            "_key": str(row["id"]),
            "path": rel_path,  # Relative path
            "library_id": row["library_id"],
            "file_size": row["file_size"],
            "modified_time": row["modified_time"],
            "duration_seconds": row["duration_seconds"],
            "artist": row["artist"],
            "album": row["album"],
            "title": row["title"],
            "calibration": json.loads(row["calibration"]) if row["calibration"] else {},
            "chromaprint": row["chromaprint"],
            "needs_tagging": row["needs_tagging"],
            "is_valid": row["is_valid"],
            "scanned_at": row["scanned_at"],
            "last_tagged_at": row["last_tagged_at"],
            "tagged": row["tagged"],
            "tagged_version": row["tagged_version"],
        }
        batch.append(doc)
        
        if len(batch) >= 1000:
            collection.import_bulk(batch, on_duplicate="replace")
            print(f"Migrated {len(batch)} library_files...")
            batch = []
    
    if batch:
        collection.import_bulk(batch, on_duplicate="replace")
        print(f"Migrated {len(batch)} library_files (final batch)")
    
    if skipped:
        print(f"Skipped {skipped} files outside library root")


def migrate_library_tags(sqlite_conn, arango_db):
    """Migrate library_tags table to ArangoDB collection."""
    cursor = sqlite_conn.execute("SELECT * FROM library_tags")
    collection = arango_db.collection("library_tags")
    
    batch = []
    for row in cursor:
        doc = {
            "_key": str(row["id"]),  # Use old ID as _key
            "key": row["key"],
            "value": row["value"],
            "is_nomarr_tag": row["is_nomarr_tag"],
        }
        batch.append(doc)
        
        if len(batch) >= 1000:
            collection.import_bulk(batch, on_duplicate="replace")
            batch = []
    
    if batch:
        collection.import_bulk(batch, on_duplicate="replace")


def migrate_file_tags(sqlite_conn, arango_db):
    """Migrate file_tags join table to ArangoDB edge collection."""
    cursor = sqlite_conn.execute("SELECT file_id, tag_id FROM file_tags")
    collection = arango_db.collection("file_tags")
    
    edges = []
    for row in cursor:
        # _key determinism: old IDs map directly to ArangoDB _keys
        edges.append({
            "_from": f"library_files/{row['file_id']}",
            "_to": f"library_tags/{row['tag_id']}",
        })
        
        if len(edges) >= 1000:
            collection.import_bulk(edges)
            print(f"Migrated {len(edges)} file_tags edges...")
            edges = []
    
    if edges:
        collection.import_bulk(edges)
        print(f"Migrated {len(edges)} file_tags edges (final batch)")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python migrate_sqlite_to_arango.py <library_root>")
        sys.exit(1)
    
    library_root = sys.argv[1]
    
    sqlite_conn = sqlite3.connect("/app/config/db/nomarr.db")
    sqlite_conn.row_factory = sqlite3.Row
    
    arango_db = create_arango_client(
        hosts="http://localhost:8529",
        username="nomarr",
        password="nomarr_password",
    )
    
    print("Migrating library_files...")
    migrate_library_files(sqlite_conn, arango_db, library_root)
    
    print("Migrating library_tags...")
    migrate_library_tags(sqlite_conn, arango_db)
    
    print("Migrating file_tags edges...")
    migrate_file_tags(sqlite_conn, arango_db)
    
    print("Migration complete!")
    print("\nNote: Other tables (meta, sessions, queues, health) are transient.")
    print("Recommendation: Verify data, then delete SQLite DB and re-scan if issues found.")
```

</details>

### Phase 3: Switch Default to ArangoDB

1. Update `Database` class to use ArangoDB by default
2. Remove SQLite code paths
3. Delete `*_sql.py` files
4. Update all tests to use ArangoDB

### Phase 4: Remove SQLite

1. Remove SQLite schema from `db.py`
2. Remove `sqlite3` imports
3. Update documentation

---

## Testing Strategy

### Unit Tests

**Mock ArangoDB for fast unit tests:**

```python
from unittest.mock import Mock

@pytest.fixture
def mock_arango_db():
    db = Mock()
    db.collection.return_value = Mock()
    db.aql.execute.return_value = iter([{"_key": "123"}])
    return db
```

### Integration Tests

**Use ArangoDB testcontainer:**

```python
import pytest
from testcontainers.arangodb import ArangoDbContainer

@pytest.fixture(scope="session")
def arango_container():
    with ArangoDbContainer("arangodb:3.11") as container:
        yield container
```

### Migration Tests

**Test SQLite → ArangoDB migration:**

```python
def test_migration_preserves_data(temp_sqlite_db, arango_container):
    # Populate SQLite with test data
    # Run migration
    # Verify data in ArangoDB matches
    pass
```

---

## Performance Considerations

### Connection Pooling

ArangoDB client manages connection pool automatically:
- Default pool size: 10 connections
- Thread-safe within a single process
- **Per-process pools**: Each process creates its own client + pool

**Pattern: One `Database` instance per process, created at process startup**

```python
# At process startup (after fork/spawn boundaries)
app = Application()
app.db = Database()  # Creates client + pool for this process

# Multiple threads in this process share the pool
# Other processes create their own Database instances
```

**Lifecycle management:**
- Create `Database()` after fork/spawn (not before)
- Inject into services/workflows via constructor (dependency injection)
- Clean shutdown: call `db.close()` before process exit (though ArangoDB client handles cleanup)

**Note:** While ArangoDB's pooling handles thread-safety automatically, you still need proper application-level lifecycle management to ensure one instance per process and clean dependency injection.

### Batch Operations

Use `import_bulk` for large inserts:

```python
# Efficient batch insert
documents = [{"path": f"/media/file{i}.mp3"} for i in range(10000)]
collection.import_bulk(documents, batch_size=1000)
```

### Query Optimization

- Use indexes on filtered fields
- Limit result sets (`LIMIT 1000`)
- Use `COLLECT` for aggregations (like SQL GROUP BY)
- Profile slow queries with `explain()`:

```python
query = """
    FOR file IN library_files
        FILTER file.library_id == @library_id
        RETURN file
"""
explanation = db.aql.explain(query, bind_vars={"library_id": 1})
print(explanation)
```

---

## Benefits Summary

### Solved Problems

✅ **Multi-process concurrency** - No more `SQLITE_BUSY` errors
✅ **Write contention** - Multiple processes can write simultaneously
✅ **Horizontal scaling** - Supports clustering when needed
✅ **Schema flexibility** - Add fields without ALTER TABLE migrations
✅ **Native JSON** - No TEXT serialization for `calibration` field
✅ **Graph queries** - Efficient tag relationship traversals
✅ **Built-in Web UI** - Database administration at http://localhost:8529

### Trade-offs

⚠️ **External dependency** - ArangoDB service required (not embedded)
⚠️ **More complex deployment** - Additional container to manage
⚠️ **Learning curve** - AQL vs SQL (but similar concepts)
⚠️ **Migration effort** - ~2 weeks to rewrite all queries

---

## Deployment

### Development

```bash
# Start ArangoDB
docker-compose up -d nomarr-arangodb

# Access Web UI via:
#   1. Nginx proxy manager (production/dev external access)
#   2. docker exec -it nomarr-arangodb arangosh (CLI access)
# No ports exposed - internal network only

# Run Nomarr
docker-compose up nomarr
```

### Production

**Secure ArangoDB:**

1. **First-Run Provisioning:**
   - Root password in `.env` used ONLY during onboarding
   - App generates strong random password for `nomarr` user
   - Root credentials never stored in app config
   - After first boot, root password in `.env` is never accessed again

2. **Privilege Separation:**
   - App connects as `nomarr` user (least-privileged)
   - No persistent root credentials in app container
   - First-run code path is one-way door (cannot be re-entered)

3. **Password Management:**
   - App-generated password stored in persistent config volume
   - Strong entropy (32+ byte secrets)
   - Rotate by deleting config and re-running first-boot

4. **Network:**
   - Internal network only (no public exposure)
   - TLS/SSL for production
   - Firewall rules restrict access

5. **Backups:**
   - `arangodump` scheduled backups
   - Store backups off-site
   - Test restore procedures

**Example production config:**

```yaml
nomarr-arangodb:
  image: arangodb:3.11
  environment:
    - ARANGO_ROOT_PASSWORD=${ARANGO_ROOT_PASSWORD}
    - ARANGO_NO_AUTH=0
  volumes:
    - arangodb_data:/var/lib/arangodb3
    - arangodb_apps:/var/lib/arangodb3-apps
  networks:
    - internal_network  # No public exposure
  # NO ports published
  restart: always

volumes:
  arangodb_data:
  arangodb_apps:

networks:
  internal_network:
    internal: true  # Fully isolated
```

---

## Migration Progress (2026-01-13)

**Phase 1-2 COMPLETE** ✅

All core ArangoDB infrastructure and AQL operations modules have been implemented:

**Foundation (Phase 1):**
- ✅ `python-arango` dependency added
- ✅ [persistence/arango_client.py](../../nomarr/persistence/arango_client.py) - Connection factory
- ✅ [components/platform/arango_first_run_comp.py](../../nomarr/components/platform/arango_first_run_comp.py) - Secure first-run provisioning
- ✅ [components/platform/arango_bootstrap_comp.py](../../nomarr/components/platform/arango_bootstrap_comp.py) - Schema initialization
- ✅ [docker-compose.yml](../../docker-compose.yml) - ArangoDB service (no exposed ports)
- ✅ [.env.example](../../.env.example) - Environment variable template

**Core Operations (Phase 2):**
- ✅ [persistence/database/library_files_aql.py](../../nomarr/persistence/database/library_files_aql.py)
- ✅ [persistence/database/library_tags_aql.py](../../nomarr/persistence/database/library_tags_aql.py)
- ✅ [persistence/database/file_tags_aql.py](../../nomarr/persistence/database/file_tags_aql.py) - Edge collection
- ✅ [persistence/database/tag_queue_aql.py](../../nomarr/persistence/database/tag_queue_aql.py)
- ✅ [persistence/database/libraries_aql.py](../../nomarr/persistence/database/libraries_aql.py)
- ✅ [persistence/database/calibration_queue_aql.py](../../nomarr/persistence/database/calibration_queue_aql.py)
- ✅ [persistence/database/calibration_runs_aql.py](../../nomarr/persistence/database/calibration_runs_aql.py)
- ✅ [persistence/database/meta_aql.py](../../nomarr/persistence/database/meta_aql.py)
- ✅ [persistence/database/sessions_aql.py](../../nomarr/persistence/database/sessions_aql.py)
- ✅ [persistence/database/health_aql.py](../../nomarr/persistence/database/health_aql.py)
- ✅ [persistence/db.py](../../nomarr/persistence/db.py) - Database class updated for ArangoDB

**Architectural Compliance:**
- ✅ Universal `PARSE_IDENTIFIER(@id).key` pattern for all mutations
- ✅ Returns `_id` (not integer IDs) from all operations
- ✅ Stores relative paths (portable across library roots)
- ✅ Native JSON for calibration metadata
- ✅ Edge collection for file→tag relationships
- ✅ Graph capabilities (`file_tag_graph` defined)
- ✅ First-run provisioning in `components/` (not `persistence/`)
- ✅ Secure password generation (no defaults)
- ✅ No exposed ports (internal network only)

**Remaining Work:**
- [ ] Update services to use `_id` returns from persistence
- [ ] Update workflows for `_id` identity throughout
- [ ] Wire first-run detection + schema bootstrap into app startup
- [ ] Add ArangoDB config handling (hosts, username, password fields)
- [ ] Verify chromaprint move detection still deterministic
- [ ] Update unit tests for AQL operations
- [ ] Performance testing and optimization
- [ ] Remove SQLite code paths
- [ ] Final QC checks (mypy, ruff, import-linter)

**Status:** Type system migration 91% complete (231 errors remaining).

**Progress:** 263 → 231 errors

**Changes:**
- ✅ All DTOs updated to `id: str`
- ✅ Services/workflows/API routes use str IDs
- ✅ SQLite files renamed to .bak (12 files)
- ✅ path_dto.py library_id parameter fixed (int→str)

**Remaining Errors (231):**
- ~220 AQL cursor type narrowing (python-arango union type issue)
- ~11 analytics_queries.py uses db.conn (needs ArangoDB port or deletion)

**Decision needed:** 
- analytics_queries.py: Port to ArangoDB AQL or remove? (Used for tag correlation stats, co-occurrence analysis)

---

## Architectural Decisions (Pre-Implementation)

### 1. DB-Primary + _id Everywhere

**Decision:** Use `_id` (e.g., `library_files/12345`) as primary identity across all workflows and DTOs.

**Requires:** Universal `PARSE_IDENTIFIER(@id).key` pattern for UPDATE/REMOVE mutations in persistence layer.

**Enforcement:** All `*_aql.py` modules must follow this pattern. See UPDATE example above.

### 2. Persistence Layer Boundary

**Decision:** Persistence is "AQL only" - database operations with NO upward dependencies.

**First-run provisioning:** Lives in `components/infrastructure/`, NOT `persistence/`.

**Rationale:** Provisioning requires config file I/O (higher-level concern than database queries).

**Enforcement:** import-linter rules prevent persistence from importing components/services.

### 3. No Port Exposure

**Decision:** ArangoDB runs on internal network only. External access ONLY via nginx proxy manager.

**Docker Compose:** Port 8529 must remain commented out (except for local development debugging).

**Rationale:** Defense in depth - no direct database exposure to public networks.

### 4. Move Detection Determinism

**Decision:** Sort candidate files by stable ID before matching to ensure deterministic reconciliation.

**Context:** When multiple missing files share same chromaprint, DB cursor order is non-deterministic.

**Implementation:** Already completed in `scan_library_direct_wf.py` (lines 242-243):
```python
files_to_remove.sort(key=lambda f: f["id"])
```

**Rationale:** Predictable behavior enables debugging and prevents user confusion when duplicates exist.

---

## Migration Timeline

### Week 1: Foundation ✅ COMPLETE
- [x] Add `python-arango` dependency
- [x] Create `arango_client.py`
- [x] Update `docker-compose.yml`
- [x] Create ArangoDB schema initialization
- [x] Test basic connection

### Week 2: Core Operations ✅ COMPLETE
- [x] Rewrite `library_files_aql.py`
- [x] Rewrite `library_tags_aql.py`
- [x] Rewrite `file_tags_aql.py` (edge collection)
- [x] Rewrite `tag_queue_aql.py`
- [x] Rewrite `libraries_aql.py`
- [x] Rewrite `calibration_queue_aql.py`
- [x] Rewrite `calibration_runs_aql.py`
- [x] Rewrite `meta_aql.py`
- [x] Rewrite `sessions_aql.py`
- [x] Rewrite `health_aql.py`
- [x] Update `Database` class ⏳ IN PROGRESS
- [ ] Update unit tests

### Week 3: Integration & Services ⏳ IN PROGRESS
- [ ] Update services to use `_id` returns
- [ ] Update workflows for `_id` identity
- [ ] Verify chromaprint move detection
- [ ] Update integration tests

### Week 4: Completion & QC
- [ ] Update app.py startup wiring
- [ ] Add config handling for ArangoDB
- [ ] Performance testing
- [ ] Update documentation
- [ ] Remove SQLite code
- [ ] Run QC checks (mypy, ruff, import-linter)

---

## Open Questions

1. **Identity strategy: RESOLVED**
   - Use `_id` as primary identity in all workflows and DTOs
   - DB-primary architecture: database record IS the song
   - Filesystem path is a locator attribute, not identity
   - Trade-off: Explicit ArangoDB commitment, but aligns with actual system behavior
   
2. **Transactions**: Do we need ACID transactions for any operations?
   - ArangoDB supports multi-document transactions
   - Most operations are single-doc (atomic by default)
   - **Important**: Multi-step logical operations (read → compute → write across documents) must be wrapped in explicit ArangoDB transactions if consistency matters. The DB provides atomicity per-document, but not magic for multi-document workflows.
   
3. **Backup strategy**: How to backup ArangoDB in production?
   - `arangodump` / `arangorestore` tools
   - Can run as cron job
   
4. **Monitoring**: How to monitor ArangoDB health?
   - Built-in metrics at `/_admin/metrics`
   - Prometheus exporter available
   
5. **Clustering**: When to enable clustering?
   - Start single-node
   - Enable clustering when > 10k files or high concurrency

---

## Next Steps

1. **Review and approve this refactor document**
2. **Create feature branch**: `feature/arangodb-migration`
3. **Start with Phase 1**: Parallel ArangoDB support
4. **Incremental rollout**: Test thoroughly before switching default

---

End of document.
