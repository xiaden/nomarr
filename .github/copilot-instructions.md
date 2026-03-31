# Copilot Instructions for Nomarr

---

## Alpha Development Policy

Nomarr is **alpha software** with forward-only migrations. Breaking changes are allowed before 1.0, but the system self-repairs via database migrations on startup. When you change contracts and something breaks, fix the breakage by updating callers and adding migrations if schema changes. Priority is always clean architecture over preserving old code.

**Do break:**
- Change service method signatures to fix layer violations
- Rename modules to match actual responsibilities
- Delete unused code even if recently added
- Refactor workflows to eliminate temporal coupling
- Change database schemas (add a migration in `nomarr/migrations/` — do NOT edit `ensure_schema`, it is a frozen baseline)

**Fix the breakage by:**
- Updating all callers (use `find_referencing_symbols`)
- Running `lint_project_backend` to find compile errors
- Updating tests to match new contracts
- Writing a forward-only migration if schema changes (see `docs/dev/migrations.md`)

**Priority order:**
1. Clean architecture (proper layers, clear contracts)
2. Working code (passes lint + tests)
3. Self-repairing (migrations for schema changes)
4. Git history / preserving old code (irrelevant)

---

## Dependency Direction

```
interfaces â†’ services â†’ workflows â†’ components â†’ (persistence / helpers)
```

- **Interfaces** call services only
- **Services** own wiring, call workflows and/or components directly
- **Workflows** orchestrate multi-step use cases, call components and other workflows
- **Components** contain reusable domain logic, call persistence/helpers
- **Persistence/helpers** never import higher layers

Lateral (same-layer) imports are allowed: workflows may call other workflows, components may call other components. Only **upward** imports are forbidden.

Services may skip workflows for simple single-step operations. Workflows exist for multi-step orchestration, not as mandatory pass-through.

Import-linter enforces layer boundaries.

---

## Hard Rules

**Never:**

- Import `essentia` anywhere except `components/ml/audio/ml_audio_comp.py` (MonoLoader audio loading) and `components/ml/audio/ml_preprocess_comp.py` (mel spectrogram preprocessing). Essentia is no longer the ML backend — ONNX is. Essentia is a thin set of functions for audio I/O and preprocessing only.
- Read config or env vars at module import time
- Create or mutate global state
- Rename `_id` or `_key` (ArangoDB-native identifiers)
- Let workflows import services or interfaces
- Let helpers import any `nomarr.*` modules
- Guess context or line counts in tool usage
- Create plans, memories, or summaries solely to "preserve context" — if the task doesn't require durable tracking, use todos and finish the work

**Always:**

- Use dependency injection for major resources (db, config, backends) — not every operation
- Write fully type-annotated code
- Use MCP `read_module_api` before calling unfamiliar APIs (the script version is legacy fallback)
- Check venv is active before running Python commands
- Reread context if a tool errors