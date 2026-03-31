# Agent Types

Hierarchical agent system for managing complex multi-plan features. The Director (main agent) spawns department heads and specialized agents. RnD-Manager owns the "thinking" phase (design, ideation, analysis). Exec-Manager owns implementation lifecycle.

## Architecture

```
Director
├── RnD-Manager (R&D Department)
│   ├── RnD-DDAuthor (Design Lead) → Support-Researcher
│   ├── RnD-Ideator
│   ├── RnD-Architect → Support-Researcher
│   ├── RnD-Estimator
│   ├── RnD-PatternEnforcer
│   ├── RnD-Improver
│   ├── RnD-ComplexityAdvisor
│   └── Support-Researcher
├── Exec-Planner → Support-Researcher
├── Support-Researcher
├── Support-Debugger
└── Exec-Manager (per plan)
    ├── Exec-Executor (per phase)
    ├── QA-Reviewer
    │   ├── QA-TestAnalyzer → QA-TestGenerator
    │   └── QA-DocsAnalyzer → QA-DocsGenerator
    ├── Exec-Fixer (if needed)
    └── Exec-Planner (for plan amendments)
```

**Key principle:** RnD-Manager owns exploration and design. Exec-Manager owns execution. Director coordinates between them.

---

## Agent Types

| Agent | Purpose | Spawns Children? |
|-------|---------|------------------|
| `Director` | Top-level orchestrator for features | Yes (RnD-Manager, Exec-Planner, Exec-Manager, Support-Researcher, Support-Debugger) |
| `RnD-Manager` | R&D Department head — owns exploration/design | Yes (RnD-DDAuthor, advisory agents, Support-Researcher) |
| `RnD-DDAuthor` | Creates design docs from requirements | Yes (RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher) |
| `RnD-Ideator` | Creative solution generation | No |
| `RnD-Architect` | Implementation options analysis | Yes (Support-Researcher) |
| `RnD-Estimator` | Effort sizing | No |
| `RnD-PatternEnforcer` | Finds where patterns should apply | No |
| `RnD-Improver` | Enhancement suggestions | No |
| `RnD-ComplexityAdvisor` | Semantic complexity analysis | No |
| `Exec-Manager` | Owns one plan's full lifecycle | Yes (Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner) |
| `Exec-Executor` | Implements one phase of a plan | No |
| `Exec-Planner` | Creates/amends plan files | Yes (Support-Researcher) |
| `Exec-Fixer` | Targeted repairs from review issues | No |
| `QA-Reviewer` | Quality gate with test/docs verification | Yes (QA-TestAnalyzer, QA-DocsAnalyzer) |
| `QA-TestAnalyzer` | Analyzes test coverage, self-repairs | Yes (QA-TestGenerator) |
| `QA-TestGenerator` | Generates tests to fill gaps | No |
| `QA-DocsAnalyzer` | Analyzes documentation, self-repairs | Yes (QA-DocsGenerator) |
| `QA-DocsGenerator` | Generates/updates documentation | No |
| `Support-Researcher` | Deep codebase/external research | No |
| `Support-Debugger` | Root cause analysis for failures | No |

---

## Input Contract (All Agents)

Every agent receives:

```yaml
contextFiles:      # Files to read BEFORE starting work
  - plans/TASK-{feature}-{letter}-*.md        # The plan
  - plans/dev/{feature}-parts/CONTRACTS.md    # Current contracts
  - plans/dev/{feature}-parts/README.md       # Feature structure
  - plans/dev/design-{feature}.md             # Design doc
  - .github/instructions/{layer}.instructions.md  # Per layer touched
```

Task-specific parameters go in a structured `task:` section, not prose summaries.

---

## Output Contract (All Agents)

All agents return a structured report:

```yaml
status: DONE | BLOCKED | ESCALATE
summary: "One-line outcome"
artifacts:          # Files created/modified
  - path: "..."
    action: created | modified | deleted
annotations:        # Notes for next agent or Director
  - "..."
blockers:           # Only if status != DONE
  - type: PLANNING_GAP | DEPENDENCY | EXTERNAL | UNKNOWN
    detail: "..."
nextAction:         # Suggested follow-up (optional)
  type: DISPATCH_FIXER | AMEND_PLAN | DISCUSS | CONTINUE
  reason: "..."
```

---

## Agent Definitions

See individual `.agent.md` files:

**Executive:**
- [director.agent.md](director.agent.md) — Top-level feature orchestrator

