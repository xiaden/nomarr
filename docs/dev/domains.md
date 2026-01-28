# Domain Architecture

**Audience:** Developers making "where does this code belong?" decisions.

Nomarr architecture has TWO orthogonal organizing principles:

## Layers (Horizontal Lines)

```
interfaces  ← Transport (HTTP, CLI)
services    ← Wiring, DI
workflows   ← Orchestration
components  ← Atomic operations
persistence ← Database access
helpers     ← Pure utilities
```

Layers define **dependency direction** and **what kind of code**.

## Domains (Vertical Lines)

```
library | tagging | ml | metadata | analytics
   |        |       |       |           |
   v        v       v       v           v
[Data + Invariants + Public API]
```

Domains define **data ownership** and **invariant enforcement**.

---

## What is a Domain?

A domain is a **vertical slice** through the layers that encapsulates:

### 1. Data Ownership
The domain owns specific database collections/tables.

**Example - Library Domain:**
- `library_files` - File records, paths, metadata
- `library_folders` - Folder cache, mtimes
- `libraries` - Library definitions, scan state

### 2. Invariants
Rules that MUST stay true about that data.

**Example - Library Domain Invariants:**
- Every file path must be under its library's root
- File paths must be unique within a library
- Folder mtimes determine "needs scan"
- Scan progress must be 0-100%

### 3. Public API
**Components** that enforce invariants when reading/writing data.

**Example:**
```python
# Library domain component
def add_file_to_library(db, library_id, file_path, metadata):
    # Enforce invariants:
    library = db.libraries.get(library_id)
    if not is_path_under_root(file_path, library["root_path"]):
        raise ValueError("Path not under library root")
    
    if db.library_files.path_exists(file_path):
        raise ValueError("File already exists")
    
    # Write to owned collection
    db.library_files.insert({
        "path": file_path,
        "library_id": library_id,
        **metadata
    })
```

### 4. Private Implementation
Direct persistence access is **private** to the domain.

**Rule:** Other domains CANNOT call `db.library_files` directly. They MUST call library domain components.

---

## Critical Rules

### Rule 1: Components Enforce Invariants

**Only components may import from persistence.**

```python
# ✅ GOOD - Component imports persistence
# components/library/add_file_comp.py
from nomarr.persistence.db import Database

def add_file_to_library(db: Database, library_id: str, file_path: str):
    # Enforce invariants, then write
    db.library_files.insert(...)

# ✅ GOOD - Workflow calls component
# workflows/library/scan_library_wf.py
from nomarr.components.library.add_file_comp import add_file_to_library

def scan_library(db, library_id):
    for file_path in discovered_files:
        add_file_to_library(db, library_id, file_path)

# ❌ BAD - Workflow imports persistence
# workflows/library/scan_library_wf.py
from nomarr.persistence.db import Database

def scan_library(db):
    db.library_files.insert(...)  # BYPASSES INVARIANTS!
```

**Why:** If workflows access persistence directly, invariants aren't enforced. Data corruption ensues.

### Rule 2: One Function Per Component

**Components contain exactly ONE public function. No private helpers.**

If you have private helpers, they should be separate components.

