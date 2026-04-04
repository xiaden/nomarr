# Agent Hierarchy

Hierarchical agent system organized into four departments. Department heads and the Director live at the root level; specialized agents live in department subfolders.

## Directory Layout

```
.github/agents/
├── agent.agent.md              # Default agent (all tools)
├── director.agent.md           # Top-level orchestrator
├── exec-manager.agent.md       # Execution department head
├── rnd-manager.agent.md        # R&D department head
├── README.md
│
├── Exec/                       # Plan Execution department
│   ├── exec-executor.agent.md  # Phase implementation
│   ├── exec-fixer.agent.md     # Targeted repairs from review
│   └── exec-planner.agent.md   # Plan creation/amendment
│
├── QA/                         # Quality Assurance department
│   ├── qa-reviewer.agent.md    # Quality gate (dispatches analyzers)
│   ├── qa-test-analyzer.agent.md   # Test coverage → QA-TestGenerator
│   ├── qa-test-generator.agent.md  # Test generation
│   ├── qa-docs-analyzer.agent.md   # Doc coverage → QA-DocsGenerator
│   ├── qa-docs-generator.agent.md  # Documentation generation
│   └── qa-subagent.agent.md        # Standalone QA utility agent
│
├── RnD/                        # Research & Design department
│   ├── rnd-dd-author.agent.md      # Design document creation
│   ├── rnd-ideator.agent.md        # Creative solution generation
│   ├── rnd-architect.agent.md      # Implementation options analysis
│   ├── rnd-estimator.agent.md      # Effort sizing
│   ├── rnd-improver.agent.md       # Iterative refinement
│   └── rnd-complexity-advisor.agent.md  # Over-engineering detection
│
└── Support/                    # Shared support services
    ├── support-researcher.agent.md     # Deep codebase/external research
    ├── support-debugger.agent.md       # Root cause analysis
    ├── support-librarian.agent.md      # Artifact corpus navigation (ADRs/logs/DDs)
    └── support-pattern-enforcer.agent.md       # Pattern consistency discovery
```

## Spawn Hierarchy

```
Director
├── Support-Librarian    (artifact context before dispatch)
├── RnD-Manager
│   ├── Support-Librarian    (artifact context before design)
│   ├── RnD-DDAuthor → Support-Researcher, Support-Librarian
│   ├── RnD-Ideator
│   ├── RnD-Architect → Support-Researcher
│   ├── RnD-Estimator
│   ├── RnD-Improver
│   ├── RnD-ComplexityAdvisor
│   ├── Support-PatternEnforcer  (DD validation gate)
│   └── Support-Researcher
├── Exec-Planner → Support-Researcher, Support-Librarian
├── Support-PatternEnforcer  (DD/plan validation gate)
├── Support-Researcher
├── Support-Debugger
└── Exec-Manager
    ├── Exec-Executor
    ├── QA-Reviewer
    │   ├── QA-TestAnalyzer → QA-TestGenerator
    │   └── QA-DocsAnalyzer → QA-DocsGenerator
    ├── Exec-Fixer
    └── Exec-Planner
```

**Key principle:** RnD-Manager owns exploration and design. Exec-Manager owns execution. Director coordinates between them. Support agents are shared services any department can request.

---

## Agent Roster

### Executive (Root)

| Agent | Purpose | Spawns |
|-------|---------|--------|
| `Director` | Top-level orchestrator for multi-plan features | RnD-Manager, Exec-Planner, Exec-Manager, Support-Researcher, Support-Debugger, Support-PatternEnforcer, Support-Librarian |
| `RnD-Manager` | R&D department head — exploration, design, analysis | RnD-DDAuthor, all RnD advisors, Support-PatternEnforcer, Support-Librarian, Support-Researcher |
| `Exec-Manager` | Owns one plan's full lifecycle | Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner |

### R&D Department (`RnD/`)

| Agent | Purpose | Spawns |
|-------|---------|--------|
| `RnD-DDAuthor` | Creates design docs from requirements | RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher, Support-Librarian |
| `RnD-Ideator` | Creative solution generation — default first step for most R&D work | — |
| `RnD-Architect` | Implementation options with tradeoff analysis | Support-Researcher |
| `RnD-Estimator` | Effort sizing (TRIVIAL → EPIC) — use to scope before committing | — |
| `RnD-Improver` | Iterative refinement loop — polishes any agent's output | — |
| `RnD-ComplexityAdvisor` | Identifies over-engineering and unnecessary abstraction | — |

### Plan Execution (`Exec/`)

| Agent | Purpose | Spawns |
|-------|---------|--------|
| `Exec-Executor` | Implements one phase of a plan | — |
| `Exec-Planner` | Creates or amends plan files | Support-Researcher, Support-Librarian |
| `Exec-Fixer` | Targeted repairs from review issues | — |

