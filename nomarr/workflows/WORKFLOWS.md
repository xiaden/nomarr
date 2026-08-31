# Workflows Layer

The **workflows layer** implements use cases — the "stories" of what Nomarr does. Each workflow is a clear sequence of component calls that accepts dependencies as parameters, orchestrates components to perform work, and returns a DTO.

They are:

- **Use case implementations** (scan a library, generate calibration, process a file)
- **Recipes** composed of component calls
- **Dependency-injected** (receive DB, config, backends as parameters)

> **⚠️ Persistence Rule:** Workflows may call the injected public `Database` intent facade (`db.library`, `db.app`, `db.ml`) for **thin, single-atomic-intent operations** — one facade method per call. They must not sequence lower-level calls, implement business rules or state-machine transitions, manage collection-level writes, or perform multi-call persistence choreography; that belongs in a component or an intent-complete facade method. Workflows import `Database` from `nomarr.persistence.db` and never touch persistence implementation internals.

> **Rule:** Control flow composition lives here. Heavy logic lives in components. Wiring lives in services.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Workflows sit **between services and components**. Services call workflows; workflows call components and other workflows. Lateral (same-layer) imports are allowed — workflows may call other workflows.

---

## 2. Directory Structure

```text
workflows/
├── calibration/
│   ├── apply_calibration_wf.py            # Apply calibration to tags
│   ├── calibration_loader_wf.py           # Load calibration data
│   ├── export_calibration_bundle_wf.py    # Export calibration bundle
│   ├── generate_calibration_wf.py         # Generate calibration thresholds
│   ├── import_calibration_bundle_wf.py    # Import calibration bundle
│   └── write_calibrated_tags_wf.py        # Write calibrated tags to files
│
├── library/
│   ├── cleanup_orphaned_tags_wf.py        # Remove orphan tags
│   ├── file_tags_io_wf.py                 # File tag I/O operations
│   ├── reconcile_paths_wf.py              # Reconcile file paths
│   ├── scan_library_full_wf.py            # Full library scan
│   ├── scan_library_quick_wf.py           # Quick library scan
│   ├── scan_setup_wf.py                   # Scan initialization/setup
│   ├── sync_file_to_library_wf.py         # Sync single file to library
│   └── validate_library_tags_wf.py        # Validate library tag state
│
├── metadata/
│   ├── cleanup_orphaned_entities_wf.py    # Clean up orphaned entities
│   └── rebuild_metadata_cache_wf.py       # Rebuild metadata cache
│
├── navidrome/
│   ├── filter_engine_wf.py                # Smart playlist filter engine
│   ├── find_similar_tracks_wf.py          # Find similar tracks by vector
│   ├── generate_navidrome_config_wf.py    # Generate Navidrome config
│   ├── generate_playlists_wf.py           # Batch playlist generation
│   ├── generate_smart_playlist_wf.py      # Generate smart playlist
│   ├── generate_static_playlist_wf.py     # Generate static playlist
│   ├── parse_smart_playlist_query_wf.py   # Parse playlist query syntax
│   ├── preview_smart_playlist_wf.py       # Preview playlist results
│   └── preview_tag_stats_wf.py            # Preview tag statistics
│
├── platform/
│   ├── idle_promotion_vectors_wf.py       # Idle vector promotion
│   ├── prepare_database_wf.py             # Database preparation
│   ├── promote_and_rebuild_vectors_wf.py  # Promote vectors and rebuild index
│   ├── rebuild_vector_index_wf.py         # Rebuild vector search index
│   └── register_ml_models_wf.py           # Register ML models in DB
│
├── playlist_import/
│   └── convert_playlist_wf.py             # Convert imported playlist
│
├── processing/
│   ├── process_file_wf.py                 # Process single file (ML + tags)
│   └── write_file_tags_wf.py              # Write tags to file
│
└── vectors/
    └── get_track_vector_wf.py             # Retrieve track vector embedding
```

**Naming rules:**

- Modules: `verb_object_wf.py` (e.g., `scan_library_full_wf.py`, `process_file_wf.py`)
- Primary entrypoint: `verb_object_workflow(...)` — one public function per file
- Private helpers: `_prefix` (e.g., `_validate_paths`, `_collect_results`)

---

## 3. Workflow Anatomy

Workflows read like a **recipe** — clear sequences of component calls:

