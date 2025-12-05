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
- invent modules, imports, attributes, or function names (use `scripts/discover_api.py` to confirm real APIs)

**Always:**

- follow the layering rules and directory placement below
- follow naming standards in `docs/dev/naming.md`
- consult layer-specific guidelines in each layer's base folder (e.g., `services/SERVICES.md`)
- use dependency injection (receive `db`, config, ML backends, etc. as parameters or constructor deps)
- keep imports local when they are optional or heavy (Essentia, ML backends, etc.)
- write mypy-friendly, fully type-annotated Python
- write code that passes `ruff`, `mypy`, and `pytest` without needing huge repairs
- prefer minimal diffs unless explicitly instructed otherwise

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
- **Components** contain heavy, domain-specific logic (analytics, tagging, ML).
- **Persistence** is the DB/queue access layer.
- **Helpers** are pure utilities and shared data types.

---
## 2. Architecture & Dependencies

### 2.1 Naming Standards

**All code must follow the naming conventions in `docs/dev/naming.md`.**

Key rules:
- Services: `<Noun>Service` (e.g., `LibraryService`, `QueueService`)
- Service methods: `<verb>_<noun>` (e.g., `get_library`, `scan_library`, `pause_workers`)
- No transport prefixes (`api_`, `web_`, `cli_`)
- No meaningless suffixes (`_for_admin`, `_internal`)
- DTOs: `<Name>Result` or `<Name>DTO`

See the full document for allowed verbs, forbidden patterns, and refactoring examples.

### 2.2 High-Level Flow

For any non-trivial operation:

```text
interfaces  →  services  →  workflows  →  components  →  (persistence / helpers)
                                            ├─ analytics
                                            ├─ tagging
                                            └─ ml
```

### 2.3 Complexity & Clarity Guidelines

Each layer has clarity-focused guidelines to enforce separation of concerns. **Judge complexity by readability and logic density, not strict line counts.**

**See detailed layer-specific guidelines:**
- `nomarr/interfaces/INTERFACES.md` - Interface layer patterns
- `nomarr/services/SERVICES.md` - Service layer patterns
- `nomarr/workflows/WORKFLOWS.md` - Workflow layer patterns
- `nomarr/components/COMPONENTS.md` - Component layer patterns

**Quick Reference:**

- **`interfaces`**: **1 service call per route**
  - Pattern: `auth() → service.method() → ResponseModel.from_dto(dto)`
  - Only validate inputs, call service, serialize outputs
  - No business logic, no direct DB/ML/tagging calls
  - If you need > 1 service call → extract a service method that orchestrates them

- **`services`**: **DI + orchestration only**
  - Wire dependencies (config, db, queues, ML backends)
  - Call workflows with dependencies injected
  - Return DTOs
  - If a method has noticeable logic (loops, branching, multiple steps) → extract to workflow

- **`workflows`**: **Clear sequences of component calls**
  - One public method per workflow file
  - Unlimited calls to components and helpers (as long as they form a clear sequence)
  - If a workflow starts doing non-trivial computation itself → move that into a component
  - If a workflow becomes hard to read → split into smaller workflows or private workflow helpers
  - Judge by clarity, not line count

- **`components`**: **Heavy logic lives here**
  - Domain logic (ML inference, analytics, tagging rules)
  - If a function is unwieldy → break into `_private` helpers within the same file
  - If `_private` helpers are reused across multiple modules → centralize them in a single component module for that domain

### 2.4 Allowed Dependencies (Direction)

- `interfaces`:

  - Allowed: may import `nomarr.services`
  - Allowed: may import `nomarr.helpers`
  - Do not: import `nomarr.workflows`, `nomarr.components`, or `nomarr.persistence`

- `services`:

  - Allowed: may import `nomarr.workflows`
  - Allowed: may import `nomarr.persistence`
  - Allowed: may import `nomarr.components.*` (analytics, tagging, ml)
  - Allowed: may import `nomarr.helpers`
  - Do not: import `nomarr.interfaces`

- `workflows`:

  - Allowed: may import `nomarr.persistence`
  - Allowed: may import `nomarr.components.*` (analytics, tagging, ml)
  - Allowed: may import `nomarr.helpers`
  - Do not: import `nomarr.services` or `nomarr.interfaces`

- `components/*` (analytics, tagging, ml):

  - Allowed: may import `nomarr.persistence`
  - Allowed: may import `nomarr.helpers`
  - Allowed: may import other `nomarr.components.*` modules
  - Do not: import `nomarr.workflows`, `nomarr.services`, or `nomarr.interfaces`

- `persistence`:

  - Allowed: may import `nomarr.helpers`
  - Do not: import `nomarr.workflows`, `nomarr.components`, `nomarr.services`, or `nomarr.interfaces`

- `helpers`:

  - Do not: import any `nomarr.*` modules
  - Allowed: may import stdlib and third-party libraries only

Use this rule of thumb:

> Interfaces call **services**.
> Services own **wiring and long-lived resources** and call **workflows**.
> Workflows implement **use cases** and call **components** (analytics / tagging / ml).
> Components contain **heavy domain logic** and call **persistence / helpers**.
> Persistence & helpers never know about higher layers.

Import-linter enforces this; follow it rather than fighting it.

---

## 3. Directory Placement Rules (Where Code Should Live)

### Quick Decision Guide

When adding new code, ask:

- **Does it handle HTTP, CLI, or UI?** → `interfaces/`
- **Does it manage config, DB, queues, workers, or background jobs?** → `services/`
- **Does it implement a use case ("scan library", "process track", "recalibrate tags")?** → `workflows/`
- **Does it compute tag statistics, correlations, or co-occurrences?** → `components/analytics/`
- **Does it convert model outputs into tags, or aggregate/resolve tags?** → `components/tagging/`
- **Does it compute embeddings, heads, or apply ML models?** → `components/ml/`
- **Does it read/write DB tables or queues?** → `persistence/`
- **Is it a stateless utility or shared data type used in many layers?** → `helpers/`

### 3.1 `interfaces/` — API, CLI, and Web UI

Contains: `api/`, `cli/`, `web/`

- HTTP routes (FastAPI), CLI commands, web handlers
- Thin: validate inputs, call a service, serialize outputs
- Must not know about DB schema, ML details, or tagging rules

### 3.2 `services/` — Runtime Wiring & Long-Lived Resources

Contains: `*_service.py` files (e.g., `config_service.py`, `processing_service.py`, `queue_service.py`, `worker_service.py`)

- Own `ConfigService`, `Database` construction, queues, background workers
- Gather dependencies (config, db, ML backends, tag writers) and call workflows
- Should not contain complicated business rules; push logic to workflows

### 3.3 `workflows/` — Use Cases

Contains: workflow modules organized by domain (e.g., `processing/`, `library/`, `calibration/`, `queue/`, `navidrome/`)

- Implement operations like `process_file()`, `scan_library()`, `run_recalibration()`
- Accept all dependencies as parameters (no global config reading)
- Call components and persistence to perform work
- This is where most "interesting logic" lives

### 3.4 `components/` — Domain Logic

Contains: `analytics/`, `ml/`, `tagging/`

- **`analytics/`**: Compute tag statistics, correlations, co-occurrence analysis
- **`ml/`**: Model loading, embeddings, inference, calibration. Only `ml/backend_essentia.py` may import Essentia
- **`tagging/`**: Convert model outputs to tags, tiering, conflict resolution, aggregation

All components:
- Operate on data via persistence layer
- Must not import services, workflows, or interfaces

### 3.5 `persistence/` — Database & Queue Access

Contains: `db.py`, `queue.py`, `analytics_queries.py`, `database/` (with `*Operations` classes)

- `db.py` owns `Database` class (connection owner)
- `database/` contains one `*Operations` class per table or related group
- Each `*Operations` class owns all SQL for that table
- Access pattern: `db.queue.enqueue()`, `db.tags.get_track_tags()`, etc.
- External code must not import `persistence.database.*` directly

### 3.6 `helpers/` — Pure Utilities

Contains: `audio.py`, `files.py`, `dataclasses.py`, `logging.py`, `navidrome_templates.py`, etc.

- Pure utility functions (audio helpers, path helpers, file validation, etc.)
- `dataclasses.py` contains dataclasses used by multiple top-level packages
- Must not import any `nomarr.*` modules (only stdlib and third-party)
- No business logic; just reusable utilities

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

## 5. Data Transfer Objects (DTOs)

DTOs are the typed contracts for structured data flowing between layers.

### 5.1 DTO Requirements for Services

**Every public service method that returns non-trivial structured data must return a DTO.**

- **Trivial returns** (bool, int, str, None, list of primitives) do NOT require a DTO.
- **Private methods** (prefixed with `_`) do NOT require a DTO.
- **Structured data** (dicts with multiple fields, complex nested data) MUST use a DTO.

Examples:
```python
# ✅ Correct - trivial returns
def is_enabled(self) -> bool: ...
def get_count(self) -> int: ...
def get_job_id(self) -> str | None: ...

# ✅ Correct - private method
def _internal_helper(self) -> dict[str, Any]: ...

# ❌ Wrong - public method returning structured data without DTO
def get_job(self, job_id: int) -> dict[str, Any]: ...

# ✅ Correct - public method returns DTO
def get_job(self, job_id: int) -> JobDict | None: ...
```

### 5.2 DTO Placement Rules

**Single-service DTOs:**
- Used only within one service module
- Define at the top of the service file or in a nested `_models.py`
- Do not export to `services/__init__.py`

**Cross-layer DTOs:**
- Used by multiple services OR used by interfaces/workflows
- Must live in `helpers/dto/<domain>.py`
- Grouped by domain: `queue.py`, `config.py`, `analytics.py`, etc.
- Exported from `helpers/dto/__init__.py`

