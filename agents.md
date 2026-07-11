# Nomarr Agent Skills

This document catalogs the agent skills available in Nomarr's `.opencode/skills/` directory. Skills provide specialized knowledge that agents load on demand during development tasks.

---

## Layer Architecture Skills

### `nomarr-layers`

Complete architecture layer conventions for the entire Nomarr codebase.

**Covers:**
- Dependency direction: `interfaces → services → workflows → components → (persistence / helpers)`
- Allowed/forbidden imports per layer
- Naming conventions (file suffixes: `_svc.py`, `_wf.py`, `_comp.py`)
- Validation checklists per layer
- Size guidelines and split criteria
- Essentia isolation rule
- LibraryPath authority
- Frontend structure and API client patterns

**Reference files:**
- `references/components.md` — Domain logic, ML inference, tagging (stateless functions)
- `references/services.md` — DI wiring, thin orchestration, worker processes
- `references/workflows.md` — Use case recipes, one function per file, no private helpers
- `references/persistence.md` — Database access only, collection-first verbs, no business logic
- `references/interfaces.md` — HTTP/CLI adapters, one service call per route, authentication rules
- `references/helpers.md` — Pure utilities, DTOs, exceptions, no nomarr.* imports
- `references/frontend.md` — React 19 + TypeScript, feature-based modules, MUI, API client

---

## Testing Skills

### `nomarr-testing`

Testing conventions across all three test suites.

**Covers:**
- Backend: pytest markers, fixtures, mocking patterns, naming conventions
- Frontend: Vitest + React Testing Library, hooks, components, API client tests
- E2E: Playwright with Docker, fixtures, selectors, timing and debugging

**Reference files:**
- `references/backend.md` — pytest markers (unit/integration/e2e), resource markers, anti-patterns
- `references/frontend.md` — Co-located tests, query priority, mocking patterns
- `references/e2e.md` — Docker environment, auth fixture, selector strategy, conditional waits

---

## Domain Skills

### `embedding-research`

Embedding research pipeline conventions and contracts for `scripts/embedding_research/`. Covers flat strategies, binned strategies, PTC/CTP pathways, metric invariants, cross-file change protocols, storage architecture, cache rules, and known DB violations.

**Reference files:**
- `references/vocabulary.md` — Backbones, flat/binned strategies, PTC/CTP pathways, heads, comparison baselines
- `references/metrics.md` — Primary + advisory metrics, forbidden columns
- `references/architecture.md` — Storage architecture, cache layout, module owners, known DB violations
- `references/rules.md` — DB layer rules, report section rules, comprehensive "never do" list

### `nomarr-tags`

Deep reference for the Nomarr `nom:` tag system — creation, gating, storage, reading, curation, calibration, thresholds, opponent suppression, and the ArangoDB tag schema.

### `nomarr-code-migration`

Procedures for moving logic between layers, deprecating patterns, and enforcing canonical owners. Ensures migrations are complete with no legacy coexistence.

---

## Infrastructure Skills

### `docker`

Docker development environment reference — containers, e2e testing, ArangoDB queries, credentials, and collection schema.

### `playwright-cli`

Browser automation for web testing, form filling, screenshots, and data extraction.

---

## Agent Tooling Skills

### `code-discovery`

Scripts for exploring codebase structure, discovering module APIs, and understanding imports without manual file reading.

### `code-generation`

Scripts for generating boilerplate code, `__init__.py` files, and test scaffolds following project conventions.

### `code-intel-usage`

Meta-guide for using code-intel MCP tools effectively — covers hard rules, artifact logging, tool usage hierarchy, and agent behavior patterns.

---

## Meta Skills

### `agent-creation-guide`

Guidelines for creating effective OpenCode agents in `.opencode/agents/`.

### `skill-creation-guide` / `skill-creator` / `skill-maintenance`

Tools for creating and maintaining skill files (SKILL.md) following Agent Skills specifications.

### `context7`

On-demand external documentation fetching via Context7 MCP — retrieval of current library/framework documentation.

---

## Workflow Skills

### `feature-planning` / `feature-execution`

Pipeline for decomposing major features into dependency-ordered implementation plans and executing them through subagents.

### `subsystem-orientation`

Template for creating subsystem orientation skills after deep research on stable code areas.

---

## Dispatching Skills

### `dispatching-support-librarian` / `dispatching-support-patternenforcer`

Templates for dispatching support agents (artifact context gathering and pattern enforcement).
