# Helpers Layer

The **helpers layer** contains pure utilities and shared data types used across all other layers. Helpers are the foundation of the codebase: stateless, reusable, and completely isolated from business logic.

They are:

- **Pure utility functions** (no side effects, no I/O)
- **Data Transfer Objects (DTOs)** (cross-layer contracts)
- **Shared exceptions** (custom error types)

> **Rule:** Helpers know nothing about Nomarr. They could be extracted into a standalone utility library tomorrow.

---

## 1. Position in the Architecture

Layers:

- **Interfaces** – HTTP/CLI/SSE, Pydantic, auth, HTTP status codes
- **Services** – dependency wiring, thin orchestration, DTO boundaries
- **Workflows** – domain flows, multi-step operations, control logic
- **Components** – heavy computations, analytics, ML, tagging
- **Persistence** – DB access, AQL queries
- **Helpers** – stateless utilities, DTOs, exceptions

Helpers sit at the **bottom** of the architecture and **must not import** any `nomarr.*` modules.

---

## 2. Directory Structure & Naming

Helpers live under `nomarr/helpers/`:

```text
helpers/
├── dataclasses.py              # Shared dataclasses (currently empty)
├── exceptions.py               # Custom exception types
├── file_validation_helper.py   # Audio file validation utilities
├── files_helper.py             # File path utilities
├── logging_helper.py           # Logging utilities and filters
├── sql_helper.py               # SQL fragment builders
├── time_helper.py              # Time/timestamp conversions
└── dto/                        # Data Transfer Objects
    ├── analytics_dto.py        # Analytics domain DTOs
    ├── config_dto.py           # Configuration DTOs
    ├── health_dto.py           # Health monitoring DTOs
    ├── info_dto.py             # System information DTOs
    ├── library_dto.py          # Library domain DTOs
    ├── processing_dto.py       # Processing pipeline DTOs
    └── queue_dto.py            # Queue domain DTOs
```

Naming rules:

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

**Examples:**
- Path validation and normalization
- SQL fragment building
- Time/date conversions
- String formatting
- Math calculations

**Anti-patterns:**
- Reading files
- Making HTTP requests
- Querying databases
- Containing business rules

### 3.2 Data Transfer Objects (DTOs)

**Purpose:** Type-safe contracts for data flowing between layers.

**Rules:**
1. Pure dataclasses (no methods beyond `__init__`)
2. Only stdlib and typing imports
3. No business logic
4. No validation (validation happens at service layer)

**Placement:**
- **Single-service DTOs:** Define at top of service file (not exported to `helpers/dto/`)
- **Cross-layer DTOs:** Must live in `helpers/dto/<domain>.py`

**Decision tree:**
```python
# If used by multiple services OR used by interfaces/workflows:
from nomarr.helpers.dto.library import LibraryDict

# If only used within one service file:
# Keep it local to that service (don't export to helpers/dto/)
```

**DTO Requirements for Services:**

Every public service method that returns non-trivial structured data must return a DTO.

- **Trivial returns** (bool, int, str, None, list of primitives) do NOT require a DTO.
- **Private methods** (prefixed with `_`) do NOT require a DTO.
- **Structured data** (dicts with multiple fields, complex nested data) MUST use a DTO.

### 3.3 Shared Exceptions

Custom exception types used across multiple layers.

**Rules:**
- Inherit from appropriate base exception
- No business logic in exceptions
- Clear, descriptive names
- Include helpful error messages

**Example:**
```python
class PlaylistQueryError(Exception):
    """Raised when a smart playlist query is invalid."""
    pass
```

### 3.4 Shared Dataclasses (Rare)

**Purpose:** Dataclasses used by multiple top-level packages.

**Current status:** `dataclasses.py` is currently empty. Most dataclasses should live in `dto/` instead.

