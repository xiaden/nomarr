# Quality Control System

Nomarr uses layered quality checks to keep architecture, typing, and behavior consistent as the codebase evolves.

---

## QC Goals

The QC system is designed to catch:

- Layering violations
- Type drift
- Broken imports
- Missing test coverage in critical paths
- Persistence/API drift after refactors

---

## Main QC Checks

### 1. Backend lint suite

Covers formatting, lint, typing, import rules, and tests.

Typical checks include:

- Ruff
- Mypy
- Import-linter
- Pytest

### 2. Architecture QC

Architecture QC verifies that dependency direction remains intact.

Relevant areas include:

- `nomarr/workflows/processing/` — audio processing workflows
- `nomarr/components/ml/` — ONNX inference and audio preprocessing
- `nomarr/components/tagging/` — tag extraction and aggregation
- `nomarr/services/domain/library_svc/` — library management
- `nomarr/services/domain/calibration_svc.py` — calibration
- `nomarr/services/domain/tagging_svc.py` — tagging operations
- `nomarr/services/infrastructure/worker_system_svc.py` — worker lifecycle
- `nomarr/persistence/db.py` — database facade
- `nomarr/persistence/base.py` — persistence base types
- `nomarr/persistence/collections.py` — class-based collection declarations
- `nomarr/persistence/constructor/builder.py` — runtime collection wiring
- `nomarr/interfaces/api/` — FastAPI routes and auth
- `nomarr/interfaces/cli/` — CLI commands

### 3. Persistence surface checks

Persistence changes should be validated for:

- correct collection declarations in `collections.py`
- correct runtime wiring through `Builder`
- regenerated `nomarr/persistence/stubs/` when the public API changes
- no upward imports from persistence into higher layers

---

## QC Reports

### Report Structure

Good QC output should make it obvious:

- what failed
- where it failed
- whether the failure is architectural, typing-related, or behavioral
- what area of the codebase is affected

### Typical follow-up after persistence refactors

When persistence internals change:

1. update the collection declarations or builder wiring
2. regenerate stubs if the runtime API changed
3. run backend lint
4. run targeted tests or the full suite as appropriate
5. run architecture QC to confirm boundaries still hold

That combo catches most refactor gremlins before they escape into the wild.