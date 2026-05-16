# Domain Architecture

**Audience:** Developers making "where does this code belong?" decisions.

Nomarr's architecture has TWO orthogonal organizing principles:

## Layers (Horizontal)

```
interfaces  ← Transport (HTTP, CLI)
services    ← Wiring, DI
workflows   ← Orchestration
components  ← Atomic operations, domain logic
persistence ← Database access
helpers     ← Pure utilities
```

Layers define **dependency direction** and **what kind of code**. See [Architecture Overview](architecture.md).

## Domains (Vertical)

```
library | tagging | ml | metadata | analytics | navidrome | ...
 | | | | | | 
   v        v       v       v           v           v
[Data Ownership + Invariants + Public API]
```

Domains define **data ownership** and **invariant enforcement**.

---

## What is a Domain?

A domain is a **vertical slice** through the layers that encapsulates:

### 1. Data Ownership

The domain owns specific ArangoDB collections.

### 2. Invariants

Rules that MUST stay true about that data.

### 3. Public API

**Components** that enforce invariants when reading/writing data.

### 4. Private Implementation

Direct persistence access is **private** to the domain. Other domains CANNOT call `db.library_files` directly — they MUST call library domain components.

**Metaphor:** Domains are like in-process microservices. You call their API (components), you never touch their database directly.

---

## Critical Rules

### Rule 1: Components Enforce Invariants

**Only components may import from persistence.**

```python
# ✅ GOOD — Component imports persistence
# components/library/file_library_comp.py
from nomarr.persistence.db import Database

def add_file(db: Database, library_id: str, file_path: str) -> dict:
    library = db.libraries.get(library_id)
    if not is_under_root(file_path, library["root_path"]):
        raise ValueError("Path not under library root")
    return db.library_files.insert({"path": file_path, ...})

# ✅ GOOD — Workflow calls component
# workflows/library/scan_library_full_wf.py
from nomarr.components.library.file_library_comp import add_file

def scan_library(db, library_id):
    for path in discovered:
        add_file(db, library_id, path)

# ❌ BAD — Workflow imports persistence
db.library_files.insert(...)  # BYPASSES INVARIANTS!
```

### Rule 2: Cross-Domain via Components Only

**To write to another domain's data, call its components.**

```python
# ✅ GOOD — Library workflow calls metadata domain component
from nomarr.components.metadata.entity_seeding_comp import seed_entities

def scan_file_workflow(db, file_doc, tags):
    add_file(db, library_id, file_doc["path"])      # Library domain
    seed_entities(db, file_doc["_id"], tags)          # Metadata domain

# ❌ BAD — Library workflow bypasses metadata domain
db.entities.insert({"_key": artist_key})  # No invariant enforcement!
```

---

## Domain Catalog

Each domain maps to a subfolder under `components/` and owns specific ArangoDB collections.

### library

**Components:** `components/library/`

**Owns:**

- `libraries` — Library definitions, root paths
- `library_files` — File records, paths, audio metadata, tagging state
- `library_folders` — Folder cache for quick scanning
- `file_states` — Edge collection for file lifecycle state (e.g., `ml_tagged`)

**Invariants:**

- File paths must be under library root
- File paths unique within a library
- Scan progress 0–100%
- Folder mtimes determine staleness

**Key components:**

- `file_library_comp.py` — Add/update files with path validation
- `file_batch_scanner_comp.py` — Batch file discovery
- `scan_lifecycle_comp.py` — Scan state management
- `move_detection_comp.py` — Match chromaprints for moved files
- `reconcile_paths_comp.py` — Path reconciliation with claim locking
- `search_files_comp.py` — Library search queries

---

### metadata

**Components:** `components/metadata/`

**Owns:**

- Entity data seeded from file tags (artists, albums, genres)

**Invariants:**

- Entity keys must be normalized (deduplication)
- Edges must reference valid vertices

**Key components:**

- `entity_seeding_comp.py` — Create entity vertices and edges from tags
- `entity_cleanup_comp.py` — Remove orphaned entities
- `metadata_cache_comp.py` — Metadata cache management

---

### tagging

**Components:** `components/tagging/`

**Owns:**

- `tags` — Edge collection linking files to tag labels with scores


**Invariants:**

- Tags must reference valid files and valid model outputs
- Tag scores are normalized floats

**Key components:**

- `tagging_writer_comp.py` — Write tags to audio files
- `tagging_reader_comp.py` — Read tags from audio files
- `tagging_aggregation_comp.py` — Aggregate ML predictions into tags
- `tag_normalization_comp.py` — Normalize tag labels
- `tag_parsing_comp.py` — Parse tag strings
- `tagging_remove_comp.py` — Remove tags from files
- `tagging_reconstruction_comp.py` — Reconstruct tags from model outputs

---

### ml

**Components:** `components/ml/`

**Owns:**

- `ml_models` — Registered model definitions (backbone + heads)
- `ml_model_outputs` — Raw model output storage
- `calibration_state` — Current calibration parameters per model
- `calibration_history` — Historical calibration records
- `segment_scores_stats` — Per-file segment score statistics
- `ml_capacity` — GPU/CPU capacity probe results
- `vram_promises` — VRAM allocation tracking

**Subpackages:**

- `audio/` — Audio loading (`ml_audio_comp.py` via Essentia MonoLoader), chromaprint, mel preprocessing
- `calibration/` — Per-label calibration computation and state
- `inference/` — Backbone embedding, head pipeline, segment stats
- `onnx/` — ONNX Runtime session management, model discovery, caching
- `resources/` — VRAM coordination, capacity probing, tier selection, timing
- `vectors/` — Vector persistence, retrieval, idle promotion, maintenance

**Invariants:**

