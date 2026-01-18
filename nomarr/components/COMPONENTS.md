## Components Layer

The **components layer** contains heavy, domain-specific logic (analytics, tagging, ML, etc.). Components are the workhorses that do the real computational work of the system.

They are:

* **Domain logic modules** for a specific area (analytics, ML, tagging).
* **Leaf modules** in the architecture (nothing depends *on them* except workflows and services).
* **Reusable building blocks** used by workflows.

> **Rule:** Heavy business logic lives here. Wiring lives in services. Control flow composition lives in workflows.

---

## 1. Position in the Architecture

Layers:

* **Interfaces** – HTTP/CLI/SSE, Pydantic, auth, HTTP status codes
* **Services** – dependency wiring, thin orchestration, DTO boundaries
* **Workflows** – domain flows, multi-step operations, control logic
* **Components** – heavy computations, analytics, ML, tagging
* **Persistence / Helpers** – DB access and generic utilities

Components sit **below workflows** and **must not import** services or interfaces.

---

## 2. Directory Structure & Naming

Components live under `nomarr/components/`, grouped by domain:

```text
components/
├── analytics/
│   └── analytics_comp.py           # Tag statistics, co-occurrence
├── events/
│   ├── event_broker_comp.py        # Event broadcasting
│   └── sse_stream_comp.py          # Server-sent events streaming
├── infrastructure/
│   └── path_comp.py                # Path resolution utilities
├── library/
│   ├── file_tags_comp.py           # File tag operations
│   ├── library_admin_comp.py       # Library CRUD
│   ├── library_root_comp.py        # Root path operations
│   ├── metadata_extraction_comp.py # Audio metadata extraction
│   ├── reconcile_paths_comp.py     # Path reconciliation
│   ├── search_files_comp.py        # File search
│   └── tag_cleanup_comp.py         # Orphan tag cleanup
├── metadata/
│   ├── entity_keys_comp.py         # Entity key generation
│   ├── entity_seeding_comp.py      # Entity seeding
│   └── metadata_cache_comp.py      # Metadata caching
├── ml/
│   ├── chromaprint_comp.py         # Audio fingerprinting
│   ├── ml_audio_comp.py            # Audio loading/processing
│   ├── ml_backend_essentia_comp.py # Essentia ML backend (ONLY Essentia import)
│   ├── ml_cache_comp.py            # Embedding/prediction caching
│   ├── ml_calibration_comp.py      # Calibration logic
│   ├── ml_discovery_comp.py        # Model discovery
│   ├── ml_embed_comp.py            # Embedding computation
│   ├── ml_heads_comp.py            # Head management
│   └── ml_inference_comp.py        # Inference orchestration
├── navidrome/
│   └── templates_comp.py           # Navidrome template handling
├── platform/
│   ├── arango_bootstrap_comp.py    # ArangoDB initialization
│   ├── arango_first_run_comp.py    # First-run setup
│   ├── gpu_monitor_comp.py         # GPU monitoring
│   └── gpu_probe_comp.py           # GPU detection
├── queue/
│   ├── queue_cleanup_comp.py       # Queue maintenance
│   ├── queue_dequeue_comp.py       # Job dequeuing
│   ├── queue_enqueue_comp.py       # Job enqueuing
│   └── queue_status_comp.py        # Queue status
├── tagging/
│   ├── safe_write_comp.py          # Safe tag writing
│   ├── tagging_aggregation_comp.py # Tag aggregation
│   ├── tagging_reader_comp.py      # Tag reading
│   ├── tagging_remove_comp.py      # Tag removal
│   ├── tagging_writer_comp.py      # Tag writing
│   ├── tag_normalization_comp.py   # Tag normalization
│   └── tag_parsing_comp.py         # Tag parsing
└── workers/
    ├── job_recovery_comp.py        # Job recovery after crashes
    └── worker_crash_comp.py        # Crash handling decisions
```

Naming rules:

* Modules: `snake_case_comp.py` by domain (e.g., `analytics_comp.py`, `ml_embed_comp.py`).
* Public functions: clear verb–noun names (`compute_embeddings`, `compute_tag_statistics`, `aggregate_mood_tags`).
* Private helpers: `_prefix` (`_load_model`, `_format_tag_stats`).

