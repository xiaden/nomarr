---
name: nomarr-layers
description: Architecture layer conventions for the Nomarr Python backend and React frontend. Covers dependency direction, allowed/forbidden imports, naming conventions, validation checklists, and size guidelines for every layer (components, services, workflows, persistence, interfaces, helpers, frontend). Use when editing code in any nomarr/ or frontend/ layer, choosing where logic belongs, or enforcing import boundaries.
---

# Nomarr Layer Conventions

**Purpose:** Define the architecture layers, their responsibilities, import rules, and conventions for the Nomarr codebase.

---

## When to Use

**Trigger conditions:**

- Editing code in `nomarr/components/`, `nomarr/services/`, `nomarr/workflows/`, `nomarr/persistence/`, `nomarr/interfaces/`, `nomarr/helpers/`, or `frontend/`
- Deciding where new logic belongs (which layer owns what)
- Enforcing import boundaries between layers
- Reviewing whether code follows layer conventions

**Do NOT use for:**
- Migration procedures (use `nomarr-code-migration`)
- Tag system specifics (use `nomarr-tags`)
- Testing conventions (use `nomarr-testing`)
- Docker or deployment concerns (use `docker`)

---

## Dependency Direction

```
interfaces → services → workflows → components → (persistence / helpers)
```

| Rule | Detail |
|------|--------|
| **Interfaces** call services only |
| **Services** own wiring, call workflows and/or components directly |
| **Workflows** orchestrate multi-step use cases, call components and other workflows |
| **Components** contain reusable domain logic, call persistence/helpers |
| **Persistence/helpers** never import higher layers |

Lateral (same-layer) imports are allowed: workflows may call other workflows, components may call other components. Only **upward** imports are forbidden.

Services may skip workflows for simple single-step operations. Workflows exist for multi-step orchestration, not as mandatory pass-through.

---

## Import Rule Summary

| Layer | May Import | Must NEVER Import |
|-------|-----------|-------------------|
| **Interfaces** | Services, DTOs, Pydantic (own layer only) | Workflows, Components, Persistence |
| **Services** | Workflows, Components, Persistence, DTOs | Interfaces, FastAPI, HTTPException, Pydantic |
| **Workflows** | Components, other workflows, Persistence, DTOs | Services, Interfaces, Pydantic |
| **Components** | Persistence, other components, DTOs, Helpers | Services, Workflows, Interfaces, Pydantic |
| **Persistence** | DTOs (helpers only), third-party libs | Services, Workflows, Components, Interfaces |
| **Helpers** | Stdlib, third-party libs, sibling DTOs | Any `nomarr.*` module from higher layers |
| **Frontend** | Shared modules, API client | Backend internals, direct DB access |

---

## Global Hard Rules

These apply across all layers:

- **Never** import `essentia` anywhere except `components/ml/audio/ml_audio_comp.py` and `components/ml/audio/ml_preprocess_comp.py`
- **Migrating from ArangoDB:** `_id`, `_key`, and `_rev` fields are being removed from DTOs in favor of PostgreSQL integer `id` fields. Do not introduce new `_id`/`_key`/`_rev` fields.
- **Never** let helpers import any `nomarr.*` modules
- **Alpha development policy:** Breaking changes are allowed before 1.0. Fix breakage by updating callers and adding migrations. Priority: clean architecture > working code > self-repairing > git history.

---

## Layer Reference Files

Each layer has a detailed reference file with its full conventions:

| Layer | Reference | Summary |
|-------|-----------|---------|
| Components | [`references/components.md`](references/components.md) | Heavy domain logic (ML, tagging, analytics). Stateless functions. DTOs return. |
| Services | [`references/services.md`](references/services.md) | DI wiring, thin orchestration. No business logic. Worker processes. |
| Workflows | [`references/workflows.md`](references/workflows.md) | Use case recipes. One public function per file. No private helpers. |
| Persistence | [`references/persistence.md`](references/persistence.md) | Database access only. No business logic. Collection-first verbs. |
| Interfaces | [`references/interfaces.md`](references/interfaces.md) | HTTP/CLI adapters. One service call per route. Thin. |
| Helpers | [`references/helpers.md`](references/helpers.md) | Pure utilities, DTOs, exceptions. No nomarr.* imports. |
| Frontend | [`references/frontend.md`](references/frontend.md) | React 19 + TypeScript. Feature-based modules. API client patterns. |

---

## Validation Checklist

Before committing code in any layer:

- [ ] Imports match the layer's allowed/forbidden rules (see table above)
- [ ] No `pydantic.BaseModel` outside interfaces layer
- [ ] No business logic in persistence or helpers
- [ ] Workflow functions are single, flat recipes (no private helpers)
- [ ] Services don't call persistence directly (delegate to components)
- [ ] Interfaces don't call more than one service per route
- [ ] `lint_project_backend(path="nomarr/<layer>")` passes with zero errors
- [ ] File size within layer-specific limits (<300-600 LOC per file, layer-dependent)

---

## Related Skills

- `nomarr-testing` — Test conventions for backend, frontend, and E2E
- `nomarr-tags` — Tag system architecture and conventions
- `nomarr-code-migration` — Migration procedures and patterns
- `docker` — Docker development environment
