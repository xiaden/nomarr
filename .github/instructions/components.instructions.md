---
name: Components Layer
description: Auto-applied when working with nomarr/components/ - Heavy domain logic
applyTo: nomarr/components/**
---

# Components Layer

**Purpose:** Contain heavy, domain-specific logic (analytics, tagging, ML, etc.).

Components are the **workhorses** that do the real computational work:

- ML inference and embeddings
- Tag aggregation and resolution
- Statistical analysis
- Complex data transformations
- Return [DTOs](./helpers.instructions.md)
- May call [persistence](./persistence.instructions.md) and [helper utilities](./helpers.instructions.md)

**Rule:** Heavy business logic lives here. Wiring lives in services. Control flow lives in workflows.

---

## Directory Structure

```
components/
├── analytics/          # Tag statistics, co-occurrence, mood analysis
├── infrastructure/     # Health checks, path management
├── library/            # Library file operations, scanning, sync
├── metadata/           # Entity cleanup, seeding, metadata cache
├── ml/                 # ML inference, embeddings, calibration
│   ├── audio/          # Audio loading (Essentia), mel preprocessing
│   ├── calibration/    # Model calibration
│   ├── inference/      # Embedding computation, head pipelines
│   ├── onnx/           # ONNX Runtime session management, model discovery
│   ├── resources/      # VRAM coordination, GPU probing, timing
│   └── vectors/        # Vector persistence, pooling, retrieval
├── navidrome/          # Navidrome integration, Subsonic API
├── platform/           # GPU, bootstrap, migrations
├── playlist_import/    # External playlist import (Spotify, Deezer)
├── processing/         # File write operations
├── tagging/            # Tag parsing, writing, aggregation
└── workers/            # Worker crash handling, discovery
```

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.persistence import Database
from nomarr.helpers.dto import ProcessFileResult
from nomarr.components.ml.model_loading import load_model  # Cross-component OK
from nomarr.helpers.files_helper import discover_audio_files
```

## Forbidden Imports

```python
# ❌ NEVER import these in components
from nomarr.services import ...      # No services
from nomarr.workflows import ...     # No workflows
from nomarr.interfaces import ...    # No interfaces
from pydantic import BaseModel       # No Pydantic

# ❌ ESSENTIA ONLY IN ml/audio/ml_audio_comp.py and ml/audio/ml_preprocess_comp.py
import essentia  # Only in the two files above
```

---

## MCP Server Tools

**Use the Nomarr MCP server to navigate this layer efficiently:**

- `read_module_api(module_name)` - See exported functions/classes before reading full files
- `locate_module_symbol(symbol_name)` - Find where components are defined
- `read_module_source(qualified_name)` - Get exact function/class source with line numbers
- `trace_module_calls(function)` - Follow call chains from components

**Before modifying any component, run `read_module_api` to understand its shape.**

---

## Essentia Isolation Rule

**Only `nomarr/components/ml/audio/ml_audio_comp.py` (audio loading) and `nomarr/components/ml/audio/ml_preprocess_comp.py` (mel spectrogram preprocessing) may import Essentia.**

Essentia is used **only** for audio I/O and preprocessing — it is **not** the ML backend. ONNX Runtime (`components/ml/onnx/`) is the ML inference backend.

All other ML code calls functions in those files:

```python
# In ml_audio_comp.py:
import essentia

def load_audio_mono(file_path: str, sample_rate: int = 16000) -> np.ndarray:
    """Load audio file as mono waveform via Essentia MonoLoader."""
    ...
```

---

## LibraryPath Authority

**`path_comp` is the sole authority for `LibraryPath` construction.**

All raw user paths and DB paths must flow through:

- `build_library_path_from_input()` — for API/CLI/user-provided paths
- `build_library_path_from_db()` — for paths retrieved from database

Components are responsible for:

- Calling factory functions before any filesystem access
- Checking `path.is_valid()` before proceeding
- Never accepting raw path strings where `LibraryPath` exists

Raw strings are never acceptable substitutes for `LibraryPath` once constructed. Deviations are architectural violations.

---

## Function Style

Components prefer **stateless, pure functions** over classes:

```python
# ✅ Good - stateless function
def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    return TagStats(stats)

# ❌ Avoid - stateful class (unless truly needed)
class TagStatsComputer:
    def __init__(self, db: Database):
        self.db = db  # Unnecessary state
```

---

## Naming Conventions

- **Module:** `snake_case_comp.py` (e.g., `analytics_comp.py`, `ml_embed_comp.py`)
- **Public functions:** `compute_embeddings`, `aggregate_mood_tags`
- **Private helpers:** `_load_model`, `_format_tag_stats`

---

## Complexity & Private Helpers

Components are where **large, complex functions are acceptable** if well-structured.

Use `_private` helpers to keep public functions readable:

```python
# Before - too large
def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    # 40 lines of querying
    # 40 lines of aggregation
    # 40 lines of formatting
    ...

# After - split into phases
def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    formatted = _format_tag_stats(stats)
    return TagStats(formatted)

def _query_tag_data(db: Database, library_id: int) -> list[dict]: ...
def _aggregate_tag_stats(rows: list[dict]) -> dict[str, int]: ...
def _format_tag_stats(stats: dict[str, int]) -> dict[str, Any]: ...
```

---

## Example: Worker Crash Handling

```python
def should_restart_worker(restart_count: int, last_restart_ms: int) -> RestartDecision:
    """
    Decide whether to restart a crashed worker or mark it as failed.
    
    Uses two-tier limits:
    - Rapid: 5 restarts in 5 minutes (catches OOM loops)
    - Lifetime: 20 total restarts (catches slow thrashing)
    """
    current_time_ms = now_ms()
    
    if restart_count >= 5 and (current_time_ms - last_restart_ms) < 300_000:
        return RestartDecision(action="mark_failed", reason="Rapid restart limit exceeded")
    
    if restart_count >= 20:
        return RestartDecision(action="mark_failed", reason="Lifetime restart limit exceeded")
    
    backoff = calculate_backoff(restart_count)
    return RestartDecision(action="restart", backoff_seconds=backoff)
```

---

## Size Guidelines

- **Consider splitting** at 300 LOC — review whether multiple domain concerns are coexisting in one class
- **MUST split** at 500 LOC — no exceptions; split before committing

When splitting, extract a sibling component (e.g., `ml_calibration_comp.py` + `ml_calibration_helpers_comp.py`). Never grow past the hard limit by adding more private helpers.

---

## Validation Checklist

Before committing component code, verify:

- [ ] Does this file import from services, workflows, or interfaces? **→ Violation**
- [ ] Does this file import Essentia directly (and isn't `ml/audio/ml_audio_comp.py` or `ml/audio/ml_preprocess_comp.py`)? **→ Violation**
- [ ] Does this accept raw path strings where `LibraryPath` should be used? **→ Violation**
- [ ] Is this doing orchestration instead of computation? **→ Should be a workflow**
- [ ] Are heavy functions split into `_private` helpers? **→ Recommended**
- [ ] Does the module name end in `_comp.py`? **→ Convention**
- [ ] **Does `lint_project_backend(path="nomarr/components")` pass with zero errors?** **→ MANDATORY**

---

## Validation

**Run `lint_project_backend(path="nomarr/components")` after every edit.** Zero errors is the only acceptable state.

This MCP tool runs ruff, mypy, and import-linter — covering style, types, and layer boundary enforcement.