```python
# ❌ BAD - Private helpers hide complexity
# components/metadata/entity_seeding_comp.py
def seed_song_entities(db, file_id, tags):
    artist_key = _normalize_artist(tags["artist"])  # Private helper
    album_key = _normalize_album(tags["album"])      # Private helper
    _create_vertices(db, artist_key, album_key)      # Private helper
    _create_edges(db, file_id, artist_key)           # Private helper

def _normalize_artist(name):
    ...

def _normalize_album(name):
    ...

# ✅ GOOD - Each operation is a component
# components/metadata/normalize_artist_key_comp.py
def normalize_artist_key(artist_name: str) -> str:
    return artist_name.lower().strip()

# components/metadata/normalize_album_key_comp.py
def normalize_album_key(album_name: str) -> str:
    return album_name.lower().strip()

# components/metadata/create_entity_vertices_comp.py
def create_entity_vertices(db: Database, artist_key: str, album_key: str):
    if not db.entities.exists(artist_key):
        db.entities.insert({"_key": artist_key, "type": "artist"})
    if not db.entities.exists(album_key):
        db.entities.insert({"_key": album_key, "type": "album"})

# components/metadata/create_entity_edges_comp.py
def create_entity_edges(db: Database, file_id: str, artist_key: str, album_key: str):
    db.entity_edges.insert({"_from": file_id, "_to": artist_key, "type": "artist"})
    db.entity_edges.insert({"_from": file_id, "_to": album_key, "type": "album"})

# workflows/metadata/seed_entities_wf.py
def seed_song_entities_workflow(db, file_id, tags):
    # Explicit composition in workflow
    artist_key = normalize_artist_key(tags["artist"])
    album_key = normalize_album_key(tags["album"])
    create_entity_vertices(db, artist_key, album_key)
    create_entity_edges(db, file_id, artist_key, album_key)
```

**Why:**
- Each component is independently testable
- Composition is visible in workflows
- Components are reusable building blocks
- Call graph shows exact dependencies
- No hidden complexity

**Yes, this creates hundreds of small components. That's the point.**

### Rule 3: Cross-Domain via Components Only

**To write to another domain's data, call its components.**

```python
# ✅ GOOD - Library workflow calls metadata domain API
from nomarr.components.metadata import create_entity_vertices_comp

def scan_library_workflow(db, library_id):
    for file in files:
        # Library domain writes to library_files
        add_file_to_library(db, library_id, file.path)
        
        # Metadata domain writes to entities (via its component)
        create_entity_vertices_comp(db, artist_key, album_key)

# ❌ BAD - Library workflow bypasses metadata domain
def scan_library_workflow(db, library_id):
    for file in files:
        add_file_to_library(db, library_id, file.path)
        
        # BYPASS! No invariant enforcement!
        db.entities.insert({"_key": artist_key})
```

**Metaphor:** Domains are like in-process microservices. You call their API (components), you never touch their database directly.


## Domain Catalog

Each domain owns data and enforces invariants.

### library

**Owns:**
- `library_files` - File records, paths, audio metadata
- `library_folders` - Folder cache for quick scanning
- `libraries` - Library definitions, scan state

**Invariants:**
- File paths must be under library root
- File paths unique within library
- Scan progress 0-100%
- Folder mtimes determine staleness

**Components:**
- `add_file_comp.py` - Add file with path validation
- `scan_folder_comp.py` - Discover files in folder
- `validate_path_comp.py` - Check path under root
- `detect_move_comp.py` - Match fingerprints for moves

**Example:**
```python
# Enforce "path must be under root" invariant
def add_file_to_library(db, library_id, file_path):
    library = db.libraries.get(library_id)
    if not is_path_under_root(file_path, library["root_path"]):
        raise ValueError("Path not under library root")
    db.library_files.insert({"path": file_path, "library_id": library_id})
```

---

### metadata

**Owns:**
- `entities` - Artists, albums, genres, labels, years
- `entity_edges` - Song → entity relationships

**Invariants:**
- Entity keys must be normalized (deduplication)
- Edges must reference valid vertices
- Entity types must be valid (artist/album/genre/label/year)

**Components:**
- `normalize_artist_key_comp.py` - Generate normalized artist key
- `normalize_album_key_comp.py` - Generate normalized album key
- `create_entity_vertex_comp.py` - Create entity if not exists
- `create_entity_edge_comp.py` - Link song to entity

**Example:**
```python
# Enforce "keys must be normalized" invariant
def create_entity_vertex(db, entity_type, entity_name):
    key = normalize_key(entity_type, entity_name)  # Normalize!
    if not db.entities.exists(key):
        db.entities.insert({"_key": key, "type": entity_type, "name": entity_name})
```

---

### tagging

**Owns:**
- `tag_queue` - Jobs to write tags to files

