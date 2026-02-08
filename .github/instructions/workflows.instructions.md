---
name: Workflows Layer
description: Auto-applied when working with nomarr/workflows/ - Use case implementation
applyTo: nomarr/workflows/**
---

# Workflows Layer

**Purpose:** Implement core use cases ("what Nomarr does").

Workflows contain the **story** of how Nomarr performs operations. They are recipes that:
1. Accept dependencies as parameters (DB, config, ML backends)
2. Orchestrate [components](./components.instructions.md) to perform work
3. Return [DTOs](./helpers.instructions.md)

---

## Allowed Imports

```python
# ✅ Allowed
from nomarr.workflows.library.sync_file_to_library_wf import sync_file_to_library  # Workflows can call other workflows
from nomarr.persistence import Database
from nomarr.components.ml import compute_embeddings, run_inference
from nomarr.components.tagging import predictions_to_tags
from nomarr.helpers.dto import ProcessFileResult
```

> **Workflows may import and call other workflows.** This is lateral (same-layer) composition,
> not an upward dependency. Use this to reuse orchestration logic without duplicating it.

## Forbidden Imports

```python
# ❌ NEVER import these in workflows
from nomarr.services import ProcessingService  # Workflows don't call services
from nomarr.interfaces import ...              # No interface imports
from pydantic import BaseModel                 # No Pydantic
```

---

## MCP Server Tools

**Use the Nomarr MCP server to navigate this layer efficiently:**

- `read_module_api(module_name)` - See workflow signatures before reading full files
- `locate_module_symbol(symbol_name)` - Find where workflows are defined
- `read_module_source(qualified_name)` - Get exact workflow source with line numbers
- `trace_module_calls(function)` - Follow call chains from workflows to components

**Before modifying workflows, run `read_module_api` to understand dependencies and return types.**

---

## File & Function Naming

- **File:** `verb_object_wf.py` (e.g., `scan_library_quick_wf.py`, `process_file_wf.py`)
- **Function:** `verb_object_workflow(...)` as the single exported function
- **One public workflow per file**
- **No private helper functions.** The recipe is the workflow function body.
- **No common/shared/base modules** (`_common.py`, `_base.py`, `_shared.py`) within workflows.

---

## The Recipe Rule

A workflow file contains **one function** whose body reads like a **recipe** — a flat
sequence of component calls with step comments:

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

**Judge by clarity, not line count.** Many component calls are fine if they form a clear
sequence. The point is: someone reading the workflow can see what it does without
jumping to another file or scrolling past helper definitions.

### Why no private helpers?

Private helpers (`_do_step_3(...)`) hide the recipe. When you extract steps into helpers
within the same file, the workflow function becomes a table of contents — not a recipe.
When you extract them into `_common.py`, you get a monolith behind a delegate.

**If part of a workflow is complex enough to extract, it belongs in a component, not a
private helper.** Components are testable, discoverable, and reusable. Private helpers
are hidden, untestable, and create indirection without benefit.

### What about duplication between workflows?

Two workflows that share most of their steps (e.g., quick scan vs. full scan) should:

1. **Call the same components.** The shared logic lives in components, not in shared
   workflow modules.
2. **Duplicate the recipe skeleton.** The step-by-step sequence is cheap to duplicate
   (it's just component calls with comments). The *implementation* isn't duplicated
   because it lives in the components.
3. **Call one workflow from another** if one is a strict superset. E.g., `full_scan`
   calls `quick_scan` and then does additional work.

```python
# ✅ Good: Two workflows calling different components, clear recipe in each
def scan_library_quick_workflow(db, library_id, tagger_version):
    # Step 1: Resolve library
    library = db.libraries.get_library(library_id)
    # Step 2: Discover folders, plan incremental scan (cache-aware)
    all_folders = discover_library_folders(library_root, [library_root])
    folder_plan = plan_incremental_scan(all_folders, cached_folders)
    # Step 3: Scan changed folders
    ...

def scan_library_full_workflow(db, library_id, tagger_version):
    # Step 1: Resolve library
    library = db.libraries.get_library(library_id)
    # Step 2: Discover folders, plan full scan (no cache)
    all_folders = discover_library_folders(library_root, [library_root])
    folder_plan = plan_full_scan(all_folders)
    # Step 3: Scan all folders
    ...

# ❌ Bad: Workflows delegating to a shared private function with a boolean toggle
def scan_library_quick_workflow(db, library_id, tagger_version):
    return _execute_scan(db, library_id, tagger_version, full=False)

def scan_library_full_workflow(db, library_id, tagger_version):
    return _execute_scan(db, library_id, tagger_version, full=True)

# ❌ Bad: Shared module hiding the recipe behind a boolean
from ._scan_common import _execute_scan
def scan_library_quick_workflow(db, library_id, tagger_version):
    return _execute_scan(db, library_id, tagger_version, full=False)
```

---

## Accept All Dependencies as Parameters

Workflows receive everything via parameters — no global config reading:

```python
# ✅ Good - dependencies injected
def process_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
) -> ProcessFileResult:
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

If you find yourself writing a private helper in a workflow, stop and ask:
"Should this be a component?" The answer is almost always yes.

---

## Size Guidelines

- Soft limit: ~300–400 LOC per workflow module
- If multiple exported workflows with different user stories → split files
- Exception: analytics-style modules can group related read-only workflows
- A workflow function body over ~150 lines likely contains logic that should
  be in components

---

## Validation Checklist

Before committing workflow code, verify:

- [ ] Does this file import from services or interfaces? **→ Violation**
- [ ] Does this file import Pydantic? **→ Violation**
- [ ] Does this workflow read global config? **→ Accept as parameter instead**
- [ ] Is the workflow doing heavy computation? **→ Extract to component**
- [ ] Does the function return a DTO? **→ Required**
- [ ] Is there one public workflow per file? **→ Required**
- [ ] Does the file name end in `_wf.py`? **→ Convention**
- [ ] Are there private helper functions? **→ Extract to components**
- [ ] Is there a `_common.py` or `_shared.py`? **→ Move logic to components**
- [ ] Can someone read the workflow and understand the full story? **→ Required**
- [ ] **Does `lint_project_backend(path="nomarr/workflows")` pass with zero errors?** **→ MANDATORY**
