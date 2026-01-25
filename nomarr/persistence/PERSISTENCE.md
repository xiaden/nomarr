# Persistence Layer

The **persistence layer** handles all database access for Nomarr. It's a thin wrapper around ArangoDB that provides type-safe, domain-organized operations for collections, documents, and queries.

Persistence is:

- **Pure data access** (no business logic)
- **AQL-based** (leveraging ArangoDB's query language)
- **Injected** (never imported by helpers)

> **Rule:** Persistence knows nothing about business rules. It's CRUD + queries, nothing more.

---

## 1. Position in the Architecture

Layers:

- **Interfaces** – HTTP/CLI/SSE, Pydantic, auth, HTTP status codes
- **Services** – dependency wiring, thin orchestration, DTO boundaries
- **Workflows** – domain flows, multi-step operations, control logic
- **Components** – heavy computations, analytics, ML, tagging
- **Persistence** – DB access, AQL queries
- **Helpers** – stateless utilities, DTOs, exceptions

Persistence sits **alongside components** at the bottom of the stack:

- **Components** use **persistence** (e.g., ML tagging reads file metadata)
- **Persistence** uses **helpers** (e.g., time utilities, DTOs)
- **Persistence never imports** services, workflows, or interfaces

---

## 2. Directory Structure & Naming

Persistence lives under `nomarr/persistence/`:

```text
persistence/
├── arango_client.py              # Factory for ArangoDB connections
├── db.py                          # Database class (wires all operations)
└── database/                      # Operations classes (one per collection)
    ├── calibration_history_aql.py
    ├── calibration_state_aql.py
    ├── health_aql.py
    ├── libraries_aql.py
    ├── library_files_aql.py
    ├── library_folders_aql.py
    ├── meta_aql.py
    ├── ml_capacity_aql.py
    ├── sessions_aql.py
    ├── tags_aql.py                # Unified tag operations (TAG_UNIFICATION_REFACTOR)
    ├── worker_claims_aql.py
    └── worker_restart_policy_aql.py
```

Naming rules:

- **Operations files:** `<collection_name>_aql.py` (e.g., `libraries_aql.py`)
- **Operations class:** `<CollectionName>Operations` (e.g., `LibrariesOperations`)
- **Methods:** Verb-noun names describing the operation (e.g., `create_library`, `get_library_by_id`)

---

## 3. Core Components

### 3.1 Database Class (`db.py`)

**Purpose:** Single entry point for all database operations.

**Responsibilities:**
- Establish connection to ArangoDB
- Wire all `*Operations` classes
- Expose operations via named attributes
- Handle schema versioning and bootstrap

**Usage pattern:**
```python
# Services receive db as parameter
db = Database(hosts=config.arango_host, password=config.arango_password)

# Access operations via attributes
library_id = db.libraries.create_library(name="My Library", root_path="/music")
files = db.library_files.get_files_for_library(library_id)
```

**Key features:**
- **Connection pooling:** Handled automatically by python-arango
- **Thread-safe:** Within a single process
- **Hardcoded credentials:** Username and db_name are `"nomarr"` (not user-configurable)
- **Schema versioning:** Additive-only, no migrations

### 3.2 ArangoDB Client Factory (`arango_client.py`)

**Purpose:** Create ArangoDB connections.

**Usage:**
```python
from nomarr.persistence.arango_client import create_arango_client

db = create_arango_client(
    hosts="http://localhost:8529",
    username="nomarr",
    password="secret",
    db_name="nomarr"
)
```

**Note:** Typically called by `Database` class, not directly by application code.

### 3.3 Operations Classes (`database/*_aql.py`)

**Purpose:** Collection-oriented data access (one class per collection).

**Pattern:**
```python
class LibrariesOperations:
    """Operations for the libraries collection."""
    
    def __init__(self, db: StandardDatabase) -> None:
        self.db = db
        self.collection = db.collection("libraries")
    
    def create_library(self, name: str, root_path: str) -> str:
        """Create a new library entry."""
        result = self.collection.insert({"name": name, "root_path": root_path})
        return result["_id"]
    
    def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
        """Get library by _id."""
        cursor = self.db.aql.execute(
            "FOR lib IN libraries FILTER lib._id == @id RETURN lib",
            bind_vars={"id": library_id}
        )
        return cursor.next() if cursor.count() > 0 else None
```

**Each operations class:**
- Accepts `StandardDatabase` in `__init__`
- Stores reference to its collection
- Provides CRUD + query methods
- Returns native Python types or None

---

## 4. What Belongs in Persistence

### 4.1 CRUD Operations

Basic create, read, update, delete:

```python
def create_library(self, name: str, root_path: str) -> str:
    """Create a new library entry."""
    
def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
    """Get library by _id."""
    
def update_library(self, library_id: str, updates: dict[str, Any]) -> None:
    """Update library fields."""
    
def delete_library(self, library_id: str) -> None:
    """Delete library by _id."""
```

### 4.2 Queries

Domain-specific queries (filtering, aggregation, joins):

```python
def get_unprocessed_files(self, limit: int | None = None) -> list[dict[str, Any]]:
    """Get files missing ML tags."""
    
def get_library_stats(self, library_id: str) -> dict[str, int]:
    """Get file count, tagged count for library."""
    
def find_similar_songs(self, song_id: str, threshold: float, limit: int) -> list[dict[str, Any]]:
    """Find songs with similar embeddings."""
```

### 4.3 Batch Operations

Efficient bulk operations:

```python
def bulk_insert_files(self, files: list[dict[str, Any]]) -> None:
    """Insert multiple files in one transaction."""
    
def bulk_update_tags(self, updates: list[tuple[str, dict[str, Any]]]) -> None:
    """Update tags for multiple files."""
```

### 4.4 Existence Checks

Fast boolean checks without fetching documents:

```python
def library_exists(self, library_id: str) -> bool:
    """Check if library exists."""
    
def file_exists_in_library(self, library_id: str, file_path: str) -> bool:
    """Check if file exists at path in library."""
```

---

## 5. What Does NOT Belong in Persistence

### ❌ Business Logic

**Bad:**
```python
def should_process_file(self, file_id: str) -> bool:
    """Check if file needs processing."""
    file = self.get_file_by_id(file_id)
    if file["force_reprocess"]:
        return True
    if file["ml_tags_generated_at"] is None:
        return True
    return False
```

**Why:** Contains business rules (force reprocess, tag staleness).

**Fix:** Move to a workflow. Persistence only returns data.

### ❌ Validation

**Bad:**
```python
def create_library(self, name: str, root_path: str) -> str:
    """Create a new library entry."""
    if not name:
        raise ValueError("Library name required")
    if not Path(root_path).exists():
        raise ValueError("Root path must exist")
    # ...
```

**Why:** Validation is a service/workflow concern.

**Fix:** Validate before calling persistence. Let database handle constraint violations.

### ❌ Orchestration

**Bad:**
```python
def create_library_with_scan(self, name: str, root_path: str) -> str:
    """Create library and trigger scan."""
    library_id = self.create_library(name, root_path)
    self.queue_scan_job(library_id)
    return library_id
```

**Why:** Multi-step orchestration belongs in workflows.

**Fix:** Persistence only handles the `create_library` part. Workflow calls both.

### ❌ DTO Transformation

**Bad:**
```python
def get_library_for_api(self, library_id: str) -> LibraryDict:
    """Get library formatted for API response."""
    lib = self.get_library_by_id(library_id)
    return LibraryDict(
        id=lib["_id"],
        name=lib["name"],
        root_path=lib["root_path"],
        file_count=lib["file_count"],
        tagged_count=lib["tagged_count"]
    )
```

**Why:** DTO mapping is a service boundary concern.

**Fix:** Persistence returns raw dict. Service transforms to DTO.

---

## 6. ArangoDB Patterns

### 6.1 Document Keys vs IDs

**Critical rule:** Never rename `_id` or `_key`.

ArangoDB uses:
- `_id`: Full document identifier (e.g., `"libraries/12345"`)
- `_key`: Collection-local identifier (e.g., `"12345"`)

**When mutating by _id, extract the key:**

```python
# ✅ Correct - extract key from _id
self.db.aql.execute(
    """
    UPDATE PARSE_IDENTIFIER(@id).key WITH @updates IN libraries
    """,
    bind_vars={"id": library_id, "updates": updates}
)

# ❌ Wrong - will fail if library_id includes collection prefix
self.db.aql.execute(
    """
    UPDATE @id WITH @updates IN libraries
    """,
    bind_vars={"id": library_id, "updates": updates}
)
```

**Why:** `_id` may include collection prefix. AQL UPDATE/REMOVE require the key only.

### 6.2 Bind Variables

**Always use bind variables** for user input:

```python
# ✅ Correct - parameterized query
cursor = self.db.aql.execute(
    "FOR lib IN libraries FILTER lib.name == @name RETURN lib",
    bind_vars={"name": library_name}
)

# ❌ Wrong - SQL injection risk
cursor = self.db.aql.execute(
    f"FOR lib IN libraries FILTER lib.name == '{library_name}' RETURN lib"
)
```

### 6.3 Return Values

**Pattern:** Return native Python types or None.

```python
# Single document - return dict or None
def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
    cursor = self.db.aql.execute(...)
    return cursor.next() if cursor.count() > 0 else None

# Multiple documents - return list
def get_all_libraries(self) -> list[dict[str, Any]]:
    cursor = self.db.aql.execute(...)
    return list(cursor)

# Scalar - return primitive or None
def get_file_count(self, library_id: str) -> int:
    cursor = self.db.aql.execute(...)
    result = cursor.next()
    return result["count"]
```

### 6.4 Timestamps

**Rule:** Use wall clock timestamps for persistence.

```python
from nomarr.helpers.time_helper import now_ms

def create_library(self, name: str, root_path: str) -> str:
    now = now_ms()
    result = self.collection.insert({
        "name": name,
        "root_path": root_path,
        "created_at": now,      # Wall clock
        "updated_at": now       # Wall clock
    })
    return result["_id"]
```

**Never use:**
- `internal_ms()` / `internal_s()` (monotonic) - Not for persistence!
- `time.time()` directly - Use helpers for type safety

### 6.5 Error Handling

**Let ArangoDB exceptions propagate:**

```python
# ✅ Correct - let exception bubble up
def create_library(self, name: str, root_path: str) -> str:
    result = self.collection.insert({"name": name, "root_path": root_path})
    return result["_id"]

# ❌ Wrong - swallow database errors
def create_library(self, name: str, root_path: str) -> str | None:
    try:
        result = self.collection.insert({"name": name, "root_path": root_path})
        return result["_id"]
    except Exception:
        return None
```

**Why:** Services/workflows handle error mapping. Persistence surfaces database errors as-is.

---

## 7. Schema Management

### 7.1 Schema Versioning

**Policy:** Additive-only changes.

```python
# db.py
SCHEMA_VERSION = 3  # GPU/CPU adaptive resource management collections
```

Schema changes require:
1. Increment `SCHEMA_VERSION`
2. Add new collections/indexes to bootstrap
3. Document manual intervention if destructive

**Pre-alpha:** Breaking changes are acceptable. No migrations.

**Post-1.0:** Must build migration framework or maintain additive-only.

### 7.2 Bootstrap Process

Schema bootstrap is **idempotent**:
- Creates missing collections
- Creates missing indexes
- Does NOT handle:
  - Index changes (must drop manually)
  - Collection renames (manual intervention)
  - Data migrations (not supported)

### 7.3 Collections

**Current collections** (schema v3):
- `libraries` - Library roots
- `library_files` - Audio files
- `library_folders` - Folder metadata
- `library_tags` - Available tags
- `file_tags` - ML-generated tags (document store)
- `song_tag_edges` - Tag relationships (edges)
- `entities` - Shared entities (artists, albums)
- `sessions` - User sessions
- `meta` - System metadata
- `health` - Health telemetry
- `worker_claims` - Worker resource claims
- `worker_restart_policy` - Worker restart state
- `ml_capacity` - ML capacity monitoring
- `calibration_state` - Calibration state
- `calibration_history` - Calibration history

---

## 8. Testing Persistence

### 8.1 Test Structure

Persistence tests use a real ArangoDB instance (test database):

```python
@pytest.fixture
def db():
    """Provide test database."""
    db = Database(hosts="http://localhost:8529", password="test_password")
    yield db
    # Cleanup test data

def test_create_library(db):
    """Test library creation."""
    library_id = db.libraries.create_library(name="Test", root_path="/test")
    assert library_id.startswith("libraries/")
```

### 8.2 Cleanup

Tests must clean up after themselves:

```python
def test_library_operations(db):
    """Test library CRUD."""
    # Create
    library_id = db.libraries.create_library(name="Test", root_path="/test")
    
    # Test operations
    library = db.libraries.get_library_by_id(library_id)
    assert library["name"] == "Test"
    
    # Cleanup
    db.libraries.delete_library(library_id)
```

### 8.3 Test Isolation

Each test should be independent:
- Use unique names/keys
- Don't rely on test order
- Clean up in try/finally or fixtures

---

## 9. Common Patterns

### 9.1 Single Document Query

```python
def get_library_by_id(self, library_id: str) -> dict[str, Any] | None:
    """Get library by _id."""
    cursor = self.db.aql.execute(
        "FOR lib IN libraries FILTER lib._id == @id RETURN lib",
        bind_vars={"id": library_id}
    )
    return cursor.next() if cursor.count() > 0 else None
```

### 9.2 Multiple Documents Query

```python
def get_enabled_libraries(self) -> list[dict[str, Any]]:
    """Get all enabled libraries."""
    cursor = self.db.aql.execute(
        "FOR lib IN libraries FILTER lib.is_enabled == true RETURN lib"
    )
    return list(cursor)
```

### 9.3 Aggregation Query

```python
def get_library_stats(self, library_id: str) -> dict[str, int]:
    """Get file count and tagged count for library."""
    cursor = self.db.aql.execute(
        """
        LET files = (
            FOR f IN library_files
            FILTER f.library_id == @library_id
            RETURN f
        )
        LET tagged = (
            FOR f IN files
            FILTER f.ml_tags_generated_at != null
            RETURN 1
        )
        RETURN {
            file_count: LENGTH(files),
            tagged_count: LENGTH(tagged)
        }
        """,
        bind_vars={"library_id": library_id}
    )
    return cursor.next()
```

### 9.4 Update with PARSE_IDENTIFIER

```python
def update_library(self, library_id: str, updates: dict[str, Any]) -> None:
    """Update library fields."""
    self.db.aql.execute(
        """
        UPDATE PARSE_IDENTIFIER(@id).key 
        WITH @updates 
        IN libraries
        """,
        bind_vars={"id": library_id, "updates": updates}
    )
```

### 9.5 Batch Insert

```python
def bulk_insert_files(self, files: list[dict[str, Any]]) -> None:
    """Insert multiple files in one transaction."""
    self.collection.insert_many(files)
```

### 9.6 Existence Check

```python
def library_exists(self, library_id: str) -> bool:
    """Check if library exists."""
    cursor = self.db.aql.execute(
        "RETURN LENGTH(FOR lib IN libraries FILTER lib._id == @id RETURN 1) > 0",
        bind_vars={"id": library_id}
    )
    return cursor.next()
```

---

## 10. Method Naming Conventions

### Verb Patterns

- **get_*** - Fetch single document (returns dict or None)
- **get_all_*** - Fetch multiple documents (returns list)
- **find_*** - Query/search (returns list, may be empty)
- **create_*** - Insert new document (returns _id)
- **update_*** - Modify existing document (returns None)
- **delete_*** - Remove document (returns None)
- **count_*** - Aggregation (returns int)
- **exists_*** - Boolean check (returns bool)
- **list_*** - Fetch collection metadata (returns list)

### Examples

```python
# Single document
get_library_by_id(library_id: str) -> dict[str, Any] | None
get_library_by_name(name: str) -> dict[str, Any] | None

# Multiple documents
get_all_libraries() -> list[dict[str, Any]]
get_enabled_libraries() -> list[dict[str, Any]]

# Query/search
find_libraries_by_path(root_path: str) -> list[dict[str, Any]]
find_unprocessed_files(limit: int) -> list[dict[str, Any]]

# Create
create_library(name: str, root_path: str) -> str

# Update
update_library(library_id: str, updates: dict[str, Any]) -> None

# Delete
delete_library(library_id: str) -> None

# Aggregation
count_libraries() -> int
count_files_in_library(library_id: str) -> int

# Existence
library_exists(library_id: str) -> bool
file_exists_in_library(library_id: str, file_path: str) -> bool
```

---

## 11. Import Rules

### Allowed Imports:
- ✅ `arango` (python-arango client)
- ✅ `nomarr.helpers.*` (time utilities, DTOs, exceptions)
- ✅ Standard library (`typing`, etc.)

### Forbidden Imports:
- ❌ `nomarr.services.*`
- ❌ `nomarr.workflows.*`
- ❌ `nomarr.components.*`
- ❌ `nomarr.interfaces.*`

**Rationale:** Persistence is at the bottom of the stack. It can't depend on higher layers.

---

## 12. Connection Management

### 12.1 Connection Pooling

**Handled automatically** by python-arango:
- Pool size managed by client
- Thread-safe within a single process
- Each process creates its own pool

**No manual pool management needed.**

### 12.2 Multi-Process

Each process needs its own `Database` instance:
- Spawn worker → create new `Database()`
- Worker exit → connection pool cleaned up automatically

**Don't share Database instances across process boundaries.**

### 12.3 First-Run Provisioning

First run requires special handling:
- App connects as root to provision database
- Creates `nomarr` user and database
- Generates app password
- Stores password in config file

After first run, app connects as `nomarr` user.

---

## 13. Performance Considerations

### 13.1 Use Indexes

Query performance depends on proper indexes:
```python
# Ensure indexes exist during schema bootstrap
self.db.collection("libraries").add_hash_index(fields=["name"], unique=True)
self.db.collection("library_files").add_persistent_index(fields=["library_id"])
```

### 13.2 Limit Result Sets

Always provide limits for unbounded queries:
```python
def get_unprocessed_files(self, limit: int = 100) -> list[dict[str, Any]]:
    cursor = self.db.aql.execute(
        "FOR f IN library_files FILTER f.ml_tags_generated_at == null LIMIT @limit RETURN f",
        bind_vars={"limit": limit}
    )
    return list(cursor)
```

### 13.3 Batch Operations

Use bulk operations when possible:
```python
# ✅ Efficient - single transaction
self.collection.insert_many(files)

# ❌ Slow - N transactions
for file in files:
    self.collection.insert(file)
```

### 13.4 Cursor Iteration

For large result sets, iterate cursor instead of materializing list:
```python
# ✅ Memory-efficient
cursor = self.db.aql.execute("FOR f IN library_files RETURN f")
for file in cursor:
    process_file(file)

# ❌ Memory-intensive
files = list(cursor)
for file in files:
    process_file(file)
```

---

## 14. Summary

**Persistence is:**
- Pure data access layer
- AQL-based queries
- Collection-organized operations (one class per collection)
- Type-safe, dependency-injected

**Persistence is NOT:**
- Business logic
- Validation
- Orchestration
- DTO transformation
- Domain-level aggregates (workflows compose from multiple collections)

**Think of persistence as:** A thin, type-safe wrapper around ArangoDB that provides collection-focused access without imposing business rules. Domain orchestration happens at the workflow layer.
