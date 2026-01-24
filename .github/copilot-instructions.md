# Copilot Instructions for Nomarr

These are the **always-on** hard rules. Layer-specific guidance lives in `.github/skills/`.

---

## Pre-Alpha Policy

Nomarr is **pre-alpha**. That means:

- Breaking schemas and APIs is acceptable
- **No** migrations, legacy shims, or compatibility layers
- Priority: clean architecture, not preserving old data

---

## Dependency Direction

```
interfaces â†’ services â†’ workflows â†’ components â†’ (persistence / helpers)
```

- **Interfaces** call services only
- **Services** own wiring, call workflows
- **Workflows** implement use cases, call components
- **Components** contain heavy logic, call persistence/helpers
- **Persistence/helpers** never import higher layers

Import-linter enforces this.

---

## Hard Rules

**Never:**

- Import `essentia` anywhere except `components/ml/ml_backend_essentia_comp.py`
- Read config or env vars at module import time
- Create or mutate global state
- Rename `_id` or `_key` (ArangoDB-native identifiers)
- Let workflows import services or interfaces
- Let helpers import any `nomarr.*` modules

**Always:**

- Use dependency injection (receive db, config, backends as parameters)
- Write fully type-annotated code
- Run `python scripts/discover_api.py <module>` before calling unfamiliar APIs
- Check venv is active before running Python commands

---

## DI Philosophy

Config is loaded once by `ConfigService` and passed via parameters. No global singletons.

---

## Quality Scripts

For detailed tool usage, see `.github/skills/quality-analysis/` and `.github/skills/code-discovery/`.

Quick reference:

```bash
# Discover module API before calling it
python scripts/discover_api.py nomarr.components.ml

# Run all QC checks
python scripts/run_qc.py

# Find complexity/violations in specific file
python scripts/detect_slop.py nomarr/workflows/some_wf.py
```

---

## Layer-Specific Skills

Detailed guidance for each layer is loaded on-demand via Agent Skills:

- `layer-interfaces/` — API routes, CLI commands
- `layer-services/` — DI wiring, orchestration
- `layer-workflows/` — Use case implementation
- `layer-components/` — Heavy domain logic
- `layer-persistence/` — Database access
- `layer-helpers/` — Pure utilities, DTOs
- `layer-frontend/` — React + TypeScript UI (requires lint+build verification)

These load automatically when editing files in the relevant layer.

---

End of always-on instructions.