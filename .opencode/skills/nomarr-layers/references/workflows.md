# Workflows Layer

**Purpose:** Implement core use cases ("what Nomarr does").

Workflows contain the **story** of how Nomarr performs operations. They are recipes that:
1. Accept dependencies as parameters (DB, config, ML backends)
2. Orchestrate components to perform work
3. Return DTOs

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.workflows.library.sync_file_to_library_wf import sync_file_to_library  # Workflows can call other workflows
from nomarr.persistence.db import Database  # public intent facade, thin single-intent calls
from nomarr.components.ml import compute_embeddings, run_inference
from nomarr.components.tagging import predictions_to_tags
from nomarr.helpers.dto import ProcessFileResult
```

Workflows may import and call other workflows. This is lateral (same-layer) composition, not an upward dependency.

## Forbidden Imports

```python
# ❌ NEVER import these in workflows
from nomarr.services import ...                # Workflows don't call services
from nomarr.interfaces import ...              # No interface imports
from pydantic import BaseModel                 # No Pydantic
```

---

## Persistence Rule

Workflows may call the public `Database` intent facade for **thin, single-atomic-intent operations** — one facade method on `db.library`, `db.app`, or `db.ml` (or a public nested sub-facade the facade exposes), through the injected `Database` instance.

```python
# ✅ Allowed — one thin single-intent facade call
assignments = db.library.list_tags_for_song(song_identity)

# ❌ Not allowed — reconstructing an intent by sequencing multiple facade calls
#    (business logic / multi-call choreography belongs in a component)
identity = db.library.resolve_song_identity(song_id)
first = db.library.list_songs(...)
second = ...  # more facade calls chained to rebuild a multi-step intent
```

A workflow facade call must be thin: it must not sequence lower-level calls, implement business rules or state-machine transitions, manage collection-level writes, or perform multi-call persistence choreography. Side-effectful reads (e.g. hydration) are treated as commands for review. Such behavior belongs in a component or an intent-complete facade method.

Workflows receive `Database` as a parameter for DI pass-through to components and for these thin direct facade calls. Import `Database` from `nomarr.persistence.db`; never import persistence implementation internals (repositories, SQL primitives, mappers, models, `nomarr.persistence.api` implementation modules) or open raw sessions/transactions.

---

## File & Function Naming

- **File:** `verb_object_wf.py` (e.g., `scan_library_quick_wf.py`, `process_file_wf.py`)
- **Function:** `verb_object_workflow(...)` as the single exported function
- **One public workflow per file**
- **No private helper functions.** The recipe is the workflow function body.
- **No common/shared/base modules** (`_common.py`, `_base.py`, `_shared.py`) within workflows.

---

## The Recipe Rule

A workflow file contains **one function** whose body reads like a **recipe** — a flat sequence of component calls with step comments:

```python
def process_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str,
) -> ProcessFileResult:
    # Step 1: Load file
    file_record = load_file_from_db(db, file_path)

    # Step 2: Compute embeddings
    embeddings = compute_all_embeddings(file_path, models_dir)

    # Step 3: Run inference
    predictions = run_inference_for_heads(embeddings, models_dir)

    # Step 4: Convert to tags
    tags = predictions_to_tags(predictions, namespace)

    # Step 5: Write tags
    write_tags_to_db(db, file_record.id, tags)

    return ProcessFileResult(file=file_path, tags_written=len(tags))
```

**Judge by clarity, not line count.** Many component calls are fine if they form a clear sequence. The point is: someone reading the workflow can see what it does without jumping to another file or scrolling past helper definitions.

### Why no private helpers?

Private helpers (`_do_step_3(...)`) hide the recipe. When you extract steps into helpers within the same file, the workflow function becomes a table of contents — not a recipe. When you extract them into `_common.py`, you get a monolith behind a delegate.

**If part of a workflow is complex enough to extract, it belongs in a component, not a private helper.** Components are testable, discoverable, and reusable. Private helpers are hidden, untestable, and create indirection without benefit.

### What about duplication between workflows?

Two workflows that share most of their steps should:
1. **Call the same components.** The shared logic lives in components.
2. **Duplicate the recipe skeleton.** The step-by-step sequence is cheap to duplicate (it's just component calls with comments). The *implementation* isn't duplicated because it lives in the components.
3. **Call one workflow from another** if one is a strict superset.

---

## Accept All Dependencies as Parameters

Workflows receive everything via parameters — no global config reading:

```python
# ✅ Good - dependencies injected
def process_file_workflow(db: Database, file_path: str, models_dir: str) -> ProcessFileResult:
    ...

# ❌ Bad - reading globals
def process_file_workflow(file_path: str) -> ProcessFileResult:
    from nomarr.config import db, models_dir  # NO GLOBALS
    ...
```

---

## When to Extract to a Component

If your workflow is doing non-trivial work inline, that work belongs in a component:
- Complex branching logic or data transformations
- Heavy domain math / ML / statistics
- Set operations, graph traversal, or multi-step DB queries
- Anything you'd want to unit test in isolation

**The workflow calls the component. The component does the work.**

---

## Size Guidelines

- **Consider splitting** at 300 LOC — review whether multiple user stories are coexisting
- **MUST split** at 500 LOC — no exceptions; split by user story

A workflow function body over ~150 lines almost always contains logic that belongs in components.

---

## Validation

- Does this file import from services or interfaces? **→ Violation**
- Does this file import Pydantic? **→ Violation**
- Does this workflow read global config? **→ Accept as parameter instead**
- Is the workflow doing heavy computation? **→ Extract to component**
- Does the function return a DTO? **→ Required**
- Is there one public workflow per file? **→ Required**
- Does the file name end in `_wf.py`? **→ Convention**
- Are there private helper functions? **→ Extract to components**
- Is there a `_common.py` or `_shared.py`? **→ Move logic to components**
- Can someone read the workflow and understand the full story? **→ Required**
- **Run `lint_project_backend(path="nomarr/workflows")` after every edit.** Zero errors is the only acceptable state.