- Models must be discoverable ONNX files in the models directory
- Sessions are managed with VRAM-aware eviction
- Calibration is per-model and per-label

---

### analytics

**Components:** `components/analytics/`

**Owns:**

- No persistent collections (computes on-demand from other domains)

**Key components:**

- `analytics_comp.py` — Tag frequency statistics
- `collection_overview_comp.py` — Library-wide collection metrics
- `mood_analysis_comp.py` — Mood-based analysis

**Note:** Analytics is read-only. It's a domain because it provides a cohesive API for analytical queries.

---

### navidrome

**Components:** `components/navidrome/`

**Owns:**

- `navidrome_tracks` — Track mapping between Nomarr and Navidrome
- `navidrome_playcounts` — Playcount/scrobble data from Navidrome

**Invariants:**

- Track mappings must reference valid library files
- Playcounts are append-only

**Key components:**

- `subsonic_client_comp.py` — Subsonic API client
- `subsonic_crawl_comp.py` — Crawl Navidrome library
- `playlist_builder_comp.py` — Build playlists from tag queries
- `m3u_comp.py` — M3U file generation
- `templates_comp.py` — Playlist template management
- `taste_profile_comp.py` — User taste profile computation
- `tag_query_comp.py` — Tag-based track queries

---

### workers

**Components:** `components/workers/`

**Owns:**

- `worker_claims` — Ephemeral claim documents (work leases)
- `worker_restart_policy` — Per-worker restart policy tracking

**Invariants:**

- Claims use deterministic `_key` based on file `_key` (one claim per file)
- Claims are ephemeral (represent active work, not scheduled work)

**Key components:**

- `worker_discovery_comp.py` — Find next file needing processing
- `worker_crash_comp.py` — Crash recovery and claim cleanup

**Note:** Worker *process management* lives in `services/infrastructure/` (`WorkerSystemService`, `DiscoveryWorker`). Components handle only domain logic (discovery, claims, crash recovery).

---

### platform

**Components:** `components/platform/`

**Owns:**

- `meta` — Key-value store for system metadata (schema version, worker_enabled flag, etc.)
- `health` — Health status snapshots (history-only, written by `HealthMonitorService`)
- `sessions` — API session data
- `applied_migrations` — Migration tracking

**Key components:**

- `arango_bootstrap_comp.py` — Database schema creation
- `arango_first_run_comp.py` — First-run provisioning
- `migration_runner_comp.py` — Migration execution
- `gpu_probe_comp.py` — GPU hardware detection
- `gpu_monitor_comp.py` — GPU health monitoring
- `resource_monitor_comp.py` — System resource monitoring

**Note:** Platform is infrastructure, not a traditional domain. It has no business invariants but does own system-level collections.

---

### playlist_import

**Components:** `components/playlist_import/`

**Owns:**

- No persistent collections (processes external playlists into library references)

**Key components:**

- `spotify_fetcher_comp.py` — Fetch playlist data from Spotify
- `deezer_fetcher_comp.py` — Fetch playlist data from Deezer
- `track_matcher_comp.py` — Match external tracks to library files
- `url_parser_comp.py` — Parse playlist URLs
- `metadata_normalizer_comp.py` — Normalize external metadata

---

### processing

**Components:** `components/processing/`

**Owns:**

- No persistent collections (coordinates file writing)

**Key components:**

- `file_write_comp.py` — Safe file write operations

---

### infrastructure

**Components:** `components/infrastructure/`

**Owns:**

- No persistent collections

**Key components:**

- `health_comp.py` — Health status helpers
- `path_comp.py` — Path resolution utilities

**Related infrastructure services:**

- `HealthMonitorService` — Reads worker health and pipeline frames from OS pipes
- `WorkerSystemService` — Owns worker process lifecycle and health callback wiring
- `LibraryPipelineService` — Coordinates startup recovery, calibration triggers, apply callbacks, and file-write transitions for the per-library automation pipeline

---

## Decision Rules

### Where does this component belong?

**Q1: Does it write to a specific collection?**
→ Component belongs to the domain that owns that collection.

**Q2: Does it enforce invariants for a specific domain?**
→ Component belongs to that domain.

**Q3: Is it a pure utility with no domain knowledge?**
→ It's a helper (`helpers/`), not a component.

**Q4: Is it infrastructure/bootstrap/monitoring?**
→ It's platform (`components/platform/`).

### Quick Examples

 | Question | Answer |
 | ---------- | -------- |
 | Where does "normalize tag label" belong? | `components/tagging/tag_normalization_comp.py` — enforces tagging invariants |
 | Where does "discover next file to process" belong? | `components/workers/worker_discovery_comp.py` — queries library_files |
 | Where does "load audio file" belong? | `components/ml/audio/ml_audio_comp.py` — ML domain audio I/O |
 | Where does "bootstrap database" belong? | `components/platform/arango_bootstrap_comp.py` — infrastructure |
 | Where does "match Spotify tracks" belong? | `components/playlist_import/track_matcher_comp.py` — playlist_import domain |

---

## Enforcement

### Import Linter

`import-linter` enforces that only components import persistence. Workflows and services cannot bypass domain boundaries.

### Code Review Checklist

- ☐ Does this component import persistence? (Only if it owns that collection)
- ☐ Does this workflow import persistence? (Should be NO)
- ☐ Are invariants enforced before writing?
- ☐ Is the component in the correct domain folder?
- ☐ Cross-domain access goes through the target domain's components?

---

## Related Documentation

- [Architecture Overview](architecture.md) — Layer structure and dependency rules
- [Health System](health.md) — Health monitoring domain
- [Workers & Lifecycle](workers.md) — Worker domain and claim-based processing
- [Migrations](migrations.md) — Database migration system