**Use only when:**
- Truly shared across multiple top-level packages
- Not a DTO (doesn't cross layer boundaries)
- Can't be placed in a more specific location

---

## 4. Complexity Guidelines

### Rule: Keep It Simple

Helpers should be **trivially correct**:
- Small, focused functions (< 30 lines typical)
- Minimal branching
- Easy to test
- Easy to understand

If a helper function has complex logic, it probably belongs in a component instead.

### Rule: No Hidden Dependencies

Every helper function must be **self-contained**:
- All inputs via parameters
- No global state
- No environment variables
- No config file reads

### Rule: Stateless

Helpers must be **pure functions**:
- Same input → same output
- No side effects
- No mutation of input parameters
- No I/O operations

**Exception:** Caching is acceptable if it's transparent and doesn't affect behavior.

---

## 5. Import Rules

### Allowed Imports:
- ✅ Standard library (`os`, `pathlib`, `datetime`, `json`, etc.)
- ✅ Typing (`typing`, `typing_extensions`)
- ✅ Third-party libraries (`mutagen`, `numpy`, etc.)

### Forbidden Imports:
- ❌ Any `nomarr.*` modules
- ❌ Any imports that would create circular dependencies

**Rationale:** Helpers are the foundation. They can't depend on anything above them.

---

## 6. Testing Helpers

Helpers should be **easy to test**:
- Pure functions → simple unit tests
- No mocking needed (usually)
- Test edge cases and error conditions

**Example test structure:**
```python
class TestNowMs:
    def test_returns_milliseconds_type(self):
        result = now_ms()
        assert isinstance(result, Milliseconds)
    
    def test_returns_positive_value(self):
        result = now_ms()
        assert result.value > 0
```

---

## 7. Common Patterns

### 7.1 Path Utilities

```python
def validate_file_exists(path: Path) -> None:
    """Validate file exists and is readable."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")
    if not path.is_file():
        raise ValueError(f"Not a file: {path}")
```

### 7.2 Time Utilities

```python
def now_ms() -> Milliseconds:
    """Get current UTC time in milliseconds."""
    return Milliseconds(int(time.time() * 1000))
```

### 7.3 DTOs

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

## 8. Anti-Patterns to Avoid

### ❌ Business Logic in Helpers

**Bad:**
```python
def should_process_file(file_path: str, force: bool, config: Config) -> bool:
    """Check if file needs processing."""
    if force:
        return True
    if is_already_tagged(file_path):  # reads file!
        return False
    return True
```

**Why:** Contains business rules, performs I/O, reads config.

**Fix:** Move to a component or workflow.

### ❌ Hidden Dependencies

**Bad:**
```python
def get_config_value(key: str) -> str:
    """Get configuration value."""
    config = load_config_file()  # hidden dependency!
    return config.get(key)
```

**Why:** Hidden file I/O, not pure.

**Fix:** Pass config as parameter or move to service.

### ❌ Stateful Helpers

**Bad:**
```python
_cache = {}

def cached_compute(value: int) -> int:
    """Compute with caching."""
    if value in _cache:
        return _cache[value]
    result = expensive_computation(value)
    _cache[value] = result
    return result
```

**Why:** Mutable global state.

**Fix:** Either make cache local to function or use a proper cache decorator.

### ❌ Importing from Upper Layers

**Bad:**
```python
from nomarr.services import LibraryService  # FORBIDDEN!

def get_library_stats(library_id: str) -> dict:
    """Get library statistics."""
    service = LibraryService()
    return service.get_stats(library_id)
```

**Why:** Helpers can't depend on upper layers.

**Fix:** This belongs in a service or workflow, not helpers.

---

## 9. When to Create a New Helper

**Create a new helper when:**
- You have a pure utility function used in 2+ places
- You need a DTO for cross-layer communication
- You have a custom exception used in multiple modules

**Don't create a helper when:**
- The logic contains business rules (use component instead)
- The function performs I/O (use workflow/service instead)
- It's only used in one place (keep it local)

---

## 10. Summary

**Helpers are:**
- Pure, stateless utilities
- Data transfer objects
- Shared exceptions
- The foundation of the codebase

**Helpers are NOT:**
- Business logic
- I/O operations
- Configuration management
- Service orchestration

**Think of helpers as:** A utility library that knows nothing about Nomarr's domain and could be extracted into a standalone package with zero changes.