**Decision rule:**
```python
# If you see this pattern:
from nomarr.services.queue_service import QueueService
result = queue_service.get_job(job_id)
# And result is used in interfaces/workflows → DTO must be in helpers/dto/

# If DTO is only used internally within one service:
# Keep it local to that service file
```

### 5.3 Interface DTO Usage

**Interfaces must import and use DTOs directly, never treat service outputs as dicts.**

```python
# ❌ Wrong - treating DTO as dict
from nomarr.services import QueueService

def get_job_api(job_id: int, queue_service: QueueService = Depends(...)):
    result = queue_service.get_job(job_id)  # returns JobDict
    return {"id": result["id"], "status": result["status"]}  # treating as dict

# ✅ Correct - using DTO directly
from nomarr.helpers.dto.queue import JobDict
from nomarr.services import QueueService

def get_job_api(job_id: int, queue_service: QueueService = Depends(...)) -> JobDict | None:
    return queue_service.get_job(job_id)  # returns JobDict, passes through

# ✅ Also correct - transforming DTO to response model
from nomarr.helpers.dto.queue import JobDict
from nomarr.interfaces.api.models import JobResponse

def get_job_api(job_id: int, ...) -> JobResponse:
    job = queue_service.get_job(job_id)  # JobDict
    if not job:
        raise HTTPException(404)
    return JobResponse.from_dto(job)  # explicit transformation
```

**Why this matters:**
1. Type safety - mypy catches misuse
2. Detectability - tools can track cross-layer DTOs by imports
3. Explicitness - no hidden dict mutations
4. Refactorability - changing DTO fields shows all usage points

---

## 6. Essentia & ML Backends

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

## 7. Code Style & Quality

### 7.1 Python

- Fully type-annotated
- Follow `ruff` formatting and linting
- Follow ruff's import sorting: stdlib imports first, then third-party packages, then local `nomarr.*` imports. Do not merge unrelated imports into single lines.
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

### 6.3 Testing Guidelines

- Unit tests live in `tests/unit/` mirroring module structure.
- Integration tests live in `tests/integration/`.
- Prefer testing through public services or workflows rather than deep internals.
- Mock heavy dependencies (DB, Essentia, ML predictors, queues).
- Use pytest fixtures for DI patterns.

---

## 8. Tooling & QC

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

## 9. Development Scripts (`scripts/`)

The `scripts/` directory contains helpers that you (and Copilot) should use instead of guessing.

### 8.1 Purpose

Use these scripts to:

- discover real APIs instead of inventing functions
- enforce naming and structure conventions
- generate boilerplate in a consistent style
- identify complexity hotspots and refactor targets

When modifying or creating scripts, ensure they output ASCII-only text and support `--format=text` and `--format=json`.

### 8.2 Before Writing or Modifying Code

```bash
# Inspect real module APIs, attributes, and callables
python scripts/discover_api.py nomarr.workflows.processor
python scripts/discover_api.py nomarr.persistence.db

# Use JSON format for machine-readable output
python scripts/discover_api.py nomarr.ml.inference --format=json
```

> **Copilot rule:** Always use `discover_api.py` to verify APIs before calling them. Never guess function names, parameters, or return types.

Example text output:

```bash
python scripts/discover_api.py nomarr.ml.inference

================================================================================
Module: nomarr.ml.inference
================================================================================

FUNCTIONS:

  def compute_embeddings_for_backbone(backbone: 'str', emb_graph: 'str', target_sr: 'int', segment_s: 'float', hop_s: 'float', path: 'str', min_duration_s: 'int', allow_short: 'bool') -> 'tuple[np.ndarray, float]':
      Compute embeddings for an audio file using a specific backbo

  def make_head_only_predictor_batched(head_info: 'HeadInfo', embeddings_2d: 'np.ndarray', batch_size: 'int' = 11) -> 'Callable[[], np.ndarray]':
      Create a batched predictor that processes segments in fixed-

  def make_predictor_uncached(head_info: 'HeadInfo') -> 'Callable[[np.ndarray, int], np.ndarray]':
      Build full two-stage predictor (waveform -> embedding -> hea

CONSTANTS:

  HAVE_TF = True
  TYPE_CHECKING = False
```

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

## 10. Pre-Alpha Policy (Important)

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

## 11. Summary for Copilot

1. **Follow the layering:**
   `interfaces → services → workflows → (tagging / ml / persistence / helpers)`
   Never let lower layers import higher ones.

2. **Services own wiring and long-lived resources.**
   They construct config, DB, queues, workers, and call workflows.

3. **Workflows implement use cases.**
   They accept dependencies as parameters and call tagging/ml/persistence/helpers.

4. **Do not introduce migrations, legacy shims, or backward-compat code paths.**
   Pre-alpha means breaking changes are allowed.

5. **Use `discover_api.py` instead of guessing.**
   Never assume a function exists; check first.

Your job is to write code that respects this architecture, passes the existing tools, and does not invent new patterns unless explicitly asked.

---

End of instructions.
