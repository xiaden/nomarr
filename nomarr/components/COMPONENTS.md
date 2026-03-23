# Components Layer

The **components layer** contains heavy, domain-specific logic — analytics, tagging, ML inference, library scanning, and more. Components are the workhorses that do the real computational work of the system.

They are:

- **Domain logic modules** for a specific area (analytics, ML, tagging, library management)
- **Reusable building blocks** composed by workflows
- **The only layer that may call persistence**

> **⚠️ Persistence Rule:** Components are the **only** layer that may call persistence (`db.*`) directly. Services, workflows, and interfaces must go through components for any database access.

> **Rule:** Heavy business logic lives here. Wiring lives in services. Control flow composition lives in workflows.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Components sit **below workflows** and **must not import** services, workflows, or interfaces. Lateral (same-layer) imports are allowed — components may import other components.

---

## 2. Directory Structure

```text
components/
├── analytics/
│   ├── analytics_comp.py             # Tag statistics, co-occurrence
│   ├── collection_overview_comp.py    # Collection-level summaries
│   └── mood_analysis_comp.py          # Mood distribution analysis
│
├── infrastructure/
│   ├── health_comp.py                # Health monitoring
│   └── path_comp.py                  # Path resolution utilities
│
├── library/
│   ├── file_batch_scanner_comp.py     # Batch file scanning
│   ├── file_library_comp.py           # File–library associations
│   ├── file_sync_comp.py              # File synchronization
│   ├── file_tags_comp.py              # File tag operations
│   ├── folder_analysis_comp.py        # Folder structure analysis
│   ├── library_admin_comp.py          # Library CRUD
│   ├── library_root_comp.py           # Root path operations
│   ├── list_libraries_comp.py         # Library listing
│   ├── metadata_extraction_comp.py    # Audio metadata extraction
│   ├── missing_file_detection_comp.py # Detect removed files
│   ├── move_detection_comp.py         # Detect moved files
│   ├── reconcile_paths_comp.py        # Path reconciliation
│   ├── scan_lifecycle_comp.py         # Scan state management
│   ├── search_files_comp.py           # File search
│   ├── tag_cleanup_comp.py            # Orphan tag cleanup
│   ├── update_library_metadata_comp.py # Library metadata updates
│   ├── validate_scan_state_comp.py    # Scan state validation
│   └── work_status_comp.py            # Work queue status
│
├── metadata/
│   ├── entity_cleanup_comp.py         # Entity cleanup
│   ├── entity_seeding_comp.py         # Entity seeding
│   └── metadata_cache_comp.py         # Metadata caching
│
├── ml/
│   ├── audio/
│   │   ├── ml_audio_comp.py           # Audio loading (Essentia MonoLoader)
│   │   ├── ml_chromaprint_comp.py     # Audio fingerprinting
│   │   └── ml_preprocess_comp.py      # Mel spectrogram preprocessing (Essentia)
│   │
│   ├── calibration/
│   │   ├── ml_calibration_comp.py     # Calibration logic
│   │   └── ml_calibration_state_comp.py # Calibration state
│   │
│   ├── inference/
│   │   ├── ml_backbone_embed_comp.py  # Backbone embedding extraction
│   │   ├── ml_embed_comp.py           # Embedding computation
│   │   ├── ml_head_pipeline_comp.py   # Head inference pipeline
│   │   ├── ml_heads_comp.py           # Head management
│   │   └── ml_segment_stats_comp.py   # Segment score statistics
│   │
│   ├── onnx/
│   │   ├── ml_backbone.py             # ONNX backbone model wrapper
│   │   ├── ml_base.py                 # ONNX base model class
│   │   ├── ml_cache.py                # Model/session caching
│   │   ├── ml_constants.py            # ML constants
│   │   ├── ml_discovery_comp.py       # Model file discovery
│   │   ├── ml_head.py                 # ONNX head model wrapper
│   │   ├── ml_known_models_comp.py    # Known model registry
│   │   └── ml_session_comp.py         # ONNX session management
│   │
│   ├── resources/
│   │   ├── ml_capacity_probe_comp.py  # ML capacity estimation
│   │   ├── ml_tier_selection_comp.py   # Processing tier selection
│   │   ├── ml_timing_comp.py          # Inference timing
│   │   ├── ml_vram_coordinator_comp.py # VRAM coordination
│   │   ├── ml_vram_probe_comp.py      # VRAM probing
│   │   └── ml_worker_context_comp.py  # Worker context management
│   │
│   └── vectors/
│       ├── ml_vector_idle_promotion_comp.py  # Idle vector promotion
│       ├── ml_vector_maintenance_comp.py     # Vector maintenance
│       ├── ml_vector_persist_comp.py         # Vector persistence
│       ├── ml_vector_pool_comp.py            # Vector pool management
│       └── ml_vector_retrieve_comp.py        # Vector retrieval
│
├── navidrome/
│   ├── m3u_comp.py                    # M3U playlist generation
│   ├── playlist_builder_comp.py        # Smart playlist building
│   ├── subsonic_client_comp.py         # Subsonic API client
│   ├── subsonic_crawl_comp.py          # Subsonic library crawling
│   ├── tag_query_comp.py              # Tag-based song queries
│   ├── taste_profile_comp.py          # User taste profiling
│   └── templates_comp.py              # Playlist template handling
│
├── platform/
│   ├── arango_bootstrap_comp.py       # ArangoDB initialization
│   ├── arango_first_run_comp.py       # First-run provisioning
│   ├── gpu_monitor_comp.py            # GPU monitoring
│   ├── gpu_probe_comp.py              # GPU detection
│   ├── migration_runner_comp.py        # Database migration runner
│   └── resource_monitor_comp.py        # System resource monitoring
│
├── playlist_import/
│   ├── deezer_fetcher_comp.py         # Deezer playlist fetching
│   ├── metadata_normalizer_comp.py    # Import metadata normalization
│   ├── spotify_fetcher_comp.py        # Spotify playlist fetching
│   ├── track_matcher_comp.py          # Track matching for imports
│   └── url_parser_comp.py             # Playlist URL parsing
│
├── processing/
│   └── file_write_comp.py             # File write operations
│
├── tagging/
│   ├── mood_labels_comp.py            # Mood label definitions
│   ├── safe_write_comp.py             # Safe tag writing
│   ├── tag_normalization_comp.py      # Tag normalization
│   ├── tag_parsing_comp.py            # Tag parsing
│   ├── tagging_aggregation_comp.py    # Tag aggregation
│   ├── tagging_reader_comp.py         # Tag reading
│   ├── tagging_reconstruction_comp.py # Tag reconstruction
│   ├── tagging_remove_comp.py         # Tag removal
│   └── tagging_writer_comp.py         # Tag writing
│
└── workers/
    ├── worker_crash_comp.py           # Crash handling decisions
    └── worker_discovery_comp.py       # Worker discovery
```