Classes should be rare; prefer **stateless, pure functions** unless state is truly needed (e.g., caching inside a single call).

---

## 3. What Belongs in Components

Components implement **heavy or specialized domain logic**, for example:

* ML inference and embeddings
* Calibration logic and scoring
* Tag aggregation and resolution
* Complex statistical analysis
* Non-trivial data transformations

Examples:

```python
# Analytics example

def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    formatted = _format_tag_stats(stats)
    return TagStats(formatted)


# ML example

def compute_embeddings(
    file_path: str,
    models_dir: str,
    backbone: str,
) -> np.ndarray:
    audio = _load_audio(file_path)
    segments = _segment_audio(audio)
    model = _load_model(models_dir, backbone)
    return np.stack([model.predict(seg) for seg in segments])


# Tagging example

def predictions_to_tags(
    predictions: dict[str, np.ndarray],
    namespace: str,
    threshold: float = 0.5,
) -> list[Tag]:
    tags: list[Tag] = []
    for head_name, scores in predictions.items():
        for idx, score in enumerate(scores):
            if score >= threshold:
                tags.append(
                    Tag(
                        namespace=namespace,
                        head=head_name,
                        value=idx,
                        score=score,
                    )
                )
    return tags


# Worker crash handling example

def should_restart_worker(
    restart_count: int,
    last_restart_ms: int,
) -> RestartDecision:
    """
    Decide whether to restart a crashed worker or mark it as failed.
    
    Uses two-tier limits:
    - Rapid: 5 restarts in 5 minutes (catches OOM loops)
    - Lifetime: 20 total restarts (catches slow thrashing)
    """
    now_ms = int(time.time() * 1000)
    
    # Check rapid restart limit
    if restart_count >= 5 and (now_ms - last_restart_ms) < (5 * 60 * 1000):
        return RestartDecision(
            action="mark_failed",
            reason="Exceeded 5 restarts in 5 minutes",
            backoff_seconds=0,
            failure_reason="Worker exceeded rapid restart limit (5 restarts in 5.0 minutes)..."
        )
    
    # Check lifetime restart limit
    if restart_count >= 20:
        return RestartDecision(
            action="mark_failed",
            reason="Exceeded 20 lifetime restarts",
            backoff_seconds=0,
            failure_reason="Worker exceeded lifetime restart limit (20 total restarts)..."
        )
    
    # Continue restarting with exponential backoff
    backoff = calculate_backoff(restart_count)
    return RestartDecision(
        action="restart",
        reason=f"Restart #{restart_count + 1} after {backoff}s backoff",
        backoff_seconds=backoff,
        failure_reason=None
    )
```

If you are writing non-trivial domain math, statistics, ML, or transformations, it almost certainly belongs here.

---

## 4. Boundaries & Allowed Imports

Components **may import**:

* Persistence abstractions (DB / repositories)
* DTOs and simple domain types
* Other component modules in the same domain (for reuse)
* Helpers (filesystem, math utilities, etc.)

Examples:

```python
# ✅ Allowed in components
from nomarr.persistence import Database
from nomarr.helpers.dto import ProcessFileResult
from nomarr.components.ml.model_loading import load_model
from nomarr.helpers.files_helper import discover_audio_files
```

Components **must NOT import**:

* Services (`nomarr.services.*`)
* Workflows (`nomarr.workflows.*`)
* Interfaces or routers (`nomarr.interfaces.*`, FastAPI router, etc.)
* Pydantic models
* HTTP or CLI frameworks

```python
# ❌ Not allowed
from nomarr.services import ProcessingService        # no services
from nomarr.workflows import process_file_workflow   # no workflows
from nomarr.interfaces.api import router             # no interfaces
from pydantic import BaseModel                       # no Pydantic
```

> **Rule:** Components are leaf domain modules. They never depend on higher layers.

---

## 5. Complexity & Private Helpers

### 5.1. Heavy Logic Lives Here

Components are where it is acceptable for functions to be large and complex **as long as they are well-structured**.

Use `_private` helpers to keep public functions readable.

