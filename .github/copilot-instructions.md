# Copilot Instructions for Nomarr

These instructions tell you how to write code that fits Nomarr’s architecture and does not fight the project’s direction.

Nomarr is **pre-alpha** but already public and fully functional. That means:

- There is **no backward compatibility guarantee**.
- It is acceptable to **break schemas and APIs** while the design is still stabilizing.
- Do **not** introduce migrations, legacy shims, or compatibility layers yet.
- The priority is **clean architecture and predictability**, not preserving old data.

You are here to help maintain that architecture, not invent a new one.

---

## 0. Hard Rules (Read These First)

**Never:**

- import `essentia` or `essentia_tensorflow` anywhere except `ml/backend_essentia.py`
- read config files or environment variables at module import time
- create or mutate global state (except very narrow, explicitly approved cases)
- make functions > ~60 lines unless there is a clear, structural reason
- make modules > ~300 lines without strong justification
- let workflows import `nomarr.services` or `nomarr.interfaces`
- let persistence or ml import `nomarr.workflows`, `nomarr.services`, or `nomarr.interfaces`
- let helpers import any `nomarr.*` modules

**Always:**

- follow the layering rules and directory placement below
- use dependency injection (receive `db`, config, ML backends, etc. as parameters or constructor deps)
- keep imports local when they are optional or heavy (Essentia, ML backends, etc.)
- write mypy-friendly, fully type-annotated Python
- write code that passes `ruff`, `mypy`, and `pytest` without needing huge repairs

---

## 1. Project Philosophy

Nomarr is structured around:

- **Separation of concerns**
- **Dependency injection (DI)** instead of global singletons
- **Deterministic, explicit behavior**
- **Testable building blocks**

Responsibilities:

- **Interfaces** expose Nomarr to the outside world.
- **Services** own runtime wiring and long-lived resources (config, DB, queues, workers).
- **Workflows** implement core use cases ("what Nomarr does").
- **Analytics** provides tag statistics, correlations, and co-occurrence analysis.
- **Tagging** converts model outputs into tags.
- **ML** is model/embedding/inference code.
- **Persistence** is the DB/queue access layer.
- **Helpers** are pure utilities and shared data types.

---

## 2. Architecture & Dependencies

### 2.1 High-Level Flow

For any non-trivial operation:

```text
interfaces  →  services  →  workflows  →  (analytics / tagging / ml / persistence / helpers)
```

### 2.2 Allowed Dependencies (Direction)

- `interfaces`:

  - ✅ may import `nomarr.services`
  - ✅ may import `nomarr.helpers`
  - ❌ must NOT import `nomarr.workflows`, `nomarr.persistence`, `nomarr.ml`, `nomarr.tagging`, or `nomarr.analytics`

- `services`:

  - ✅ may import `nomarr.workflows`
  - ✅ may import `nomarr.persistence`
  - ✅ may import `nomarr.tagging`, `nomarr.ml`, and `nomarr.analytics` (through proper facades/caches)
  - ✅ may import `nomarr.helpers`
  - ❌ must NOT import `nomarr.interfaces`

- `workflows`:

  - ✅ may import `nomarr.persistence`
  - ✅ may import `nomarr.tagging`
  - ✅ may import `nomarr.ml`
  - ✅ may import `nomarr.analytics`
  - ✅ may import `nomarr.helpers`
  - ❌ must NOT import `nomarr.services` or `nomarr.interfaces`

- `persistence`:

  - ✅ may import `nomarr.helpers`
  - ❌ must NOT import `nomarr.workflows`, `nomarr.services`, or `nomarr.interfaces`

- `ml`:

  - ✅ may import `nomarr.helpers`
  - ❌ must NOT import `nomarr.workflows`, `nomarr.services`, or `nomarr.interfaces`

- `analytics`:

  - ✅ may import `nomarr.persistence` and `nomarr.helpers`
  - ❌ must NOT import `nomarr.workflows`, `nomarr.services`, or `nomarr.interfaces`

- `tagging`:

  - ✅ may import `nomarr.ml`, `nomarr.helpers`, and `nomarr.persistence`
  - ❌ must NOT import `nomarr.interfaces` or `nomarr.services`

- `helpers`:

  - ❌ must NOT import any `nomarr.*` modules
  - ✅ may import stdlib and third-party libraries only

Use this rule of thumb:

> Interfaces call **services**.
> Services own **wiring and long-lived resources** and call **workflows**.
> Workflows implement **use cases** and call **analytics / tagging / ml / persistence / helpers**.
> Analytics, ML & persistence never know about higher layers.
> Helpers never know about `nomarr.*`.

Import-linter enforces this; follow it rather than fighting it.

---

## 3. Directory Placement Rules (Where Code Should Live)

### Quick Decision Guide

When adding new code, ask:

- **Does it handle HTTP, CLI, or UI?** → `interfaces/`
- **Does it manage config, DB, queues, workers, or background jobs?** → `services/`
- **Does it implement a use case ("scan library", "process track", "recalibrate tags")?** → `workflows/`
- **Does it compute tag statistics, correlations, or co-occurrences?** → `analytics/`
- **Does it convert model outputs into tags, or aggregate/resolve tags?** → `tagging/`
- **Does it compute embeddings, heads, or apply ML models?** → `ml/`
- **Does it read/write DB tables or queues?** → `persistence/`
- **Is it a stateless utility or shared data type used in many layers?** → `helpers/`

### 3.1 `interfaces/` — How Nomarr is Exposed

- HTTP routes (FastAPI), CLI commands, web handlers.
- Thin: validate inputs, call a service, serialize outputs.
- They must not know about DB schema, ML details, or tagging rules.

**Example:**
`interfaces/api/coordinator.py` → receives HTTP request, calls a service like `QueueService` or `ProcessingService`.

### 3.2 `services/` — Runtime Wiring & Long-Lived Stuff

- Owns:

  - `ConfigService`
  - `Database` construction (from `nomarr.persistence.db`)
  - queues and queue abstractions (`QueueService`, `ProcessingQueue`)
  - background workers and schedulers

- Exposes methods like:

  - `QueueService.enqueue_track(...)`
  - `ProcessingService.process_file(...)`

- These methods:

  - gather dependencies (config, db, ML backends, tag writers, cache)
  - call **workflows** to perform the actual work

Services **should not** contain complicated business rules; push logic down into workflows when it grows.

### 3.3 `workflows/` — Use Cases (What Nomarr Does)

- Implements operations like:

  - `process_file(...)`
  - `scan_library(...)`
  - `run_recalibration(...)`

- Functions accept all dependencies as parameters:

  - `ProcessorConfig` (from helpers/dataclasses)
  - `Database` or narrower persistence objects
  - ML predictor/embeddings interfaces
  - tag writers / calibration helpers

- No global config reading. No `ConfigService` imports.

Workflows are where most "interesting logic" lives.

### 3.4 `analytics/` — Tag Statistics & Correlations

- Computes tag statistics, correlations, and co-occurrence analysis:

  - tag frequency counts
  - mood distribution analysis
  - tag correlation matrices
  - co-occurrence patterns

- Operates on database queries via persistence layer.
- Returns structured data for presentation layers.

No HTTP, no services, no workflows imports.

### 3.5 `tagging/` — Tags & Label Logic

- Takes model outputs and produces tags:

  - tiering (loose/medium/strict)
  - conflict resolution (happy vs sad, etc.)
  - aggregation across runs

- Writes tags into files or DB via persistence.

No HTTP, no services, no workers.

### 3.6 `ml/` — Models, Embeddings, Inference

- Encapsulate model loading, prediction, and calibration logic.
- Examples:

  - embedding extraction
  - model confidence outputs
  - calibration utilities

- Only `ml/backend_essentia.py` is allowed to import Essentia.

No knowledge of services, workflows, or interfaces.

### 3.7 `persistence/` — Database & Queue Access

Structure:

```text
nomarr/persistence/
  db.py              # Database façade / connection owner
  database/
    queue.py         # QueueOperations for tag_queue table
    library.py       # LibraryOperations
    tags.py          # TagOperations
    meta.py          # MetaOperations
    sessions.py      # SessionOperations
    calibration.py   # CalibrationOperations
```

- `nomarr.persistence.database.*`:

  - each file defines one `*Operations` class per table or cohesive group of tables
  - each class owns **all SQL** for that table/group

- `nomarr.persistence.db.Database`:

  - opens the DB connection
  - ensures schema
  - instantiates operations and hangs them as attributes:

    ```python
    self.meta = MetaOperations(self.conn)
    self.queue = QueueOperations(self.conn)
    self.library = LibraryOperations(self.conn)
    self.tags = TagOperations(self.conn)
    self.sessions = SessionOperations(self.conn)
    self.calibration = CalibrationOperations(self.conn)
    ```

- All higher layers should access the DB as:

  ```python
  db.queue.enqueue(...)
  db.tags.get_track_tags(...)
  db.library.list_files(...)
  db.meta.get_meta(...)
  ```

No external code should import `nomarr.persistence.database.*` directly. Only `nomarr.persistence.db` does that.

### 3.8 `helpers/` — Pure Utilities & Shared Dataclasses

- Pure utility functions (string helpers, path helpers, small math, etc.).
- Shared dataclasses that are imported from multiple top-level packages go in `helpers/dataclasses.py`.

Rules for `helpers/dataclasses.py`:

- Only include dataclasses that are imported from more than one top-level package (e.g., `services` and `workflows`).
- Must not import any `nomarr.*` modules.
- Only import `dataclasses`, `typing`, and stdlib.
- No methods with behavior beyond trivial `__str__` / formatting.

If a dataclass is only used in one layer, keep it local to that layer’s module.

---

## 4. Configuration & DI

### 4.1 No `nomarr.config` Globals