**Naming rules:**

- Modules: `snake_case_comp.py` by domain (e.g., `analytics_comp.py`, `ml_embed_comp.py`)
- Public functions: clear verb–noun names (`compute_embeddings`, `aggregate_mood_tags`)
- Private helpers: `_prefix` (`_load_model`, `_format_tag_stats`)

Classes should be rare; prefer **stateless, pure functions** unless state is truly needed.

---

## 3. ML Backend

The ML backend is **ONNX Runtime** (`components/ml/onnx/`). Essentia is **not** the ML backend — it provides only two thin functions:

| Module | Essentia Usage |
|---|---|
| `ml/audio/ml_audio_comp.py` | `MonoLoader` for audio loading |
| `ml/audio/ml_preprocess_comp.py` | Mel spectrogram preprocessing |

> **⚠️ Essentia Isolation:** `essentia` must **only** be imported in `ml_audio_comp.py` and `ml_preprocess_comp.py`. All ML inference runs through ONNX Runtime.

**ML subdirectory organization:**

| Subdirectory | Responsibility |
|---|---|
| `audio/` | Audio I/O and preprocessing (Essentia + chromaprint) |
| `calibration/` | Score calibration and state |
| `inference/` | Backbone + head inference pipeline |
| `onnx/` | ONNX Runtime session management, model wrappers |
| `resources/` | VRAM coordination, capacity probing, tier selection |
| `vectors/` | Vector persistence, retrieval, maintenance, promotion |

---

## 4. Boundaries & Import Rules

**Allowed:**
- ✅ Persistence (`nomarr.persistence.*`) — components are the only layer that may
- ✅ Helpers (`nomarr.helpers.*`)
- ✅ Other components (`nomarr.components.*`) — lateral imports
- ✅ Standard library, numpy, etc.

**Forbidden:**
- ❌ Services (`nomarr.services.*`)
- ❌ Workflows (`nomarr.workflows.*`)
- ❌ Interfaces (`nomarr.interfaces.*`)
- ❌ Pydantic models
- ❌ HTTP or CLI frameworks

Components are leaf domain modules. They never depend on higher layers.

---

## 5. What Belongs in Components

Components implement **heavy or specialized domain logic**:

- ML inference and embeddings
- Calibration logic and scoring
- Tag aggregation and resolution
- Complex statistical analysis
- Library scanning and file detection
- Non-trivial data transformations

**Not components:** wiring/resource management (services), control flow over multiple operations (workflows), HTTP/CLI concerns (interfaces).

---

## 6. Patterns

### Complexity & Private Helpers

Components may have large, complex functions. Break them into `_private` helpers for readability:

```python
def compute_tag_statistics(db: Database, library_id: str) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    return TagStats(_format_tag_stats(stats))
```

### Purity & State

Aim for **pure, stateless functions**. Avoid long-lived mutable globals. If caching is needed, prefer explicit cache objects passed as dependencies.

### Persistence Usage

Components access the database through the persistence layer (`db.module.method()`). No raw AQL inside components.

```python
# ✅ Uses persistence
def compute_tag_frequencies(db: Database, library_id: str) -> dict[str, int]:
    tags = db.tags.get_library_tags(library_id)
    return {tag["name"]: tag["count"] for tag in tags}
```

### Configuration

Components must **not** read environment variables or global config directly. Configuration is resolved in services/workflows and passed as parameters.

### Return Types

Components may return: primitives, collections, numpy arrays, DTOs from `helpers/dto/`, domain objects. They **must not** return Pydantic models (interface concern).
