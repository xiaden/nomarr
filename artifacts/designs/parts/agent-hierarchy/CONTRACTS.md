# Agent Hierarchy Restructure — Contracts Ledger

**Design doc:** `plans/dev/design-agent-hierarchy-restructure.md`
**Last updated:** 2026-04-01 (Initial — no plans executed yet)

---

## Architectural Rules

### Agent File Rules

- Agent files live in `.github/agents/` with `.agent.md` extension
- YAML frontmatter: `name`, `description`, `agents`, `tools`, optionally `user-invocable`, `handoffs`
- Naming convention: `{department}-{role}` (e.g., `RnD-Ideator`, `Exec-Manager`, `QA-Reviewer`)
- Shared-usage agents use `Shared-` prefix (e.g., `Shared-Planner`)
- File name matches agent identity: `{lowercase-hyphenated-name}.agent.md`

### Hierarchy Rules

- Director is for coordination, not gatekeeping
- Agents can only spawn agents listed in their YAML `agents` field
- `handoffs` are UI transitions (user clicks), not spawn chains
- `user-invocable: false` means the agent only appears when spawned by a parent
- Support agents are shared resources available to multiple departments

---

## Agent Specifications

### Director (Plan A)

**agents list (final, after Plans A + C):**

```yaml
agents: [RnD-Manager, Shared-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]
```

**New routing rows (Plan A):**

```
 | "Review this code/PR" | QA-Reviewer | 
 | "Check quality of this work" | QA-Reviewer | 
```

### QA-Reviewer (Plan A)

```yaml
user-invocable: true  # Changed from false
```

### QA-DocsAnalyzer (Plan A)

```yaml
user-invocable: false  # Changed from true
```

### test-probe (Plan A)

```yaml
user-invocable: false  # Added (was implicit true)
```

### QA-Engineer (Plan B — renamed from qa-subagent)

```yaml
name: QA-Engineer
description: Standalone QA engineer for test planning, bug hunting, edge-case analysis, and implementation verification. Use for direct QA work outside the formal QA-Reviewer execution pipeline.
user-invocable: true
agents: []          # Removed agent tool — leaf agent
tools: [...]        # Same tools minus `agent`
```

### QA-DocsEditor (Plan B — NEW)

```yaml
name: QA-DocsEditor
description: Standalone documentation editing workflow. Orchestrates documentation analysis, generation, and codebase research for proactive doc improvement. Use for "I want to write/improve docs" — distinct from QA-Reviewer's quality gate.
user-invocable: true
agents: [QA-DocsAnalyzer, QA-DocsGenerator, Support-Researcher]
tools: [agent, vscode/askQuestions, search/codebase, search/fileSearch, search/listDirectory, nomarr_dev/edit_file_create, nomarr_dev/edit_file_replace_string, nomarr_dev/list_project_directory_tree, nomarr_dev/read_file_line_range, nomarr_dev/read_module_api, nomarr_dev/search_file_text]
handoffs:
  - label: Analyze Documentation
    agent: QA-DocsAnalyzer
  - label: Generate Documentation
    agent: QA-DocsGenerator
  - label: Research Codebase
    agent: Support-Researcher
```

### Shared-Planner (Plan C — renamed from Exec-Planner)

```yaml
name: Shared-Planner
# File: shared-planner.agent.md (renamed from exec-planner.agent.md)
# All body content unchanged — only name, file, and cross-references updated
```

---

## Reference Updates (Plan C)

 | File | Change |
 | ------ | -------- |
 | `director.agent.md` | All "Exec-Planner" → "Shared-Planner" (7 occurrences) |
 | `exec-manager.agent.md` | agents list (1 occurrence) |
 | `rnd-dd-author.agent.md` | handoff agent (1 occurrence) |
 | `support-researcher.agent.md` | body text (1 occurrence) |
 | `feature-planning/SKILL.md` | Comment reference to `planner.agent.md` → `shared-planner.agent.md` (1 occurrence) |
 | `README.md` | Handled entirely by Plan D |

---

## Decisions

 | # | Decision | Rationale |
 | --- | ---------- | ----------- |
 | 1 | Shared-Planner rename (overrides DD recommendation to keep name) | User decision — sets naming pattern for shared-usage agents |
 | 2 | New QA-DocsEditor agent (overrides DD "no new agents" goal) | User decision — provides standalone docs editing workflow separate from QA quality gate |
 | 3 | QA-DocsGenerator stays user-invocable: false (actual state) | DD incorrectly listed current state as true; leaving as-is since QA-DocsEditor is the user entry point |
 | 4 | agents.instructions.md example not updated | Generic illustrative example using "planner.agent.md" — not a real reference to Exec-Planner |
 | 5 | Plan C skips README.md updates | Plan D does a full README rewrite; updating in C then rewriting in D is double-work |
