# Helpers Layer

**Purpose:** Provide pure utilities and shared data types used across all layers.

Helpers are **stateless utilities** that:
- Perform generic operations (file handling, time, data formatting)
- Define DTOs (data transfer objects)
- Define exceptions
- Have **no knowledge of Nomarr's domain**

---

## Directory Structure

```
helpers/
├── files_helper.py           # Path utilities, file discovery
├── file_validation_helper.py # Path validation
├── logging_helper.py         # Logging utilities
├── time_helper.py            # Time utilities (now_ms, etc.)
├── exceptions.py             # Domain exceptions
├── dataclasses.py            # Shared dataclasses
└── dto/                      # Data transfer objects
    ├── processing_dto.py     # FileDict, ProcessingResult, etc.
    ├── library_dto.py        # LibraryDict, etc.
    ├── analytics_dto.py      # AnalyticsResult, etc.
    └── __init__.py
```

---

## Import Rules

**Helpers may ONLY import:**

```python
# ✅ Allowed
import os
import pathlib
from datetime import datetime
from typing import TypedDict
import yaml  # Third-party OK
```

**DTO cross-imports are allowed (one-way only):**
```python
# ✅ Allowed - helpers-internal sibling cross-imports
from nomarr.helpers.dataclasses.tags_dataclass import Tags  # OK in processing_dto.py
from nomarr.helpers.dto.path_dto import LibraryPath  # OK in ml_dto.py
```

The dependency direction must be acyclic. If `A` imports `B`, then `B` must not import `A`.

**Helpers must NEVER import from higher layers:**

```python
# ❌ NEVER import any higher-layer nomarr.* modules
from nomarr.persistence import Database
from nomarr.services import ConfigService
from nomarr.workflows import ...
from nomarr.components import ...
from nomarr.interfaces import ...
```

This is a **hard rule**. Helpers are the foundation—they cannot depend on anything above them.

---

## No Config at Import Time

Helpers must **never** read config files or environment variables at import time.

---

## DTO Pattern

DTOs are typed dictionaries or dataclasses for cross-layer data.

**Placement rules:**
- **Cross-layer DTOs** (used by multiple layers): `helpers/dto/<domain>.py`
- **Single-service DTOs** (used only in one service): Define in service file

---

## Pure Utility Functions

Helpers should be **pure** (no side effects, deterministic output).

---

## Exceptions

Domain exceptions live in `helpers/exceptions.py`:
```python
class NomarrError(Exception):
    """Base exception for all Nomarr errors."""
class LibraryNotFoundError(NomarrError): ...
class ConfigurationError(NomarrError): ...
```

---

## What Belongs Here vs Elsewhere

| If it... | Put it in... |
|----------|-------------|
| Does file path manipulation | `helpers/files_helper.py` |
| Formats time/timestamps | `helpers/time_helper.py` |
| Is a cross-layer DTO | `helpers/dto/<domain>.py` |
| Is a domain exception | `helpers/exceptions.py` |
| Does tag parsing logic | `components/tagging/` (not helper) |
| Does DB queries | `persistence/` (not helper) |
| Has any business logic | `components/` (not helper) |
| Constructs/validates library paths | `components/infrastructure/path_comp.py` (not helper) |

---

## Library Path Restriction

Helpers MUST NOT construct, resolve, or validate library paths. All library path construction and validation occurs exclusively in `path_comp` via `LibraryPath` factories.
- Helpers define `LibraryPath` DTO in `helpers/dto/path_dto.py`
- Helpers MUST NOT call `build_library_path_from_input()` or `build_library_path_from_db()`
- Any helper needing a path must receive a validated `LibraryPath` DTO as a parameter

---

## Validation

- Does this file import from any `nomarr.*` module? **→ Violation (hard rule)**
- Does this file read config/env at import time? **→ Violation**
- Does this contain business logic? **→ Move to components**
- Does this construct or validate library paths? **→ Violation (use path_comp)**
- Are functions pure (no hidden state)? **→ Preferred**
- **Run `lint_project_backend(path="nomarr/helpers")` after every edit.** Zero errors is the only acceptable state.
