# Nomarr Agent Skills

This document describes the Agent Skills specific to the Nomarr codebase.

---

## Skill Inventory

All Nomarr skills are stored in `.github/skills/`. There are **11 active skills**:

```
.github/skills/
├── code-discovery/SKILL.md
├── code-generation/SKILL.md
├── code-migration/SKILL.md
├── doc-coauthoring/SKILL.md
├── feature-execution/SKILL.md
├── feature-planning/SKILL.md
├── mcp-builder/SKILL.md
├── playwright-cli/SKILL.md
├── quality-analysis/SKILL.md
├── skill-creator/SKILL.md
└── skill-maintenance/SKILL.md
```

---

## Tooling & Workflow Skills

### code-discovery

**Trigger:** Exploring codebase structure, discovering module APIs, understanding imports, checking what functions exist.

Provides scripts that replace manual file reading with structured discovery. Use MCP tools (`read_module_api`, `locate_module_symbol`, `trace_module_calls`) as the primary discovery mechanism.

### code-generation

**Trigger:** Generating boilerplate code, `__init__.py` files, or test scaffolds.

Provides scripts that generate consistent, convention-following code.

### code-migration

**Trigger:** Moving logic between layers, deprecating patterns, refactoring responsibilities, enforcing canonical owners.

Ensures migrations are complete with no legacy coexistence. Covers the full lifecycle: identify stale code, move to correct layer, update all callers, verify with `lint_project_backend`.

### doc-coauthoring

**Trigger:** Writing documentation, proposals, technical specs, decision docs.

Guides users through a structured workflow for co-authoring documentation. Helps efficiently transfer context, refine content through iteration, and verify the doc works for readers.

### feature-execution

**Trigger:** Executing implementation plans produced by `feature-planning`.

Orchestrates execution subagents (one plan phase at a time), dispatches review subagents for thorough quality enforcement after each plan, and manages fix cycles when review finds issues. Not for single-plan execution — use `plan_complete_step` directly for those.

### feature-planning

**Trigger:** Decomposing a major feature design into dependency-ordered implementation plans.

Handles the full pipeline from design document to validated, cross-referenced plan files with minimal drift. Not for single plans or simple tasks — use the Plan subagent directly for those.

### mcp-builder

**Trigger:** Building MCP (Model Context Protocol) servers to integrate external APIs or services.

Guide for creating high-quality MCP servers, whether in Python (FastMCP) or Node/TypeScript (MCP SDK). Covers tool design, error handling, and server configuration.

### playwright-cli

**Trigger:** Navigating websites, interacting with web pages, filling forms, taking screenshots, testing web applications.

Automates browser interactions for web testing, form filling, screenshots, and data extraction.

### quality-analysis

**Trigger:** Checking code quality, finding violations, detecting complexity issues, running QC checks.

Provides scripts for linting, naming enforcement, dead code detection, and legacy code discovery. Works alongside `lint_project_backend` for automated enforcement.

### skill-creator

**Trigger:** Creating or updating skills that extend agent capabilities.

Guide for creating effective skills with specialized knowledge, workflows, or tool integrations. Covers SKILL.md structure, frontmatter requirements, and progressive disclosure.

### skill-maintenance

**Trigger:** Auditing or validating existing Agent Skills.

Provides validation scripts and guidance for keeping skills accurate and compliant with the Agent Skills specification.

---

## Dependency Direction

Skills enforce this import hierarchy:

```
interfaces → services → workflows → components → (persistence / helpers)
```

- **Interfaces** call services only
- **Services** own wiring, call workflows and/or components
- **Workflows** implement use cases, call components and other workflows
- **Components** contain domain logic, call persistence/helpers
- **Persistence/helpers** never import higher layers

Lateral (same-layer) imports are allowed. Only **upward** imports are forbidden. Import-linter enforces these boundaries.

---

## Writing Nomarr Skills

When creating a new skill for Nomarr:

1. **Follow the standard** — See [specification.md](specification.md)
2. **Match existing tone** — Review existing skills for style
3. **Be specific about triggers** — Description should clearly state when to use
4. **Include checklist** — End with a validation checklist
5. **Keep under 500 lines** — Move details to `references/` if needed

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
