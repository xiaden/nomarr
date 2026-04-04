# Agent Hierarchy Restructure — Implementation Parts

**Design doc:** [`design-agent-hierarchy-restructure.md`](../design-agent-hierarchy-restructure.md)
**Created:** 2026-04-01
**Status:** Plans created, not yet executed

---

## Parts

| Part | Title | Depends On | Scope |
|------|-------|------------|-------|
| A | Director Fix + QA Adjustments | None | Fix Director agents list, QA user-invocable settings, test-probe |
| B | QA Renames + New DocsEditor Agent | None | Rename qa-subagent → QA-Engineer, create QA-DocsEditor agent |
| C | Shared-Planner Rename | A | Rename Exec-Planner → Shared-Planner across all agent files and skills |
| D | README Rewrite | A, B, C | Comprehensive .github/agents/README.md rewrite |

---

## Dependency Graph

```
A ──────┬──→ C ──→ D
        │         ↑
B ──────┴─────────┘
```

---

## Execution Rounds

| Round | Parts | Notes |
|-------|-------|-------|
| 1 | A, B | Independent — different files |
| 2 | C | Depends on A (Director file was modified in A) |
| 3 | D | Depends on A, B, C (README reflects final state) |

---

## Per-Part Scope

### Part A: Director Fix + QA Adjustments

Fixes the critical Director blindness bug by adding QA-Reviewer, Support-Researcher, and Support-Debugger to Director's YAML agents list. Also updates Director's body content with QA routing. Adjusts user-invocable settings on QA-Reviewer (true), QA-DocsAnalyzer (false), and test-probe (false).

**Files modified:**
- `.github/agents/director.agent.md` — agents list, description, body routing table
- `.github/agents/qa-reviewer.agent.md` — user-invocable
- `.github/agents/qa-docs-analyzer.agent.md` — user-invocable
- `.github/agents/test-probe.agent.md` — user-invocable

### Part B: QA Renames + New DocsEditor Agent

Renames the orphaned `qa-subagent.agent.md` to `qa-engineer.agent.md` with updated identity. Creates a new `qa-docs-editor.agent.md` agent that provides a standalone documentation editing workflow, orchestrating QA-DocsAnalyzer, QA-DocsGenerator, and Support-Researcher.

**Files created:**
- `.github/agents/qa-engineer.agent.md` (replacement)
- `.github/agents/qa-docs-editor.agent.md` (new)

**Files deleted:**
- `.github/agents/qa-subagent.agent.md`

### Part C: Shared-Planner Rename

Renames Exec-Planner to Shared-Planner across all agent files, handoffs, and skill references. Sets the naming pattern for shared-usage agents. Skips README.md (handled by Part D).

**Files modified:**
- `.github/agents/exec-planner.agent.md` → `.github/agents/shared-planner.agent.md` (file rename + name change)
- `.github/agents/director.agent.md` — all Exec-Planner references
- `.github/agents/exec-manager.agent.md` — agents list
- `.github/agents/rnd-dd-author.agent.md` — handoff
- `.github/agents/support-researcher.agent.md` — body text
- `.github/skills/feature-planning/SKILL.md` — stale file reference

### Part D: README Rewrite

Comprehensive rewrite of `.github/agents/README.md` to reflect the final hierarchy state. Adds Planning Mechanisms section, Task Routing Guide, Shared Resources documentation, and updated hierarchy tree.

**Files modified:**
- `.github/agents/README.md` — full rewrite
