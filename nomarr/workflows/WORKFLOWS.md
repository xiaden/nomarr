# Workflows Layer

This layer implements core use cases ("what Nomarr does").

## Purpose

Workflows are **use case implementations** that:
1. Accept dependencies as parameters (DB, config, ML backends)
2. Orchestrate components to perform work
3. Return DTOs

**Workflows contain the "story" of how Nomarr performs operations.**

---

## WORKFLOW NAMING & STRUCTURE

### 1. File naming

- One main workflow per file.
- File name: `verb_object_wf.py`
  
  Examples:
  - `scan_library_wf.py`
  - `tag_audio_file_wf.py`
  - `enqueue_files_wf.py`
  - `generate_calibration_wf.py`
  - `recalibrate_file_wf.py`

### 2. Function naming

- Primary entrypoint: `verb_object_workflow(...)`
- Everything else in the module is:
  - a private helper (`_something_internal`), or
  - a very closely related variant.

### 3. Size / complexity

- Soft limit: ~300–400 LOC per workflow module.
- If the file has multiple exported workflows that are different user stories,
  split into multiple files.
- Exceptions: "analytics-style" modules can group a few related
  read-only workflows (e.g. analytics.py) as long as they stay cohesive.

### 4. Layering rules

- Workflows NEVER import services or nomarr.app.
- Workflows NEVER import Pydantic models.
- Workflows CAN import persistence, components, and helpers.

---

## Complexity Guidelines

### Rule: Clear Sequences of Component Calls

Workflows should read like a **recipe**:
1. Do step 1 (call component)
2. Do step 2 (call component)
3. Do step 3 (call component)
4. Return result

**Judge by clarity, not line count. Allow lots of component calls as long as they form a clear sequence.**

```python
# ✅ Good - clear sequence, easy to read
def process_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str,
) -> ProcessFileResult:
    # Load file from DB
    file_record = load_file_from_db(db, file_path)
    
    # Compute embeddings for all backbones
    embeddings = compute_all_embeddings(file_path, models_dir)
    
    # Run inference for each head
    predictions = run_inference_for_heads(embeddings, models_dir)
    
    # Convert predictions to tags
    tags = predictions_to_tags(predictions, namespace)
    
    # Write tags to Navidrome
    write_tags_to_navidrome(db, file_record.id, tags)
    
    # Return result DTO
    return ProcessFileResult(
        file=file_path,
        tags_written=len(tags),
        # ...
    )
```

### When to Extract

**Extract to a component if:**
- The workflow is doing non-trivial computation itself
- There's complex branching logic embedded in the workflow
- The workflow becomes hard to read as a sequence

**Split into smaller workflows or private helpers if:**
- The workflow becomes hard to read
- You have large, reusable sub-sequences

```python
# Before - hard to read
def complex_workflow(db: Database, ...) -> Result:
    # 50 lines of file discovery
    # 50 lines of validation
    # 50 lines of processing
    # 50 lines of cleanup

# After - split with private helpers
def complex_workflow(db: Database, ...) -> Result:
    discovered = _discover_and_validate(db, ...)
    processed = _process_files(db, discovered, ...)
    _cleanup_orphans(db, ...)
    return Result(...)

def _discover_and_validate(db: Database, ...) -> list[str]:
    # 50 lines of clear logic
    ...
```

## Patterns

### Accept All Dependencies as Parameters

Workflows receive everything via parameters:

```python
# ✅ Good - dependencies injected
def process_file_workflow(
    db: Database,
    file_path: str,
    models_dir: str,
    namespace: str,
) -> ProcessFileResult:
    ...

# ❌ Bad - reading config at runtime
def process_file_workflow(file_path: str) -> ProcessFileResult:
    from nomarr.config import db, models_dir  # ← No globals
    ...
```

### Return DTOs

Workflows always return typed DTOs:

```python
# ✅ Good
def process_file_workflow(...) -> ProcessFileResult:
    return ProcessFileResult(
        file=file_path,
        elapsed=elapsed,
        tags_written=len(tags),
    )

# ❌ Bad - returning dict
def process_file_workflow(...) -> dict[str, Any]:
    return {"file": file_path, "elapsed": elapsed}
```

## Allowed Imports

```python
# ✅ Workflows can import:
from nomarr.persistence import Database
from nomarr.components.ml import compute_embeddings
from nomarr.components.tagging import predictions_to_tags
from nomarr.helpers.dto import ProcessFileResult

# ❌ Workflows must NOT import:
from nomarr.services import ProcessingService  # ← No service imports
from nomarr.interfaces.api import router  # ← No interface imports
from pydantic import BaseModel  # ← No Pydantic
```

## Anti-Patterns

### ❌ Complex Computation in Workflows
```python
# NEVER do this
def process_file_workflow(db: Database, file_path: str) -> ProcessFileResult:
    # ❌ Implementing ML inference here
    audio = librosa.load(file_path)
    features = librosa.feature.mfcc(audio)
    predictions = model.predict(features)
    # This should be: predictions = run_inference(file_path, models_dir)
```

### ❌ Importing Services
```python
# NEVER do this
from nomarr.services import ProcessingService

def workflow(db: Database) -> Result:
    service = ProcessingService(db)  # ← Workflows don't call services
    return service.process_file(...)
```

## Summary

**Workflows are recipes:**
- Accept dependencies as parameters (DB, config, backends)
- Orchestrate components to perform work
- Return DTOs
- One public method per file
- Judge by clarity, not line count
- No complex computation - delegate to components

- Soft limit: ~300–400 LOC per workflow module.
- If the file has multiple exported workflows that are different user stories,
  split into multiple files.
- Exceptions: "analytics-style" modules can group a few related
  read-only workflows (e.g. analytics.py) as long as they stay cohesive.

### 4. Layering rules

- Workflows NEVER import services or nomarr.app.
   - Workflows may import:
     - nomarr.ml.\*
     - nomarr.tagging.\*
     - nomarr.persistence.\*
     - nomarr.helpers.\*
   - Services call workflows; interfaces call services.
