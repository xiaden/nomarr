# Copilot Instructions

These instructions guide Copilot to produce consistent, maintainable, idiomatic code that fits the Nomarr architecture. The goal is predictability, correctness, and clarity.

---

## 🛑 **Copilot — Hard Rules (Read First)**

**Never:**

- write bare `import essentia` or `import essentia_tensorflow`
- import Essentia in any top-level module
- introduce global mutable state
- create 300+ line functions
- mix unrelated concerns (tagging + DB + workers)

**Always:**

- follow the directory placement rules below
- keep functions < ~50 lines unless structurally justified
- prefer dependency injection (receive db, config, etc. from caller)
- write mypy-friendly, fully type‑annotated code
- keep imports local when optional or heavyweight

A full Essentia backend module will exist at:

```
ml/backend_essentia.py
```

All Essentia use must follow this pattern:

```python
try:
    import essentia_tensorflow as essentia_tf
except ImportError:  # pragma: no cover
    essentia_tf = None
```

---

## 1. Project Philosophy

Nomarr is structured around **separation of concerns**, correctness, and predictability. All code must adhere to:

- **Pure ML code is isolated** (no DB, no HTTP, no workers)
- **Workflows orchestrate**, but do not perform low‑level actions
- **Services manage resources** (workers, queues, runtime)
- **Tagging code only handles tag logic**
- **Persistence is a thin access layer**
- **Interfaces expose, but do not compute**

Everything should be deterministic, explicit, and testable.

### Pre‑Alpha Status

Nomarr is currently **pre‑alpha**. This means:

- There is **no legacy code**; only current code exists.
- There is **no need for backward compatibility**.
- Do **not** build migration systems, compatibility shims, versioned persistence layers, or upgrade paths.
- Breaking changes are acceptable and expected.
- Prefer **clean, forward‑looking architecture**, but avoid speculative future‑proofing (e.g., cluster support, distributed systems) unless explicitly required.

Copilot: Plan for the future **when it clearly serves the current design**, but do not introduce complex abstractions for imaginary requirements.

---

## 2. Where New Code Should Go

### **Quick Placement Guide (TL;DR)**

```
Contains domain logic, takes db/config, no HTTP/workers → workflows/
Pure ML, embeddings, inference models → ml/
Tag normalization, tiering, conflict rules, ID3 writes → tagging/
Raw SQL or durability logic → persistence/
Worker orchestration, queues, scheduling → services/
API endpoints, Web UI, CLI commands → interfaces/
Pure stateless utilities → helpers/
```

### workflows/

High-level operations and orchestration. Receives db + config from callers. Never touches lower-level resources directly.

### ml/

Embedder/head models, ML inference, calibration logic. No DB. No HTTP. No workers.

### tagging/

Convert model outputs → normalized tags. Tiering, scoring, conflict resolution. Writes tags using writer module.

### persistence/

DB access layer, SQL models, migrations. No business logic.

### services/

Worker pools, queues, scheduling. Holds long‑running processes and side‑effects.

### interfaces/

HTTP REST API, CLI wrapper. Translates requests → workflow calls. No domain logic.

### helpers/

Pure, stateless utilities. Cannot import workflows/services/ml/tagging.

---

## 3. Architectural Rules

### Dependency Direction

```
interfaces → workflows → tagging → ml
                     ↓           ↓
                 persistence    helpers
                     ↓
                 services (only for worker mgmt)
```

### Rules

- ML must not import tagging, workflows, persistence, or services.
- Tagging must not import workflows or services.
- Workflows may import ML, tagging, or persistence.
- Interfaces must call workflows only.
- Services run workflows, never the inverse.

---

## 4. Code Style

### Python

- Fully type annotated
- ruff formatting
- short functions (<50 lines)
- small modules (<300 lines)
- prefer pure functions
- prefer explicit over clever

### JavaScript

- Prettier formatting
- ESLint rules enforced
- Avoid global state

### Error Handling

- Use typed errors
- No bare `except:`

---

## 5. Tooling (Copilot-aware summary)

**Fast local tools (run constantly):**

```bash
ruff check .
ruff check --fix .
ruff format .
pytest
mypy .
```

**Deeper analysis (run periodically):**

```bash
bandit .
vulture .
radon cc -s nomarr
radon mi -s nomarr
flake8
import-linter
wily build
```

Copilot should produce code _consistent_ with these tools.

---

### 5.5 Development Scripts

The `scripts/` directory provides **structured development helpers**. These tools exist to keep the codebase predictable and consistent. Copilot should rely on them to avoid inventing APIs or drifting from project conventions.

#### Purpose

These scripts are the preferred way to:

- confirm which APIs, classes, and functions actually exist,
- keep naming and exports consistent,
- generate boilerplate (tests, `__init__` files) in a predictable style,
- identify high‑value refactor targets.

#### Before Writing or Modifying Code

Use these to understand what _actually exists_ before generating code.

```bash
# Inspect real module APIs, attributes, and callables
python scripts/discover_api.py nomarr.workflows.processor
python scripts/discover_api.py nomarr.persistence.db --summary
```

#### During Development

Ensure new code matches project conventions and layout.

```bash
# Enforce naming rules across the project
python scripts/check_naming.py

# Auto-generate __init__.py exports to match actual module APIs
python scripts/generate_inits.py

# Create test scaffolds based on current module structure
python scripts/generate_tests.py nomarr.services.queue --output tests/unit/services/test_queue.py
```

#### Targeted Quality & Refactor Triage

Use this when you want to clean up **specific modules** or subsystems:

```bash
# Find complexity hotspots, architecture violations, and refactor opportunities (JSON + Markdown)
python scripts/detect_slop.py nomarr/workflows/processor.py
```

Run `detect_slop.py` on **one file or one package at a time**, then:

- let Copilot summarize the report,
- agree on a small refactor plan,
- apply changes iteratively.

Do not expect Copilot to “fix the entire codebase from one giant report” — use this script as a triage tool, not a fully automated cleanup.

**Copilot Rule:**
Before writing or modifying code, **always** confirm APIs with `discover_api.py`. Never guess function names, signatures, or return types. Use these tools to align generated code with Nomarr’s architectural and stylistic rules.

## 6. Configuration

- Configuration must be strongly typed (Pydantic model)
- Workers receive config from caller
- No module-level reading of config files

---

## 7. Optional Dependencies

Essentia is optional in development. All imports must be guarded. If essentia_tf is missing, raise a clear runtime error only when ML is invoked.

Never block the app from starting if Essentia isn’t installed.

---

## 8. Folder Naming and Structure

Current approved structure:

```
nomarr/
  interfaces/
  workflows/
  services/
  tagging/
  ml/
  persistence/
  helpers/
```

---

## 9. Performance Rules

- No premature optimization
- Cache expensive ML operations (when available)
- Avoid reading audio from disk more than once per workflow
- Avoid large in-memory structures in workers

---

## 10. File Length Guidance

- Aim for <300 lines per module
- Break up long functions with private helpers
- Prefer composition over inheritance

---

## 11. Commit Expectations

- All diffs must pass ruff + pytest
- No commented-out code
- No code with FIXME/TODO unless accompanied by GitHub issue ID

---

## 12. Summary (for Copilot)

1. Keep code small, typed, and explicit.
2. Use the directory placement rules.
3. Do not import Essentia directly.
4. Push logic downward (interfaces → workflows → tagging → ml).
5. Write code that passes ruff, mypy, and pytest by default.
6. Helpers must be pure and dependency-free.

---

End of instructions.
