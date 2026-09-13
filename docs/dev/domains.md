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

The domain owns specific PostgreSQL tables.

### 2. Invariants

Rules that MUST stay true about that data.

### 3. Public API

**Components** that enforce invariants when reading/writing data.

### 4. Private Implementation

Direct persistence access is **private** to the domain. Other domains CANNOT call `db.library` directly — they MUST call library domain components.

**Metaphor:** Domains are like in-process microservices. You call their API (components), you never touch their database directly.

---

## Critical Rules

### Rule 1: Components Enforce Invariants

**Only components may import from persistence.**

```python
# ✅ GOOD — Component imports persistence
# components/library/library_song_mutation_comp.py
from nomarr.helpers.dataclasses.library_dataclass import Library
from nomarr.helpers.dataclasses.song_command_dataclass import SongIdentity
from nomarr.helpers.dto import LibraryPath
from nomarr.persistence.db import Database


def upsert_library_song(
    db: Database,
    path: LibraryPath,
    library: Library,
    file_size: int,
    modified_time: int,
) -> SongIdentity:
    # The component validates the path and composes a typed command; persistence
    # resolves (library_uuid, normalized_path) and returns the locator.
    command = ...  # SongUpsertInput(library=LibraryIdentity(...), path=..., scan=...)
    return db.library.add_song_to_library(command)


# ✅ GOOD — Workflow calls component
# workflows/library/scan_library_full_wf.py
from nomarr.components.library import upsert_library_song


def scan_library(db, library: Library):
    for path in discovered:
        locator: SongIdentity = upsert_library_song(db, path, library, file_size, modified_time)


# ❌ BAD — Workflow bypasses the typed scan owner
 db.library.add_songs_to_library_batch(...)  # Use the scan/reconciliation workflow owner instead
```

### Rule 2: Cross-Domain via Components Only

**To write to another domain's data, call its components.**

```python
# ✅ GOOD — Library workflow calls metadata domain component
from nomarr.components.metadata.entity_seeding_comp import build_song_tag_assignments


def scan_song_workflow(db, song: SongIdentity, tags):
    assignments = build_song_tag_assignments(tags)  # Metadata domain (compute-only)
    db.library.replace_song_tags(song, assignments)  # Library domain persistence


# ❌ BAD — Library workflow bypasses metadata domain
db.entities.insert({"id": artist_id})  # No invariant enforcement!
```

---

## Domain Catalog

Each domain maps to a subfolder under `components/` and owns specific PostgreSQL tables.

### library

**Components:** `components/library/`

**Owns:**

- `libraries` — Library definitions, root paths
- `songs` — File records, paths, audio metadata, tagging state
- `library_folders` — Folder cache for quick scanning
- `song_states` / `song_state_assignments` — Song lifecycle state lookup and per-song state assignments (e.g., `ml_tagged`)

**Invariants:**

- File paths must be under library root
- File paths unique within a library
- Scan progress 0–100%
- Folder mtimes determine staleness

**Key components:**

- `library_song_mutation_comp.py` — Add/update songs with path validation, returning the ``SongIdentity`` locator
- `file_batch_scanner_comp.py` — Batch file discovery
- `scan_lifecycle_comp.py` — Scan state management
- `move_detection_comp.py` — Match chromaprints for moved files
- `reconcile_paths_comp.py` — Path reconciliation with claim locking
- `search_files_comp.py` — Library search queries

---

### metadata

**Components:** `components/metadata/`

**Owns:**

- Pure, compute-only helpers that derive entity tag assignments and metadata
  cache-field mappings from already-parsed file metadata. No table is owned by
  this domain; persistence of the derived assignments belongs to the
  `library`/`tagging` domains (`db.library.replace_song_tags`).

**Invariants:**

- Entity keys must be normalized (deduplication)
- These helpers perform no database reads or writes

**Key components:**

- `entity_seeding_comp.py` — Compute entity tag assignments from tags (pure; no DB writes — `build_song_tag_assignments`, `extract_entity_tag_mapping`)
- `metadata_cache_comp.py` — Compute metadata cache-field mappings from raw metadata (pure; ADR-045 removed the cache writer, so no cache writer remains)

---

### tagging

**Components:** `components/tagging/`

**Owns:**