### Quality Assurance (`QA/`)

| Agent | Purpose | Spawns |
|-------|---------|--------|
| `QA-Reviewer` | Quality gate with test/docs verification | QA-TestAnalyzer, QA-DocsAnalyzer |
| `QA-TestAnalyzer` | Test coverage analysis with self-repair | QA-TestGenerator |
| `QA-TestGenerator` | Generates tests to fill gaps | — |
| `QA-DocsAnalyzer` | Documentation analysis with self-repair | QA-DocsGenerator |
| `QA-DocsGenerator` | Generates/updates documentation | — |

### Support (`Support/`) — Shared Services

| Agent | Purpose | Spawns |
|-------|---------|--------|
| `Support-Researcher` | Deep codebase/external research | — |
| `Support-Debugger` | Root cause analysis for failures | — |
| `Support-Librarian` | Searches artifact corpus (ADRs, logs, DDs) for relevant context | — |
| `Support-PatternEnforcer` | Finds where a pattern should apply across the codebase | — |

---

## Contracts

### Input (All Agents)

```yaml
contextFiles:      # Files to read BEFORE starting work
  - artifacts/plans/pending/TASK-{feature}-{letter}-*.md
  - artifacts/designs/parts/{feature}/CONTRACTS.md
  - artifacts/designs/parts/{feature}/README.md
  - artifacts/designs/pending/DD-{feature}.md
  - .github/instructions/{layer}.instructions.md
```

Task-specific parameters go in a structured `task:` section, not prose summaries.

### Output (All Agents)

```yaml
status: DONE | BLOCKED | ESCALATE
summary: "One-line outcome"
artifacts:
  - path: "..."
    action: created | modified | deleted
annotations:
  - "..."
blockers:           # Only if status != DONE
  - type: PLANNING_GAP | DEPENDENCY | EXTERNAL | UNKNOWN
    detail: "..."
nextAction:         # Optional
  type: DISPATCH_FIXER | AMEND_PLAN | DISCUSS | CONTINUE
  reason: "..."
```

---

## Rules

1. **Director is for multi-plan coordination.** For simpler work, invoke managers directly.
2. **RnD-Manager and Exec-Manager are directly invokable** — no Director required for single-plan or focused R&D work.
3. **Ideator is the default first step** for most RnD-Manager requests. Even "design this feature" benefits from exploring the solution space first.
4. **Improver is a refinement loop.** After any agent produces output, Improver can iterate on it looking for optimizations and edge cases.
5. **Estimator scopes everything.** Run it before committing to multi-agent workflows to right-size effort.
6. **Support agents are shared services.** Any department can request Support-Researcher, Support-Debugger, or Support-PatternEnforcer.
7. **Advisory agents are read-only** — RnD-Ideator, RnD-Architect, RnD-Estimator, RnD-Improver, RnD-ComplexityAdvisor, Support-PatternEnforcer return reports, not code.
8. **Leaf agents spawn nothing** — Exec-Executor, Exec-Fixer, Support-Researcher, Support-Debugger, Support-PatternEnforcer, QA-TestGenerator, QA-DocsGenerator, RnD-Ideator, RnD-Estimator, RnD-Improver, RnD-ComplexityAdvisor.
9. **Escalation is explicit** — `status: ESCALATE` means "I need human/Director input."
10. **Files are the handoff** — agents read files, write to files, report file paths. No prose summaries.
11. **Annotations compound** — each agent adds to plan file annotations. Nothing gets lost.

---

## Dispatch Example

Director prompt:
```
Dispatch Exec-Manager for Plan B.

contextFiles:
  - artifacts/plans/pending/TASK-schema-refactor-v1-B-library-files.md
  - artifacts/designs/parts/schema-refactor-v1/CONTRACTS.md
  - artifacts/designs/parts/schema-refactor-v1/README.md
  - artifacts/designs/pending/DD-schema-refactor-v1.md
  - .github/instructions/persistence.instructions.md
  - .github/instructions/workflows.instructions.md

task:
  plan: TASK-schema-refactor-v1-B-library-files
  startPhase: 1
  reviewRequired: true
```

Exec-Manager returns:
```yaml
status: DONE
summary: "Plan B complete: 7 phases, 33 steps, 1 fix cycle"
artifacts:
  - path: nomarr/persistence/database/library_files_aql/queries.py
    action: modified
  - path: nomarr/persistence/database/library_files_aql/crud.py
    action: modified
annotations:
  - "Fixed 8 methods that still referenced library_id after Phase 4"
  - "Review Round 2 passed"
blockers: []
```

Director only knows: Plan B done, moved on to Plan C.
