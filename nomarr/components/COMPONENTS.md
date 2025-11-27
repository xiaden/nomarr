# Components Layer

This layer contains heavy, domain-specific logic (analytics, tagging, ML).

## Purpose

Components are **domain logic modules** that:
1. Implement complex computations
2. Operate on data via persistence layer
3. Provide reusable building blocks for workflows

**Heavy business logic lives here.**

## Structure

```
components/
├── analytics/
│   ├── tag_statistics.py
│   ├── correlations.py
│   └── co_occurrence.py
├── ml/
│   ├── embeddings.py
│   ├── inference.py
│   ├── calibration.py
│   └── backend_essentia.py
└── tagging/
    ├── predictions_to_tags.py
    ├── mood_aggregation.py
    └── tag_resolution.py
```

## Complexity Guidelines

### Rule: Heavy Logic Lives Here

Components contain the **actual computational work**:
- ML inference and embeddings
- Statistical analysis
- Tag aggregation and resolution
- Complex data transformations

**If a function is unwieldy, break into `_private` helpers within the same file.**

```python
# ✅ Good - clear, focused component
def compute_embeddings(
    file_path: str,
    models_dir: str,
    backbone: str,
) -> np.ndarray:
    """Compute embeddings for an audio file."""
    audio = _load_audio(file_path)
    segments = _segment_audio(audio)
    model = _load_model(models_dir, backbone)
    
    embeddings = []
    for segment in segments:
        emb = model.predict(segment)
        embeddings.append(emb)
    
    return np.array(embeddings)

def _load_audio(file_path: str) -> np.ndarray:
    """Private helper - loads audio."""
    ...

def _segment_audio(audio: np.ndarray) -> list[np.ndarray]:
    """Private helper - segments audio."""
    ...

def _load_model(models_dir: str, backbone: str) -> Model:
    """Private helper - loads ML model."""
    ...
```

### When to Extract Private Helpers

**Create `_private` helpers when:**
- A function exceeds ~80 LOC
- There's repeated logic within the module
- The function has distinct, extractable steps

```python
# Before - unwieldy function
def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    # 40 lines of querying
    rows = db.execute(complex_query)
    
    # 40 lines of aggregation
    stats = {}
    for row in rows:
        # complex aggregation logic
    
    # 40 lines of formatting
    formatted = {}
    for key, value in stats.items():
        # complex formatting logic
    
    return TagStats(formatted)

# After - extracted helpers
def compute_tag_statistics(db: Database, library_id: int) -> TagStats:
    rows = _query_tag_data(db, library_id)
    stats = _aggregate_tag_stats(rows)
    formatted = _format_tag_stats(stats)
    return TagStats(formatted)

def _query_tag_data(db: Database, library_id: int) -> list[dict]:
    """Private helper - queries tag data."""
    # 40 lines of querying
    ...

def _aggregate_tag_stats(rows: list[dict]) -> dict[str, int]:
    """Private helper - aggregates statistics."""
    # 40 lines of aggregation
    ...

def _format_tag_stats(stats: dict[str, int]) -> dict[str, Any]:
    """Private helper - formats for output."""
    # 40 lines of formatting
    ...
```

### When to Centralize Helpers

**If `_private` helpers are reused across multiple modules:**

Consider centralizing them in a single component module for that domain.

```python
# Before - _load_model duplicated in 3 files
# components/ml/embeddings.py
def _load_model(models_dir: str, backbone: str) -> Model: ...

# components/ml/inference.py
def _load_model(models_dir: str, backbone: str) -> Model: ...

# components/ml/calibration.py
def _load_model(models_dir: str, backbone: str) -> Model: ...

# After - centralized in model_loading.py
# components/ml/model_loading.py
def load_model(models_dir: str, backbone: str) -> Model:
    """Public helper - loads ML model (used by multiple modules)."""
    ...

# Now other modules import it
from nomarr.components.ml.model_loading import load_model
```

## Patterns

### Pure Functions Where Possible

Components should be **stateless** when possible:

```python
# ✅ Good - pure function
def predictions_to_tags(
    predictions: dict[str, np.ndarray],
    namespace: str,
    threshold: float = 0.5,
) -> list[Tag]:
    """Convert model predictions to tags."""
    tags = []
    for head_name, scores in predictions.items():
        for idx, score in enumerate(scores):
            if score >= threshold:
                tags.append(Tag(
                    namespace=namespace,
                    head=head_name,
                    value=idx,
                    score=score,
                ))
    return tags

# ❌ Bad - stateful component
class TagConverter:
    def __init__(self):
        self.tags = []
    
    def convert(self, predictions: dict) -> None:
        # Mutates internal state
        self.tags.extend(...)
```