- `tags` — Identity-only rows (`id`, `namespace`, `name`, `value`); no assignment metadata or integer application identity
- `song_tags` — Edge-owned song/tag assignments and their `confidence`, `source`, and `created_at` metadata
- `song_mood_calibration_markers` — Private additive current marker owned by `LibraryTagsDb`; it is publication metadata, not a synthetic tag or history/registry
- `LibraryTagsDb` — Exact `SongIdentity`-only mood owner and same-transaction assignment/marker boundary; broader historical examples and residual documentation are deferred to O


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
- `ml_output_streams` — ML output streaming status per song/model
- `ml_embedding_streams` — Embedding computation progress per song/backbone
- `embeddings` — Vector embeddings (single table, addressed by `backbone_id`)
- `calibration_states` — Current calibration parameters per model
- `calibration_history` — Historical calibration records
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

- No persistent tables (computes on-demand from other domains)

**Key components:**

- `analytics_comp.py` — Tag frequency statistics
- `collection_overview_comp.py` — Library-wide collection metrics
- `mood_analysis_comp.py` — Mood-based analysis

**Note:** Analytics is read-only. It's a domain because it provides a cohesive API for analytical queries.

---

### navidrome

**Components:** `components/navidrome/`

**Owns:**

- No persistent tables. Nomarr never stores Navidrome tracks, song↔Navidrome-ID mappings, or playcounts. Navidrome play data arrives through the plugin/request boundary (e.g. the personal-playlists request's `top_plays`) and is used transiently for taste-profile computation.

**Invariants:**

- Play data is never persisted locally; song↔Navidrome-ID resolution is owned by the Navidrome plugin, not the database

**Key components:**

- `subsonic_client_comp.py` — Subsonic API client
- `descriptor_match_comp.py` — Build and resolve portable track descriptors
- `playlist_builder_comp.py` — Build playlists from tag queries
- `m3u_comp.py` — M3U file generation
- `templates_comp.py` — Playlist template management
- `taste_profile_comp.py` — User taste profile computation
- `tag_query_comp.py` — Tag-based track queries

---

### workers

**Components:** `components/workers/`

**Owns:**

- `worker_claims` — Ephemeral worker claims (work leases)
- `worker_restart_policy` — Per-worker restart policy tracking

**Invariants:**

- Single active claim per song across typed and untyped (persistence-internal unique claim key)
- Claims are ephemeral (represent active work, not scheduled work)

**Key components:**

- `worker_discovery_comp.py` — Find next file needing processing
- `worker_crash_comp.py` — Crash recovery and claim cleanup

**Note:** Worker *process management* lives in `services/infrastructure/` (`WorkerSystemService`, `DiscoveryWorker`). Components handle only domain logic (discovery, claims, crash recovery).

---

### platform

**Components:** `components/platform/`

**Owns:**

- App bookkeeping & operational state (schema version, worker_enabled flag, VRAM limits, capacity estimates, GPU snapshots) — exposed through the semantic `db.app` intents
- `health` — Health status snapshots (history-only, written by `HealthMonitorService`)
- `sessions` — API session data
- `applied_migrations` — Migration tracking

**Key components:**

- `db_bootstrap_comp.py` — Database schema creation
- `db_first_run_comp.py` — First-run provisioning
- `migration_runner_comp.py` — Migration execution
- `gpu_probe_comp.py` — GPU hardware detection
- `gpu_monitor_comp.py` — GPU health monitoring
- `resource_monitor_comp.py` — System resource monitoring

**Note:** Platform is infrastructure, not a traditional domain. It has no business invariants but does own system-level tables.

---

### playlist_import

**Components:** `components/playlist_import/`

**Owns:**

- No persistent tables (processes external playlists into library references)

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

- No tag persistence ownership; mood-tag replacement is owned by `LibraryTagsDb.replace_mood_tags*`
- No persistent tables (coordinates file writing)

**Key components:**

- `file_write_comp.py` — Safe file write operations

---

### infrastructure

**Components:** `components/infrastructure/`

**Owns:**

- No persistent tables

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

**Q1: Does it write to a specific table?**
→ Component belongs to the domain that owns that table.

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
 | Where does "discover next file to process" belong? | `components/workers/worker_discovery_comp.py` — queries songs |
 | Where does "load audio file" belong? | `components/ml/audio/ml_audio_comp.py` — ML domain audio I/O |
 | Where does "bootstrap database" belong? | `components/platform/db_bootstrap_comp.py` — infrastructure |
 | Where does "match Spotify tracks" belong? | `components/playlist_import/track_matcher_comp.py` — playlist_import domain |

---

## Enforcement

### Import Linter

`import-linter` enforces that only components import persistence. Workflows and services cannot bypass domain boundaries.

### Code Review Checklist

- ☐ Does this component import persistence? (Only if it owns that table)
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