- Do **not** add new usages of `nomarr.config`.
- Do **not** read config files or env vars at module import time.
- Config should be loaded once by a **service** (e.g., `ConfigService`) and then passed into other structures via DI.

### 4.2 How Configuration Should Flow

- `ConfigService` (in `services/config.py`):

  - loads and validates config (Pydantic or similar)
  - exposes typed config objects

- Services that need config receive it via constructor or method parameters.
- Workflows that need config receive **typed config objects** as function parameters (e.g., `ProcessorConfig` from `helpers/dataclasses.py`).
- No one re-reads raw config files in deeper layers.

---

## 5. Essentia & ML Backends

Essentia is an optional dependency and must be isolated.

- Only `ml/backend_essentia.py` may contain:

  ```python
  try:
      import essentia_tensorflow as essentia_tf
  except ImportError:  # pragma: no cover
      essentia_tf = None
  ```

- All other code calls functions or classes in `ml/backend_essentia.py` and must not import Essentia directly.

- If Essentia is missing, ML-related paths should raise **clear runtime errors** _only when those paths are executed_, not at app startup.

---

## 6. Code Style & Quality

### 6.1 Python

- Fully type-annotated
- Follow `ruff` formatting and linting
- Aim for:

  - < 60 lines per function
  - < 300 lines per module

- Prefer:

  - pure, testable functions
  - explicit rather than clever
  - clear naming (`error_message`, not `err_msg`)

### 6.2 Error Handling

- No bare `except:`; always catch specific exceptions.
- Provide helpful messages on runtime errors (especially for missing dependencies like Essentia or bad config).

---

## 7. Tooling & QC

Nomarr uses several tools. You should write code that works _with_ them, not against them.

### 7.1 Core Tools (Run Often)

```bash
ruff check .
ruff check --fix .
ruff format .
pytest
mypy .
```

Your code should be consistent with what these tools expect.

### 7.2 Deeper Analysis (Run Periodically)

```bash
bandit .
vulture .
radon cc -s nomarr
radon mi -s nomarr
flake8
import-linter
wily build
```

If these tools report issues, consider them **real signals**, not noise.

---

## 8. Development Scripts (`scripts/`)

The `scripts/` directory contains helpers that you (and Copilot) should use instead of guessing.

### 8.1 Purpose

Use these scripts to:

- discover real APIs instead of inventing functions
- enforce naming and structure conventions
- generate boilerplate in a consistent style
- identify complexity hotspots and refactor targets

### 8.2 Before Writing or Modifying Code

```bash
# Inspect real module APIs, attributes, and callables
python scripts/discover_api.py nomarr.workflows.processor
python scripts/discover_api.py nomarr.persistence.db --summary
```

> **Copilot rule:** Always use `discover_api.py` to verify APIs before calling them. Never guess function names, parameters, or return types.

### 8.3 During Development

```bash
# Enforce naming rules across the project
python scripts/check_naming.py

# Generate __init__.py exports to match actual module APIs
python scripts/generate_inits.py

# Create test scaffolds from current module structure
python scripts/generate_tests.py nomarr.services.queue --output tests/unit/services/test_queue.py
```

### 8.4 Targeted Quality & Refactor Triage

```bash
# Find complexity hotspots, architecture violations, and refactor opportunities
python scripts/detect_slop.py nomarr/workflows/processor.py
```

Use `detect_slop.py` on **one file or one package at a time**:

- summarize the report,
- propose a small, focused refactor,
- apply changes iteratively.

Do **not** try to “fix the whole codebase” from one giant report.

---

## 9. Pre-Alpha Policy (Important)

Nomarr is **pre-alpha**. That means:

- It is okay to:

  - break schemas
  - change APIs
  - require users to rebuild their database or rescan their library

- It is **not** okay to:

  - build migration frameworks
  - introduce versioned compatibility layers
  - pile up “legacy” code paths to support old formats

Prefer clean, forward-looking changes over preserving old structures.

---

## 10. Summary for Copilot

1. **Follow the layering:**
   `interfaces → services → workflows → (tagging / ml / persistence / helpers)`
   Never let lower layers import higher ones.

2. **Interfaces call services only.**
   They never touch workflows, persistence, tagging, or ml directly.

3. **Services own wiring and long-lived resources.**
   They construct config, DB, queues, workers, and call workflows.

4. **Workflows implement use cases.**
   They accept dependencies as parameters and call tagging/ml/persistence/helpers.

5. **Persistence & ML are leaf layers.**
   They never import workflows, services, or interfaces. All DB access goes through `persistence.db.Database` and its `*Operations` classes.

6. **Helpers are pure.**
   They never import `nomarr.*` and contain only utilities and truly shared dataclasses.

7. **Do not introduce migrations, legacy shims, or backward-compat code paths.**
   Pre-alpha means breaking changes are allowed.

8. **Use `discover_api.py` instead of guessing.**
   Never assume a function exists; check first.

Your job is to write code that respects this architecture, passes the existing tools, and does not invent new patterns unless explicitly asked.

---

End of instructions.
