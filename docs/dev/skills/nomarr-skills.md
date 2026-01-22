# Nomarr Agent Skills

This document describes the Agent Skills specific to the Nomarr codebase.

---

## Skill Locations

All Nomarr skills are stored in `.github/skills/`:

```
.github/skills/
├── layer-helpers/SKILL.md
├── layer-components/SKILL.md
├── layer-workflows/SKILL.md
├── layer-services/SKILL.md
├── layer-interfaces/SKILL.md
├── layer-persistence/SKILL.md
├── code-discovery/SKILL.md
├── code-generation/SKILL.md
├── quality-analysis/SKILL.md
└── skill-maintenance/SKILL.md
```

---

## Layer Skills

These skills provide architecture-specific guidance for each layer of the Nomarr codebase.

### layer-helpers

**Trigger:** Creating or modifying code in `nomarr/helpers/`

Key rules:
- NO `nomarr.*` imports (stdlib and third-party only)
- No config/env reads at import time
- Pure, stateless utility functions
- DTOs defined here, used everywhere
- **MUST NOT** construct or validate library paths (use `path_comp`)

### layer-components

**Trigger:** Creating or modifying code in `nomarr/components/`

Key rules:
- Heavy domain logic lives here (ML, analytics, tagging)
- Stateless functions preferred over classes
- Only `ml_backend_essentia_comp.py` may import Essentia
- `path_comp` is the sole authority for `LibraryPath` construction
- Module names end in `_comp.py`

### layer-workflows

**Trigger:** Creating or modifying code in `nomarr/workflows/`

Key rules:
- Implement use cases, orchestrate components
- Accept dependencies as parameters (DI)
- Return DTOs, not raw dicts
- No direct service imports

### layer-services

**Trigger:** Creating or modifying code in `nomarr/services/`

Key rules:
- Own runtime wiring and long-lived resources (DB, queues, workers)
- Call workflows, never contain business logic
- Services may import workflows and components

### layer-interfaces

**Trigger:** Creating or modifying code in `nomarr/interfaces/`

Key rules:
- Thin adapters (API routes, CLI commands)
- Validate inputs, call services, serialize outputs
- No business logic

### layer-persistence

**Trigger:** Creating or modifying code in `nomarr/persistence/`

Key rules:
- Database and queue access only
- No business logic
- Never imports higher layers

---

## Tooling Skills

These skills provide guidance for code analysis and generation tasks.

### code-discovery

**Trigger:** Exploring codebase structure, discovering module APIs, checking imports

Scripts:
- `scripts/discover_api.py <module>` - List module's public API
- `scripts/discover_import_chains.py` - Trace import dependencies

### code-generation

**Trigger:** Generating boilerplate, `__init__.py` files, test scaffolds

Scripts:
- `scripts/generate_inits.py` - Generate `__init__.py` exports
- `scripts/generate_tests.py` - Generate test scaffolds

### quality-analysis

**Trigger:** Checking code quality, finding violations, running QC checks

Scripts:
- `scripts/run_qc.py` - Run quality checks
- `scripts/check_naming.py` - Verify naming conventions
- `scripts/find_legacy.py` - Detect legacy patterns

### skill-maintenance

**Trigger:** Creating, updating, auditing, or validating Agent Skills

Scripts:
- `scripts/validate_skills.py` - Validate skill format and references
- `scripts/validate_skills.py --check-refs` - Also check code references exist

---

## Dependency Direction

Skills enforce this import hierarchy:

```
interfaces → services → workflows → components → (persistence / helpers)
```

- **Interfaces** call services only
- **Services** own wiring, call workflows
- **Workflows** implement use cases, call components
- **Components** contain heavy logic, call persistence/helpers
- **Persistence/helpers** never import higher layers

---

## Writing Nomarr Skills

When creating a new skill for Nomarr:

1. **Follow the standard** - See [specification.md](specification.md)
2. **Match existing tone** - Review existing skills for style
3. **Be specific about triggers** - Description should clearly state when to use
4. **Include checklist** - End with a validation checklist
5. **Keep under 500 lines** - Move details to `references/` if needed

### Template

```markdown
---
name: my-domain
description: Use when creating or modifying code in nomarr/domain/. Provides [key capabilities].
---

# Domain Layer

**Purpose:** [One sentence purpose]

[Key rules and patterns]

---

## Validation Checklist

Before committing code, verify:

- [ ] [Check 1] **→ Consequence**
- [ ] [Check 2] **→ Consequence**
```

---

## Updating Skills

When architecture changes:

1. Identify affected skills
2. Update only sections that are now incorrect
3. Do NOT reformat or rewrite unrelated content
4. Keep changes minimal and enforceable
5. Test that skills still trigger correctly