**R&D Department:**
- [rnd-manager.agent.md](rnd-manager.agent.md) — R&D Department head
- [rnd-dd-author.agent.md](rnd-dd-author.agent.md) — Design document creation
- [rnd-ideator.agent.md](rnd-ideator.agent.md) — Creative solution generation
- [rnd-architect.agent.md](rnd-architect.agent.md) — Implementation options analysis
- [rnd-estimator.agent.md](rnd-estimator.agent.md) — Effort sizing
- [rnd-pattern-enforcer.agent.md](rnd-pattern-enforcer.agent.md) — Pattern consistency discovery
- [rnd-improver.agent.md](rnd-improver.agent.md) — Enhancement suggestions
- [rnd-complexity-advisor.agent.md](rnd-complexity-advisor.agent.md) — Semantic complexity analysis

**Plan Execution:**
- [exec-manager.agent.md](exec-manager.agent.md) — Full plan lifecycle owner
- [exec-executor.agent.md](exec-executor.agent.md) — Phase implementation
- [exec-planner.agent.md](exec-planner.agent.md) — Plan creation/amendment
- [exec-fixer.agent.md](exec-fixer.agent.md) — Targeted repairs

**Quality Assurance:**
- [qa-reviewer.agent.md](qa-reviewer.agent.md) — Quality gate with test/docs verification
- [qa-test-analyzer.agent.md](qa-test-analyzer.agent.md) — Test coverage analysis with self-repair
- [qa-test-generator.agent.md](qa-test-generator.agent.md) — Test generation
- [qa-docs-analyzer.agent.md](qa-docs-analyzer.agent.md) — Documentation analysis with self-repair
- [qa-docs-generator.agent.md](qa-docs-generator.agent.md) — Documentation generation

**Support:**
- [support-researcher.agent.md](support-researcher.agent.md) — Deep codebase/external research
- [support-debugger.agent.md](support-debugger.agent.md) — Root cause analysis for failures

---

## Hierarchy Rules

1. **Director is for large features** — Use Director when coordinating multiple plans. For simpler work, invoke managers/agents directly.
2. **RnD-Manager and Exec-Manager are directly invokable** — No need to go through Director for single-plan or focused R&D work.
3. **RnD-DDAuthor spawns RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher** — Design lead can task advisory agents.
4. **RnD-Manager spawns RnD-DDAuthor, all advisory agents, Support-Researcher** — Department head has full R&D toolkit.
5. **Advisory agents are read-only** — RnD-Ideator, RnD-Architect, RnD-Estimator, RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor return reports, not code.
6. **Exec-Manager spawns Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner** — Owns the plan lifecycle internally.
7. **QA-Reviewer spawns QA-TestAnalyzer, QA-DocsAnalyzer** — For quality verification with self-repair.
8. **QA-TestAnalyzer spawns QA-TestGenerator** — For filling test coverage gaps.
9. **QA-DocsAnalyzer spawns QA-DocsGenerator** — For filling documentation gaps.
10. **RnD-Architect spawns Support-Researcher** — For deep investigation during options analysis.
11. **Leaf agents spawn nothing** — Exec-Executor, Exec-Fixer, Support-Researcher, Support-Debugger, QA-TestGenerator, QA-DocsGenerator, RnD-Ideator, RnD-Estimator, RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor.
12. **Escalation is explicit** — `status: ESCALATE` means "I need human/Director input."
13. **Files are the handoff** — No prose summaries. Agents read files, write to files, report file paths.
14. **Annotations compound** — Each agent adds to plan file annotations. Nothing gets lost.

---

## Dispatch Example

Director prompt:
```
Dispatch Exec-Manager for Plan B.

contextFiles:
  - plans/TASK-schema-refactor-v1-B-library-files.md
  - plans/dev/schema-refactor-v1-parts/CONTRACTS.md
  - plans/dev/schema-refactor-v1-parts/README.md
  - plans/dev/design-schema-refactor-v1.md
  - .github/instructions/persistence.instructions.md
  - .github/instructions/workflows.instructions.md

task:
  plan: TASK-schema-refactor-v1-B-library-files
  startPhase: 1  # or resume from last incomplete
  reviewRequired: true
```

Exec-Manager returns (after internal execution + review + any fix cycles):
```yaml
status: DONE
summary: "Plan B complete: 7 phases, 33 steps, 1 fix cycle"
artifacts:
  - path: nomarr/persistence/database/library_files_aql/queries.py
    action: modified
  - path: nomarr/persistence/database/library_files_aql/crud.py
    action: modified
  # ... etc
annotations:
  - "Fixed 8 methods that still referenced library_id after Phase 4"
  - "Review Round 2 passed"
blockers: []
```

Director only knows: Plan B done, moved on to Plan C.