```python
def process_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str,
) -> ProcessFileResult:
    # Step 1: Load file from DB
    file_record = load_file_from_db(db, file_path)
    
    # Step 2: Compute embeddings
    embeddings = compute_all_embeddings(file_path, models_dir)
    
    # Step 3: Run inference
    predictions = run_inference_for_heads(embeddings, models_dir)
    
    # Step 4: Convert to tags
    tags = predictions_to_tags(predictions, namespace)
    
    # Step 5: Write tags via component (component calls persistence)
    write_tags_to_library(db, file_record.id, tags)
    
    return ProcessFileResult(file=file_path, tags_written=len(tags))
```

**Key pattern:** The workflow passes `db` to components for heavy or multi-step work, and may make thin single-atomic-intent facade calls directly when a step is one atomic intent.

---

## 4. Complexity Guidelines

### Size Limits

- Soft limit: ~300–400 LOC per workflow module
- One public workflow per file
- Exception: analytics-style modules may group related read-only workflows

### When to Extract

**Extract to a component if:**

- The workflow does non-trivial computation itself
- Complex branching is embedded in the workflow
- The logic is reusable across workflows

**Split into smaller workflows if:**

- The workflow exceeds the size limit
- It has large, reusable sub-sequences
- Multiple user stories live in one file

---

## 5. Boundaries & Import Rules

**Allowed:**

- ✅ Components (`nomarr.components.*`)
- ✅ Other workflows (`nomarr.workflows.*`) — lateral imports
- ✅ Helpers (`nomarr.helpers.*`)
- ✅ Public persistence facade (`from nomarr.persistence.db import Database`) — for thin single-intent calls (`db.library`/`db.app`/`db.ml`) and DI pass-through
- ✅ Standard library, numpy, etc.

**Forbidden:**

- ❌ Services (`nomarr.services.*`)
- ❌ Interfaces (`nomarr.interfaces.*`)
- ❌ `nomarr.app`
- ❌ Pydantic models
- ❌ Importing persistence implementation internals (`nomarr.persistence.database`/`api`/`sql`/`mappers`/`models`)
- ❌ Sequencing multiple facade calls to reconstruct a multi-step persistence intent

---

## 6. Patterns

### Accept All Dependencies as Parameters

```python
# ✅ Good — dependencies injected
def scan_library_workflow(
    db: Database,
    library: Library,
    models_dir: str,
) -> ScanResult: ...


# ❌ Bad — reading config at runtime
def scan_library_workflow(library: Library) -> ScanResult:
    from nomarr.config import db  # ← No globals
```

Callers resolve a library's natural name to a domain `Library` value before invoking a workflow.

### Return DTOs

Workflows always return typed DTOs from `helpers/dto/`:

```python
# ✅ Good
def process_file_workflow(...) -> ProcessFileResult:
    return ProcessFileResult(file=file_path, tags_written=len(tags))

# ❌ Bad — returning dict
def process_file_workflow(...) -> dict[str, Any]:
    return {"file": file_path, "tags_written": len(tags)}
```

### Database Pass-Through

Workflows receive `Database` and pass it to components for heavy or multi-step work; they may also make thin, single-atomic-intent facade calls directly:

```python
# ✅ Good — pass db to component for multi-step work
#    (a single thin facade call is also fine, e.g. db.library.list_tags(limit=100))
def cleanup_workflow(db: Database, library: Library) -> CleanupResult:
    orphans = find_orphaned_tags(db, library)  # component calls db
    removed = remove_tags(db, orphans)  # component calls db
    return CleanupResult(removed=removed)


# ❌ Bad — workflow reconstructing a multi-step intent (choreography)
def cleanup_workflow(db: Database, library: Library) -> CleanupResult:
    song_ids = db.library.list_library_song_ids(library, limit=None)
    removed = 0
    for song_id in song_ids:
        identity = db.library.resolve_song_identity(song_id)
        removed += len(db.library.list_tags_for_song(identity))  # sequencing facade calls in a loop
    return CleanupResult(removed=removed)  # belongs in a component
```

---

## 7. Anti-Patterns

 | Anti-Pattern | Why It's Wrong | Fix |
 | --- | --- | --- |
 | Complex computation in workflow | Logic belongs in components | Extract to component |
 | Sequencing multiple `db.library.*`/`db.app.*`/`db.ml.*` calls to rebuild an intent | Thin single-intent facade calls are allowed, but choreography belongs in a component | Extract the multi-call intent to a component |
 | Importing services | Violates layer direction | Services call workflows, not reverse |
 | Importing Pydantic models | Interface concern only | Use DTOs from `helpers/dto/` |
 | Returning raw dicts | Untyped, fragile contract | Return a DTO |
 | Reading env vars / global config | Hidden dependency | Accept config as parameter |
