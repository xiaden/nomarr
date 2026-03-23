# Helpers Layer

The **helpers layer** contains pure utilities and shared data types used across all other layers. Helpers are the foundation of the codebase: stateless, reusable, and completely isolated from business logic.

They are:

- **Pure utility functions** (no side effects, no I/O)
- **Data Transfer Objects (DTOs)** (cross-layer contracts)
- **Shared exceptions** (custom error types)

> **Rule:** Helpers know nothing about Nomarr. They could be extracted into a standalone utility library tomorrow. They **must not import** any `nomarr.*` modules.

---

## 1. Position in the Architecture

```
interfaces → services → workflows → components → (persistence / helpers)
```

Helpers sit at the **bottom** of the dependency chain. Every layer above may import helpers, but helpers never import upward.

---

## 2. Directory Structure

```text
helpers/
├── config_schema.py              # Configuration schema definitions
├── dataclasses.py                # Shared dataclasses
├── exceptions.py                 # Custom exception types
├── file_validation_helper.py     # Audio file validation utilities
├── files_helper.py               # File path utilities
├── logging_helper.py             # Logging utilities and filters
├── tag_key_mapping.py            # Tag key ↔ display name mapping
├── time_helper.py                # Time/timestamp conversions
├── vector_params_helper.py       # Vector dimension/parameter utilities
└── dto/                          # Data Transfer Objects
    ├── admin_dto.py              # Admin/management DTOs
    ├── analytics_dto.py          # Analytics domain DTOs
    ├── calibration_dto.py        # Calibration DTOs
    ├── config_dto.py             # Configuration DTOs
    ├── health_dto.py             # Health monitoring DTOs
    ├── info_dto.py               # System information DTOs
    ├── library_dto.py            # Library domain DTOs
    ├── metadata_dto.py           # Metadata DTOs
    ├── ml_dto.py                 # ML pipeline DTOs
    ├── ml_edge_dto.py            # ML edge/boundary DTOs
    ├── navidrome_dto.py          # Navidrome integration DTOs
    ├── path_dto.py               # Path resolution DTOs
    ├── playlist_import_dto.py    # Playlist import DTOs
    ├── processing_dto.py         # Processing pipeline DTOs
    ├── recalibration_dto.py      # Recalibration DTOs
    ├── tagging_dto.py            # Tagging pipeline DTOs
    ├── tags_dto.py               # Tag data DTOs
    └── vector_config_dto.py      # Vector configuration DTOs
```

**Naming rules:**

- Modules: `snake_case_helper.py` by domain (e.g., `files_helper.py`, `time_helper.py`).
- Functions: clear verb–noun names (`validate_file_exists`, `compute_normalized_path`, `now_ms`).
- DTOs: `domain_dto.py` (e.g., `analytics_dto.py`, `library_dto.py`).

---

## 3. What Belongs in Helpers

### 3.1 Pure Utility Functions

Functions that:
- Have no side effects
- Don't perform I/O
- Don't access databases or networks
- Are deterministic (same input → same output)

**Examples:** path validation, time/date conversions, string formatting, math calculations.

**Anti-patterns:** reading files, making HTTP requests, querying databases, containing business rules.

### 3.2 Data Transfer Objects (DTOs)

**Purpose:** Type-safe contracts for data flowing between layers.

**Rules:**
1. Pure dataclasses (no methods beyond `__init__`)
2. Only stdlib and typing imports
3. No business logic, no validation

**Placement decision tree:**
- **Cross-layer DTOs** (used by multiple services or workflows): must live in `helpers/dto/<domain>.py`
- **Single-service DTOs** (only used within one service file): keep local to that service

### 3.3 Shared Exceptions

Custom exception types used across multiple layers. Inherit from appropriate base exception, no business logic.

```python
class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid."""
    pass
```

---

## 4. Rules

### Keep It Simple

- Small, focused functions (< 30 lines typical)
- Minimal branching, easy to test
- If a helper has complex logic, it probably belongs in a component

### No Hidden Dependencies

- All inputs via parameters
- No global state, no environment variables, no config file reads

### Stateless

- Same input → same output
- No side effects, no mutation of input parameters
- Exception: transparent caching that doesn't affect behavior

### Import Rules

**Allowed:**
- ✅ Standard library (`os`, `pathlib`, `datetime`, `json`, etc.)
- ✅ Typing (`typing`, `typing_extensions`)
- ✅ Third-party libraries (`mutagen`, `numpy`, etc.)

**Forbidden:**
- ❌ Any `nomarr.*` modules
- ❌ Any imports that would create circular dependencies

---

## 5. Common Patterns

### Path Utilities

```python
def validate_file_exists(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
```

### Time Utilities

```python
def now_ms() -> Milliseconds:
    """Get current UTC time in milliseconds."""
    return Milliseconds(int(time.time() * 1000))
```

### DTOs

```python
@dataclass
class LibraryDict:
    """Library representation for API responses."""
    id: str
    name: str
    root_path: str
    file_count: int
    tagged_count: int
```

---

## 6. Anti-Patterns

| Anti-Pattern | Why It's Wrong | Fix |
|---|---|---|
| Business logic in helpers | Contains rules, reads config | Move to component or workflow |
| Hidden I/O (`load_config_file()`) | Not pure, hidden dependency | Pass as parameter or move to service |
| Mutable global state (`_cache = {}`) | Side effects between calls | Use cache decorator or pass cache object |
| Importing `nomarr.*` | Violates layer boundary | Keep helpers self-contained |
