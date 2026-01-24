# Copilot Instructions for Nomarr

These are the **always-on** hard rules. Layer-specific guidance lives in `.github/skills/`.

---

## MANDATORY PROCESS REQUIREMENTS

**These requirements are NOT optional. Skipping them creates architectural debt and bugs.**

### 1. Read Layer Skills BEFORE Editing

**You MUST read the relevant skill file BEFORE editing any code in that layer.**

Do not skip this step to save time. Skills contain:
- Layer-specific conventions and patterns
- Required validation steps
- Common mistakes to avoid
- File naming and structure rules

| Path Pattern | Skill to Read |
|--------------|---------------|
| `nomarr/interfaces/` | `.github/skills/layer-interfaces/SKILL.md` |
| `nomarr/services/` | `.github/skills/layer-services/SKILL.md` |
| `nomarr/workflows/` | `.github/skills/layer-workflows/SKILL.md` |
| `nomarr/components/` | `.github/skills/layer-components/SKILL.md` |
| `nomarr/persistence/` | `.github/skills/layer-persistence/SKILL.md` |
| `nomarr/helpers/` | `.github/skills/layer-helpers/SKILL.md` |
| `frontend/` | `.github/skills/layer-frontend/SKILL.md` |

The skill guidance is **authoritative** for naming, boundaries, and allowed imports. Do not proceed without consulting it.

### 2. Use MCP `discover_api` Before Editing Modules

**You MUST use the MCP `discover_api` tool to inspect module shapes before editing.**

- Run `discover_api` for each module you will modify
- Use the discovered function/class signatures as the source of truth
- Do not guess at existing APIs — verify them

```
# Example: discover API before modifying
mcp_nomarrdev_discover_api("nomarr.services.infrastructure.file_watcher_svc")
```

### 3. Run Layer Validation Scripts

**You MUST NOT skip validation steps required by the skill.**

After making changes, run the layer's naming checker:

```powershell
# Services layer
python .github/skills/layer-services/scripts/check_naming.py

# Persistence layer
python .github/skills/layer-persistence/scripts/check_naming.py

# Interfaces layer
python .github/skills/layer-interfaces/scripts/check_naming.py
```

If the skill specifies additional checks (lint, mypy, build), run them before committing.

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

## Layer-Specific Skills Reference

Skills contain mandatory conventions, patterns, and verification steps:

| Skill | Purpose |
|-------|---------|
| `layer-interfaces/` | API routes, CLI commands |
| `layer-services/` | DI wiring, orchestration, worker processes |
| `layer-workflows/` | Use case implementation |
| `layer-components/` | Heavy domain logic |
| `layer-persistence/` | Database access |
| `layer-helpers/` | Pure utilities, DTOs |
| `layer-frontend/` | React + TypeScript UI |

---

End of always-on instructions.