### Database Access via Persistence

Components query/write via the persistence layer:

```python
# ✅ Good - using persistence layer
def compute_tag_frequencies(db: Database, library_id: int) -> dict[str, int]:
    tags = db.tags.get_library_tags(library_id)
    frequencies = {}
    for tag in tags:
        frequencies[tag.name] = frequencies.get(tag.name, 0) + 1
    return frequencies

# ❌ Bad - raw SQL in component
def compute_tag_frequencies(db: Database, library_id: int) -> dict[str, int]:
    rows = db.execute_raw("SELECT tag, COUNT(*) FROM tags WHERE ...")  # ← Use persistence
    ...
```

### Return Simple Types or DTOs

Components return:
- Simple types (int, str, list, dict, np.ndarray)
- DTOs (dataclasses from `helpers/dto/`)
- Domain objects (Tag, Prediction, etc.)

```python
# ✅ Good - returns DTO
def compute_embeddings(...) -> np.ndarray:
    ...

def run_inference(...) -> InferenceResult:  # DTO
    ...

# ❌ Bad - returns Pydantic
from pydantic import BaseModel

def compute_embeddings(...) -> BaseModel:  # ← No Pydantic in components
    ...
```

## Domain-Specific Guidelines

### Analytics Components

```python
# Analytics components compute statistics and relationships
def compute_tag_correlations(
    db: Database,
    library_id: int,
    min_co_occurrence: int = 10,
) -> dict[tuple[str, str], float]:
    """Compute correlation coefficients between tags."""
    co_occurrences = _query_co_occurrences(db, library_id)
    correlations = _compute_pearson_correlations(co_occurrences)
    return _filter_by_threshold(correlations, min_co_occurrence)
```

### ML Components

```python
# ML components handle model loading, embeddings, inference
def run_inference_for_head(
    embeddings: np.ndarray,
    head_path: str,
) -> np.ndarray:
    """Run inference for a single head model."""
    model = _load_head_model(head_path)
    predictions = model.predict(embeddings)
    return _apply_softmax(predictions)
```

### Tagging Components

```python
# Tagging components convert predictions to tags, resolve conflicts
def aggregate_mood_tags(
    tags: list[Tag],
    mood_mapping: dict[str, str],
) -> dict[str, float]:
    """Aggregate mood tags by category."""
    mood_scores = {}
    for tag in tags:
        if tag.head in mood_mapping:
            mood_category = mood_mapping[tag.head]
            mood_scores[mood_category] = max(
                mood_scores.get(mood_category, 0.0),
                tag.score,
            )
    return mood_scores
```

## Allowed Imports

```python
# ✅ Components can import:
from nomarr.persistence import Database
from nomarr.helpers.dto import ProcessFileResult
from nomarr.helpers.files_helper import discover_audio_files
from nomarr.components.ml import load_model  # Cross-component imports OK

# ❌ Components must NOT import:
from nomarr.workflows import process_file_workflow  # ← No workflow imports
from nomarr.services import ProcessingService  # ← No service imports
from nomarr.interfaces.api import router  # ← No interface imports
from pydantic import BaseModel  # ← No Pydantic
```

## Anti-Patterns

### ❌ Importing Workflows/Services
```python
# NEVER do this
from nomarr.services import ProcessingService

def compute_embeddings(...):
    service = ProcessingService(...)  # ← Components don't call services
```

### ❌ Pydantic in Components
```python
# NEVER do this
from pydantic import BaseModel

class EmbeddingResult(BaseModel):  # ← Use dataclasses, not Pydantic
    embeddings: list[float]
```

### ❌ Global State
```python
# NEVER do this
_MODEL_CACHE = {}  # ← No module-level mutable state

def load_model(path: str):
    if path not in _MODEL_CACHE:
        _MODEL_CACHE[path] = ...
```

### ❌ Reading Config at Runtime
```python
# NEVER do this
def compute_embeddings(file_path: str):
    import os
    models_dir = os.getenv("MODELS_DIR")  # ← Pass as parameter
    ...
```

## Summary

**Components are workhorses:**
- Heavy domain logic lives here
- Stateless, pure functions when possible
- Access DB via persistence layer
- Use `_private` helpers for unwieldy functions
- Centralize reused helpers in domain modules
- No Pydantic, no workflow/service imports