```python
# Before – too large for a single function

def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    # 40 lines of querying
    rows = db.tags.get_stats_rows(library_id)

    # 40 lines of aggregation
    stats: dict[str, int] = {}
    for row in rows:
        ...

    # 40 lines of formatting
    formatted = {}
    for key, value in stats.items():
        ...

    return TagStats(formatted)


# After – split into helpers

def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    formatted = _format_tag_stats(stats)
    return TagStats(formatted)


def _query_tag_data(db: Database, library_id: int) -> list[dict[str, Any]]:
    ...


def _aggregate_tag_stats(rows: list[dict[str, Any]]) -> dict[str, int]:
    ...


def _format_tag_stats(stats: dict[str, int]) -> dict[str, Any]:
    ...
```

Create `_private` helpers when:

* A public function exceeds ~80 LOC.
* There are clearly distinct phases (query → aggregate → format).
* Logic can be named and reused inside the module.

### 5.2. Centralizing Shared Helpers

If you find yourself copy-pasting the same `_load_model` or `_normalize_tags` across multiple modules, centralize it in a dedicated component helper.

```python
# components/ml/model_loading.py

def load_model(models_dir: str, backbone: str) -> Model:
    """Shared ML model loader for all ML components."""
    ...

# components/ml/embeddings.py
from nomarr.components.ml.model_loading import load_model
```

---

## 6. Purity & State

Aim for **pure, stateless functions**:

```python
# ✅ Good – pure

def aggregate_mood_tags(tags: list[Tag], mapping: dict[str, str]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for tag in tags:
        if tag.head in mapping:
            key = mapping[tag.head]
            scores[key] = max(scores.get(key, 0.0), tag.score)
    return scores
```

Avoid:

* Long-lived mutable globals (`_MODEL_CACHE = {}` at module level).
* Classes whose primary job is to mutate internal state over time.

If caching is required, prefer:

* Explicit cache objects passed in as dependencies, or
* Very limited, well-documented module-level caches with clear invalidation (and only if truly needed).

---

## 7. Persistence Usage

Components may talk to the database **only through the persistence layer**.

```python
# ✅ Good – uses persistence abstraction

def compute_tag_frequencies(db: Database, library_id: int) -> dict[str, int]:
    tags = db.tags.get_library_tags(library_id)
    freq: dict[str, int] = {}
    for tag in tags:
        freq[tag.name] = freq.get(tag.name, 0) + 1
    return freq


# ❌ Bad – raw SQL inside component

def compute_tag_frequencies(db: Database, library_id: int) -> dict[str, int]:
    rows = db.execute_raw("SELECT tag, COUNT(*) FROM tags WHERE ...")
    ...
```

No raw SQL belongs here; put it in persistence and call that from the component.

---

## 8. Data & DTOs

Components may return:

* Primitive types (`int`, `float`, `str`, `bool`)
* Collections (`list`, `dict`, `set`, `np.ndarray`, etc.)
* DTOs from `helpers/dto/`
* Domain objects such as `Tag`, `InferenceResult`, etc.

They **must not** return Pydantic models.

```python
# ✅ OK

def run_inference(...) -> InferenceResult:
    ...


# ❌ Not OK

from pydantic import BaseModel

class EmbeddingResult(BaseModel):
    ...


def compute_embeddings(...) -> EmbeddingResult:
    ...
```

Pydantic is an interface concern, not a components concern.

---

## 9. Configuration & Environment

Components must **not** read environment variables or global config directly.

Bad:

```python
def compute_embeddings(path: str) -> np.ndarray:
    import os
    models_dir = os.getenv("MODELS_DIR")  # ❌ no env reads here
    ...
```

Good:

```python
def compute_embeddings(path: str, models_dir: str) -> np.ndarray:
    ...
```

Configuration is resolved in services and workflows, then passed into components as plain arguments.

---

## 10. Anti-Patterns

Avoid these in components:

* Importing services, workflows, or interfaces.
* Raising HTTP or CLI-specific exceptions.
* Returning Pydantic models.
* Raw SQL or direct file/OS probing for config.
* Hidden global state that changes over time.

When in doubt:

* If it’s **heavy domain logic**, it probably belongs here.
* If it’s **wiring or resource management**, it belongs in services.
* If it’s **control flow over multiple operations**, it belongs in workflows.