**Invariants:**
- Jobs must reference valid files
- Job status must be valid (pending/running/complete/failed)
- Only one job per file at a time

**Components:**
- `enqueue_file_comp.py` - Add file to tag queue
- `dequeue_job_comp.py` - Get next pending job
- `write_tags_comp.py` - Write tags to audio file
- `aggregate_predictions_comp.py` - Aggregate ML outputs

**Example:**
```python
# Enforce "only one job per file" invariant
def enqueue_file_for_tagging(db, file_path, force=False):
    if not force and db.tag_queue.has_pending_job(file_path):
        raise ValueError("Job already queued for file")
    db.tag_queue.insert({"path": file_path, "status": "pending"})
```

---

### ml

**Owns:**
- `embeddings` - Cached audio embeddings
- `predictions` - Cached ML predictions
- `calibration_data` - Calibration parameters per model

**Invariants:**
- Embeddings must match file hash (cache invalidation)
- Predictions must reference valid models
- Calibration must be per-model

**Components:**
- `load_audio_comp.py` - Load and preprocess audio
- `compute_embedding_comp.py` - Generate embedding vector
- `run_inference_comp.py` - Run model inference
- `calibrate_predictions_comp.py` - Apply calibration
- `cache_embedding_comp.py` - Store embedding with hash

**Example:**
```python
# Enforce "embeddings match file hash" invariant
def cache_embedding(db, file_path, embedding, file_hash):
    existing = db.embeddings.get_by_path(file_path)
    if existing and existing["file_hash"] != file_hash:
        db.embeddings.delete(existing["_id"])  # Invalidate stale cache
    db.embeddings.insert({"path": file_path, "embedding": embedding, "file_hash": file_hash})
```

---

### analytics

**Owns:**
- No persistent collections (computes on-demand from other domains)

**Invariants:**
- None (read-only aggregations)

**Components:**
- `compute_tag_statistics_comp.py` - Tag frequency across library
- `compute_cooccurrence_comp.py` - Tag co-occurrence analysis

**Note:** Analytics is read-only, so it doesn't enforce write invariants. It's a domain because it provides a cohesive API for analytical queries.

---


## Platform vs Domain

**Platform is NOT a domain** because it has no owned data.

### Platform Concerns

Infrastructure/platform code provides horizontal services:

**Components in `components/platform/`:**
- `bootstrap_db_comp.py` - Create database schema (doesn't own collections)
- `detect_gpu_comp.py` - GPU hardware detection (no data)
- `monitor_gpu_comp.py` - GPU health monitoring (no data)
- `load_config_comp.py` - Configuration loading (read-only)

**Services in `services/infrastructure/`:**
- `config_service.py` - Config singleton, dependency wiring
- `gpu_service.py` - GPU allocation, health monitoring

**Why not domains:**
- No owned collections
- No invariants to enforce
- Just utilities and infrastructure

**Rule:** If it doesn't own data, it's not a domain. It's platform/infrastructure.

---

## Decision Rules

### Where does this component belong?

**Question 1: Does it write to a specific collection?**
- YES → Component belongs to domain that owns that collection
- NO → Keep reading

**Question 2: Does it enforce invariants for a specific domain?**
- YES → Component belongs to that domain
- NO → Keep reading

**Question 3: Is it a pure utility with no domain knowledge?**
- YES → It's a helper, not a component (`helpers/`)
- NO → Keep reading

**Question 4: Is it infrastructure/bootstrap/monitoring?**
- YES → It's platform (`components/platform/`)
- NO → You probably need to define a new domain

### Examples

**Q:** Where does "normalize artist key" belong?
- Writes to: entities collection
- Enforces: "keys must be normalized" invariant
- **A:** `components/metadata/normalize_artist_key_comp.py`

**Q:** Where does "scan folder for files" belong?
- Writes to: library_files collection
- Enforces: "paths must be under root" invariant
- **A:** `components/library/scan_folder_comp.py`

**Q:** Where does "load audio file" belong?
- Writes to: Nothing (just loads file)
- Enforces: No invariants
- Pure audio processing
- **A:** `components/ml/load_audio_comp.py` (domain-specific utility for ML)

**Q:** Where does "initialize database collections" belong?
- Writes to: Creates schema, doesn't own collections
- Enforces: No domain invariants
- Infrastructure bootstrap
- **A:** `components/platform/bootstrap_db_comp.py`

---

## Migration Strategy

### Current State
Many workflows have:
- Direct persistence imports
- Private helper functions
- Mixed concerns

### Target State
- Only components import persistence
- One function per component file
- Workflows are pure composition

### Migration Steps

**Phase 1: Extract private helpers**

For each workflow with private helpers:
1. Identify each `_private_helper()` function
2. Create `components/domain/helper_name_comp.py`
3. Move logic, add type hints
4. Update workflow to import and call component
5. Run tests

**Phase 2: Remove persistence from workflows**

For each workflow importing `db`:
1. Find each `db.collection.method()` call
2. Create component that wraps the call + invariant enforcement
3. Update workflow to call component
4. Run tests

**Phase 3: Split multi-function components**

For each component with multiple public functions:
1. Split into one file per function
2. Update imports in workflows
3. Run tests

### Example Migration

**Before:**
```python
# workflows/library/scan_library_wf.py
from nomarr.persistence.db import Database

def scan_library(db: Database, library_id: str):
    library = db.libraries.get(library_id)
    files = _discover_files(library["root_path"])
    
    for file_path in files:
        normalized = _normalize_path(file_path, library["root_path"])
        db.library_files.insert({"path": normalized, "library_id": library_id})

def _discover_files(root_path: str) -> list[str]:
    # Logic here
    ...

def _normalize_path(path: str, root: str) -> str:
    # Logic here
    ...
```

**After:**
```python
# components/library/discover_files_comp.py
def discover_files(root_path: str) -> list[str]:
    # Logic here
    ...

# components/library/normalize_path_comp.py
def normalize_path(file_path: str, library_root: str) -> str:
    # Logic here
    ...

# components/library/add_file_comp.py
from nomarr.persistence.db import Database

def add_file_to_library(db: Database, library_id: str, file_path: str):
    # Enforce invariants
    library = db.libraries.get(library_id)
    if not is_path_under_root(file_path, library["root_path"]):
        raise ValueError("Path not under library root")
    
    normalized = normalize_path(file_path, library["root_path"])
    db.library_files.insert({"path": normalized, "library_id": library_id})

# workflows/library/scan_library_wf.py
from nomarr.components.library import (
    discover_files_comp,
    add_file_comp,
)

def scan_library(db: Database, library_id: str):
    library = db.libraries.get(library_id)
    files = discover_files_comp(library["root_path"])
    
    for file_path in files:
        add_file_comp(db, library_id, file_path)
```

---

## Benefits

### Testability
Each component is trivial to test:
```python
def test_normalize_artist_key():
    assert normalize_artist_key("The Beatles") == "the beatles"
    assert normalize_artist_key("  Beatles  ") == "beatles"
```

### Reusability
Components are building blocks:
```python
# Used in scan workflow
artist_key = normalize_artist_key(tags["artist"])

# Used in manual entity creation workflow
artist_key = normalize_artist_key(user_input)

# Used in import workflow
artist_key = normalize_artist_key(imported_data["artist"])
```

### Explicit Dependencies
Call graph shows exact relationships:
```
scan_library_wf
  → discover_files_comp
  → add_file_comp
    → normalize_path_comp (called internally)
    → validate_path_comp (called internally)
```

### Invariant Safety
Impossible to bypass invariants:
- Workflows can't import persistence (enforced by linter)
- Components are the only way to write data
- Components always enforce invariants

---

## Enforcement

### Import Linter Rules

```toml
# .importlinter
[[contracts]]
name = "Only components import persistence"
type = "forbidden"
source_modules = [
    "nomarr.workflows",
    "nomarr.services",
]
forbidden_modules = ["nomarr.persistence"]

[[contracts]]
name = "Workflows can import components"
type = "allowed"
source_modules = ["nomarr.workflows"]
allowed_modules = ["nomarr.components"]
```

### Component Naming Check

```bash
# Each component file must have exactly one public function
python scripts/check_component_functions.py
```

### Code Review Checklist

☐ Does this component import persistence? (Only if it writes data)
☐ Does this component have one public function?
☐ Does this workflow import persistence? (Should be NO)
☐ Are invariants enforced before writing?
☐ Is the component in the correct domain folder?

---

## Summary

**Layers (Horizontal):** Define dependency direction and code type
**Domains (Vertical):** Define data ownership and invariant enforcement

**Critical Rules:**
1. Only components import persistence (invariant enforcement)
2. One function per component (atomic operations)
3. Cross-domain via components only (no direct DB access)

**Result:**
- Clean boundaries
- Testable building blocks
- Explicit dependencies
- Impossible to violate invariants

**Think:** In-process microservices with compile-time enforcement.

---

## Domain Catalog

### Core Domains

Core domains implement primary business capabilities.

#### **library**

**Purpose:** Manage music file libraries - scanning, organization, file metadata extraction.

**Owns:**
- `library_files` collection (file records, paths, metadata)
- `library_folders` collection (folder cache, mtimes)
- `libraries` collection (library definitions, scan state)

**Responsibilities:**
- File system scanning and discovery
- File metadata extraction (tags, duration, bitrate)
- Move detection (via fingerprints)
- Path normalization and validation
- Scan progress tracking
- File CRUD operations

**Components:**
- `file_batch_scanner_comp.py` - Scan folders for files
- `folder_analysis_comp.py` - Analyze folder changes
- `move_detection_comp.py` - Detect moved files
- `metadata_extraction_comp.py` - Extract audio metadata
- `scan_target_validator_comp.py` - Validate scan paths

**Dependencies:**
- `metadata` domain (entity seeding after file discovery)
- `infrastructure` domain (path utilities)

**Example boundary decision:**
- ✅ File scanning → `library`
- ✅ Entity graph seeding after scan → `metadata`
- ✅ Batch entity seeding during scan → `library` (orchestration context)

---

#### **tagging**

**Purpose:** Read and write audio file tags (ID3, Vorbis, MP4).

**Owns:**
- `tag_queue` collection (tagging jobs)
- Tag normalization rules
- Safe write strategies (temp files, backups)

**Responsibilities:**
- Read tags from audio files
- Write tags to audio files safely
- Tag parsing and normalization
- Tag aggregation (multiple sources → consensus)
- Queue management for tagging jobs

**Components:**
- `tagging_reader_comp.py` - Read tags from files
- `tagging_writer_comp.py` - Write tags to files
- `safe_write_comp.py` - Safe write strategies
- `tag_normalization_comp.py` - Normalize tag values
- `tagging_aggregation_comp.py` - Aggregate predictions

**Dependencies:**
- `ml` domain (gets predictions to write)
- `metadata` domain (reads entity cache for tag values)

**Example boundary decision:**
- ✅ Writing tags to files → `tagging`
- ✅ Aggregating ML predictions → `tagging`
- ❌ Computing embeddings → `ml` domain

---

#### **ml**

**Purpose:** Audio analysis via machine learning - embeddings, predictions, calibration.

**Owns:**
- `embeddings` collection (cached embeddings)
- `predictions` collection (cached predictions)
- `calibration_data` collection (calibration parameters)
- Model loading and inference

**Responsibilities:**
- Audio loading and preprocessing
- Embedding computation
- Prediction generation (genre, mood, etc.)
- Model calibration
- Result caching
- GPU/CPU resource management

**Components:**
- `ml_embed_comp.py` - Compute embeddings
- `ml_inference_comp.py` - Run inference
- `ml_audio_comp.py` - Audio preprocessing
- `ml_backend_essentia_comp.py` - Essentia backend (**ONLY** Essentia import)
- `ml_calibration_comp.py` - Calibration logic
- `chromaprint_comp.py` - Audio fingerprinting

**Dependencies:**
- `library` domain (reads file paths)
- `infrastructure` domain (path resolution)

**Special rule:** 
- **ONLY** `ml_backend_essentia_comp.py` may import Essentia libraries
- All other code uses this component as a facade

**Example boundary decision:**
- ✅ Computing embeddings → `ml`
- ✅ Caching predictions → `ml`
- ❌ Writing predictions to file tags → `tagging` domain

---

#### **metadata**

**Purpose:** Entity graph management - artists, albums, genres, labels as vertices with edges to songs.

**Owns:**
- `entities` collection (artists, albums, genres, labels, years)
- `entity_edges` collection (song → entity relationships)
- Entity key generation
- Denormalized cache fields on songs (artist, album, etc.)

**Responsibilities:**
- Entity vertex creation
- Edge creation between songs and entities
- Entity key generation (normalization for deduplication)
- Metadata cache rebuilding (artist, album fields on songs)
- Orphaned entity cleanup

**Components:**
- `entity_seeding_comp.py` - Create entities and edges
- `entity_keys_comp.py` - Generate normalized entity keys
- `metadata_cache_comp.py` - Rebuild denormalized caches
- `entity_cleanup_comp.py` - Remove orphaned entities

**Dependencies:**
- None (leaf domain for core domains)

**Example boundary decision:**
- ✅ Creating artist vertex → `metadata`
- ✅ Linking song to artist → `metadata`
- ❌ Scanning files → `library` domain
- ❌ Reading artist from file tags → `tagging` domain

---

#### **analytics**

**Purpose:** Aggregate analysis of tag data, statistics, co-occurrence.

**Owns:**
- Tag statistics computation
- Co-occurrence analysis
- Aggregate metrics

**Responsibilities:**
- Compute tag frequency statistics
- Analyze tag co-occurrence patterns
- Generate aggregate insights

**Components:**
- `analytics_comp.py` - Tag statistics and co-occurrence

**Dependencies:**
- `metadata` domain (reads entity graph)

**Example boundary decision:**
- ✅ Computing tag statistics → `analytics`
- ❌ Individual song analysis → `ml` domain

---

### Supporting Domains

Supporting domains provide infrastructure for core domains.

#### **infrastructure**

**Purpose:** System-level utilities - paths, configuration, environment.

**Owns:**
- Path resolution logic
- Configuration loading
- Environment variable handling

**Responsibilities:**
- Resolve relative paths to absolute
- Load configuration from files/env
- Validate system prerequisites

**Components:**
- `path_comp.py` - Path resolution utilities
- `config_comp.py` - Configuration management
- `env_comp.py` - Environment validation

**Dependencies:**
- None (leaf domain)

**Example boundary decision:**
- ✅ Resolving relative paths → `infrastructure`
- ❌ Scanning library folders → `library` domain

---

#### **platform**

**Purpose:** System bootstrap, health monitoring, resource detection.

**Owns:**
- Database initialization
- First-run setup
- GPU detection and monitoring
- System health checks

**Responsibilities:**
- Initialize ArangoDB collections/graphs
- Detect available GPUs
- Monitor GPU health
- System readiness checks

**Components:**
- `arango_bootstrap_comp.py` - Database initialization
- `arango_first_run_comp.py` - First-run setup
- `gpu_probe_comp.py` - GPU detection
- `gpu_monitor_comp.py` - GPU health monitoring

**Dependencies:**
- `infrastructure` domain (config, paths)

**Example boundary decision:**
- ✅ Creating database collections → `platform`
- ✅ Detecting GPUs → `platform`
- ❌ Running ML inference → `ml` domain

---

#### **workers**

**Purpose:** Background job execution infrastructure.

**Owns:**
- Worker lifecycle management
- Job recovery after crashes
- Crash detection and handling

**Responsibilities:**
- Spawn and monitor worker processes
- Detect crashed workers
- Recover or requeue jobs after crashes
- Graceful shutdown

**Components:**
- `job_recovery_comp.py` - Recover jobs after crashes
- `worker_crash_comp.py` - Crash detection logic

**Dependencies:**
- `tagging` domain (operates on tag queue)

**Example boundary decision:**
- ✅ Detecting crashed worker → `workers`
- ✅ Recovering jobs → `workers`
- ❌ Processing a tagging job → `tagging` domain

---

### Integration Domains

Integration domains bridge Nomarr with external systems.

#### **navidrome**

**Purpose:** Integration with Navidrome music server.

**Owns:**
- Navidrome configuration templates
- Navidrome-specific export logic

**Responsibilities:**
- Generate Navidrome config files
- Format data for Navidrome consumption

**Components:**
- `templates_comp.py` - Template rendering

**Dependencies:**
- `library` domain (exports library data)

**Example boundary decision:**
- ✅ Generating Navidrome config → `navidrome`
- ❌ Scanning music files → `library` domain

---

## Decision Rules

Use these rules to determine domain placement:

### Rule 1: Data Ownership

**Question:** Which domain owns the primary data?

**Example:**
- "Where do I seed entities after scanning files?"
- Primary data: `library_files` (owned by `library`)
- But operation: creates entity vertices (owned by `metadata`)
- **Decision:** Call `metadata` component from `library` workflow

### Rule 2: Responsibility Boundary

**Question:** What is the operation's primary purpose?

**Example:**
- "Batch entity seeding during scan"
- Purpose: Complete the scan operation (library concern)
- Implementation: Calls metadata components
- **Decision:** Component in `library` domain (orchestration context)

### Rule 3: Reusability

**Question:** Could another domain need this exact operation?

**If YES:** Extract to the domain that owns the operation logic.
**If NO:** Keep it in the workflow/component calling it.

**Example:**
- "Apply file moves and re-seed entities"
- Only library scans do this exact combination
- **Decision:** Component in `library` domain

### Rule 4: Test Isolation

**Question:** Can this be tested without mocking other domains?

**If YES:** It's likely in the right domain.
**If NO:** It might be in the wrong domain or poorly factored.

---

## Cross-Domain Patterns

### Pattern 1: Orchestration in Caller Domain

When orchestrating multiple domains, the orchestration lives in the **calling domain**:

```python
# library/seed_entities_batch_comp.py
def seed_entities_for_scanned_files(db, file_paths, metadata_map):
    """Orchestrate entity seeding for library scan context."""
    for file_path in file_paths:
        file_id = db.library_files.get_library_file(file_path)["_id"]
        
        # Call metadata domain
        entity_tags = extract_entity_tags(metadata_map[file_path])
        seed_song_entities_from_tags(db, file_id, entity_tags)
        rebuild_song_metadata_cache(db, file_id)
```

**Why:** The library domain knows the scan context and error handling needs.

---

### Pattern 2: DTOs for Cross-Domain Data

Never pass raw database records across domains:

```python
# ✅ GOOD - Via DTO
from nomarr.helpers.dto import FileRecord

file_dto = FileRecord(path=path, duration=duration, bitrate=bitrate)
process_file(file_dto)

# ❌ BAD - Raw database record
file_doc = db.library_files.get(path)  # Has _id, _key, internal fields
process_file(file_doc)  # Leaks database structure
```

---

### Pattern 3: Single Responsibility Per Component

Each component should have **one clear job**:

```python
# ✅ GOOD - Single responsibility
def seed_song_entities_from_tags(db, file_id, entity_tags):
    """Create entity vertices and edges for a song."""
    ...

def rebuild_song_metadata_cache(db, file_id):
    """Rebuild denormalized cache fields from edges."""
    ...

# ❌ BAD - Multiple responsibilities
def seed_and_rebuild_everything(db, file_id, entity_tags):
    """Seed entities, rebuild cache, validate, log, send events..."""
    ...
```

---

## Enforcement

### Import Linter Rules

Add domain-specific rules to `.importlinter`:

```toml
[[contracts]]
name = "Library domain can call metadata domain"
type = "allowed"
source_modules = ["nomarr.components.library"]
forbidden_modules = ["nomarr.components.tagging", "nomarr.components.ml"]

[[contracts]]
name = "Metadata domain is a leaf"
type = "independence"
modules = ["nomarr.components.metadata"]
```

### Naming Checker

Components must live in the domain directory:

```python
# ✅ GOOD
nomarr/components/library/seed_entities_batch_comp.py

# ❌ BAD - Wrong domain
nomarr/components/metadata/seed_entities_batch_comp.py
```

### Code Review Checklist

When reviewing domain placement:

1. ☐ Does this domain own the primary data?
2. ☐ Is the responsibility boundary clear?
3. ☐ Could this be reused by other domains?
4. ☐ Can it be tested without mocking other domains?
5. ☐ Does it follow cross-domain patterns (DTOs, orchestration)?

---

## Migration Guide

### Identifying Misplaced Code

**Symptoms of wrong domain:**
1. Component imports from unexpected domains
2. Unclear responsibility when reading code
3. Difficult to test without heavy mocking
4. Duplicated logic across domains

**Example:**
```python
# In metadata domain, but calls library-specific logic
def seed_entities_during_scan(db, file_paths):
    # Gets file IDs from library_files table
    # Calls library-specific error handling
    # This should be in library domain!
```

### Refactoring Steps

1. **Identify true owner** - Which domain owns the data/operation?
2. **Extract to component** - Create component in correct domain
3. **Update imports** - Change callers to use new component
4. **Update tests** - Move tests to correct domain test file
5. **Delete old code** - Remove from wrong domain

---

## Examples

### Example 1: Batch Entity Seeding

**Question:** Where does batch entity seeding during library scan belong?

**Analysis:**
- **Data:** `library_files` (library domain) and `entities` (metadata domain)
- **Purpose:** Complete library scan operation
- **Context:** Scan-specific orchestration (per-folder progress, error handling)
- **Reusability:** Specific to scan workflow, not general-purpose

**Decision:** `nomarr/components/library/seed_entities_batch_comp.py`

**Reasoning:** The orchestration context is library-specific, even though it calls metadata domain components.

---

### Example 2: Tag Aggregation

**Question:** Where does ML prediction aggregation belong?

**Analysis:**
- **Data:** Predictions from ML models
- **Purpose:** Prepare tags for writing to files
- **Context:** Tagging workflow needs aggregated results
- **Reusability:** Only tagging workflows aggregate predictions

**Decision:** `nomarr/components/tagging/tagging_aggregation_comp.py`

**Reasoning:** Aggregation is part of preparing tags for file writing (tagging domain responsibility).

---

### Example 3: Chromaprint Fingerprinting

**Question:** Where does audio fingerprinting belong?

**Analysis:**
- **Data:** Audio file data
- **Purpose:** Generate fingerprint for move detection
- **Context:** Used by library (move detection) and ML (duplicate detection)
- **Reusability:** Multiple domains need this

**Decision:** `nomarr/components/ml/chromaprint_comp.py`

**Reasoning:** Audio analysis is ML domain responsibility. Library domain calls it as needed.

---

## Summary

**Key Takeaways:**

1. **Domains are bounded contexts** - Clear responsibilities, minimal coupling
2. **Data ownership determines domain** - Who owns the primary data?
3. **Orchestration lives in caller domain** - Context-specific coordination
4. **Cross-domain via DTOs** - Never raw database records
5. **Single responsibility per component** - One clear job, easy to test

**When in doubt:**
- Ask: "What's the primary purpose?"
- Check: "Who owns the data?"
- Test: "Can I test this without heavy mocking?"

**Result:** Clean boundaries, testable code, clear responsibilities.
