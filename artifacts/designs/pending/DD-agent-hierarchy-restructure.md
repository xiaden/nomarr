# Agent Hierarchy Restructure — Design Document

**Status:** Draft  
**Author:** RnD-Manager audit  
**Created:** 2026-04-01

**Related Documents:**

- [.github/agents/README.md](../../.github/agents/README.md) — Current hierarchy specification
- [.github/instructions/agents.instructions.md](../../.github/instructions/agents.instructions.md) — Agent file guidelines
- [.github/skills/feature-planning/SKILL.md](../../.github/skills/feature-planning/SKILL.md) — Multi-plan planning skill
- [.github/skills/feature-execution/SKILL.md](../../.github/skills/feature-execution/SKILL.md) — Multi-plan execution skill

---

## Scope

This document covers:

1. Full audit of all 24 agent files and their actual vs. documented relationships
2. Identification of contradictions, orphans, gaps, and overlaps
3. Proposed department structure with clear boundaries
4. Agent roster per department — reassignments + new agents + deletions
5. Corrected spawn chains and fast-path rules
6. Migration path from current to proposed state

**Out of scope:** Individual agent instruction rewrites (those go in implementation plans).

---

## Problem Statement

The agent hierarchy has proven its value — the Director → Manager → Executor pattern works for complex multi-plan features. However, the implementation has drifted from the documented design:

1. **Director's spawn list contradicts its documentation** — Description and body reference 5 agents (including Support-Researcher, Support-Debugger), but the YAML `agents` field only lists 3 (RnD-Manager, Exec-Planner, Exec-Manager). Director literally cannot spawn agents it tells itself to spawn.

2. **QA subagent is an orphan** — `qa-subagent.agent.md` (name: "QA") exists with broad tools and `agent` spawn capability but is not referenced by any other agent. Its name risks confusion with the formal QA-Reviewer chain.

3. **Exec-Planner has three access paths** — Director → Exec-Planner (initial planning), Exec-Manager → Exec-Planner (amendment), User → Exec-Planner (standalone). This is intentional but undocumented, making ownership ambiguous.

4. **Planning is fragmented across three mechanisms** — The `feature-planning` skill, the Exec-Planner agent, and the `create-plan.prompt.md` prompt all handle planning with different orchestration levels and no clear ownership rules.

5. **No QA Manager exists** — QA agents are only accessible within Exec-Manager's internal review cycle. There's no way to invoke QA independently of execution.

6. **DDAuthor cross-department handoff** — RnD-DDAuthor has a handoff button to Exec-Planner (a non-R&D agent), creating an implied cross-department transition that bypasses the Director.

7. **No fast-path documentation** — The README says "for simpler work, invoke managers/agents directly" but provides no guidance on what qualifies as "simpler."

---

## Phase 1 Audit: Complete Agent Catalog

### All Agent Files (24 total)

 | # | File | Name | Dep't (implied) | Role | Can Spawn | User-Invocable | Notes |
 | --- | ------ | ------ | ----------------- | ------ | ----------- | ---------------- | ------- |
 | 1 | `agent.agent.md` | Agent | Default | God-mode default context | `[*]` (all) | Yes | Base agent — reasonable |
 | 2 | `director.agent.md` | Director | Executive | Top-level orchestrator | `[RnD-Manager, Exec-Planner, Exec-Manager]` | Yes | **Missing Support-Researcher, Support-Debugger in agents list** |
 | 3 | `rnd-manager.agent.md` | RnD-Manager | R&D | Department head | `[RnD-DDAuthor, RnD-Ideator, RnD-Architect, RnD-Estimator, RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor, Support-Researcher]` | Yes | Well-structured |
 | 4 | `rnd-dd-author.agent.md` | RnD-DDAuthor | R&D | Design doc creation | `[RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher]` | Yes | Has cross-department handoff to Exec-Planner |
 | 5 | `rnd-ideator.agent.md` | RnD-Ideator | R&D | Creative solutions | `[]` | Yes | Leaf. Read-only |
 | 6 | `rnd-architect.agent.md` | RnD-Architect | R&D | Implementation options | `[Support-Researcher]` | Yes | Leaf-ish. Spawns researcher only |
 | 7 | `rnd-estimator.agent.md` | RnD-Estimator | R&D | Effort sizing | `[]` | Yes | Leaf. Read-only |
 | 8 | `rnd-pattern-enforcer.agent.md` | RnD-PatternEnforcer | R&D | Pattern consistency | `[]` | Yes | Leaf. Read-only |
 | 9 | `rnd-improver.agent.md` | RnD-Improver | R&D | Enhancement suggestions | `[]` | Yes | Leaf. Read-only |
 | 10 | `rnd-complexity-advisor.agent.md` | RnD-ComplexityAdvisor | R&D | Complexity analysis | `[]` | Yes | Leaf. Read-only |
 | 11 | `exec-manager.agent.md` | Exec-Manager | Execution | Plan lifecycle owner | `[Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner]` | Yes | Well-structured |
 | 12 | `exec-executor.agent.md` | Exec-Executor | Execution | Phase implementation | `[]` | No | Leaf. Correct |
 | 13 | `exec-fixer.agent.md` | Exec-Fixer | Execution | Targeted repairs | `[]` | No | Leaf. Correct |
 | 14 | `exec-planner.agent.md` | Exec-Planner | Planning/Shared | Plan creation/amendment | `[Support-Researcher]` | Yes | **Triple-owned: Director, Exec-Manager, user** |
 | 15 | `qa-reviewer.agent.md` | QA-Reviewer | QA | Quality gate | `[QA-TestAnalyzer, QA-DocsAnalyzer]` | No | Only accessible via Exec-Manager |
 | 16 | `qa-test-analyzer.agent.md` | QA-TestAnalyzer | QA | Test coverage analysis | `[QA-TestGenerator]` | No | Self-repairs via generator |
 | 17 | `qa-test-generator.agent.md` | QA-TestGenerator | QA | Test generation | `[]` | No | Leaf |
 | 18 | `qa-docs-analyzer.agent.md` | QA-DocsAnalyzer | QA | Doc coverage analysis | `[QA-DocsGenerator]` | Yes | Oddly user-invocable when designed as sub-agent of QA-Reviewer |
 | 19 | `qa-docs-generator.agent.md` | QA-DocsGenerator | QA | Doc generation | `[]` | Yes | Oddly user-invocable when designed as sub-agent |
 | 20 | `qa-subagent.agent.md` | QA | QA | General QA engineer | Has `agent` tool | Yes | **ORPHAN — not in any hierarchy, broad tools, name confusing** |
 | 21 | `support-researcher.agent.md` | Support-Researcher | Support | Deep research | `[]` | Yes | Shared resource. Well-designed |
 | 22 | `support-debugger.agent.md` | Support-Debugger | Support | Root cause analysis | `[]` | Yes | Shared resource. Well-designed |
 | 23 | `test-probe.agent.md` | test-probe | Test | Test harness | `[]` | Yes | Not a real agent — instruction injection test |
 | 24 | `README.md` | — | — | Documentation | — | — | Describes hierarchy |

### Spawn Chain Map (Actual YAML)

```
Agent (god mode) → [*]

Director → [RnD-Manager, Exec-Planner, Exec-Manager]  ← MISSING 2

RnD-Manager → [RnD-DDAuthor, RnD-Ideator, RnD-Architect, RnD-Estimator,
               RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor,
               Support-Researcher]

RnD-DDAuthor → [RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher]

RnD-Architect → [Support-Researcher]

Exec-Manager → [Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner]

Exec-Planner → [Support-Researcher]

QA-Reviewer → [QA-TestAnalyzer, QA-DocsAnalyzer]

QA-TestAnalyzer → [QA-TestGenerator]

QA-DocsAnalyzer → [QA-DocsGenerator]

(All others are leaf agents with no spawn capability)
```

### Handoff Map (UI workflow transitions)

```
Director
  → RnD-Manager:  "Explore options and create a design"
  → Exec-Planner: "Create an implementation plan from the design document"
  → Exec-Manager:  "Execute the implementation plan"

RnD-Manager
  → RnD-DDAuthor: "Create a design document"
  → RnD-Ideator:  "Generate creative solutions"
  → RnD-Architect: "Analyze implementation options"

RnD-DDAuthor
  → RnD-Ideator:  "Generate creative solutions"
  → RnD-Architect: "Analyze implementation options"
  → Exec-Planner: "Create implementation plans" ← Cross-department

Exec-Planner
  → Exec-Manager: "Execute the plan I just created"
```

---

## Phase 2: Department Analysis

### Department 1: Executive

**Status:** Exists, has critical bugs.  
**Current members:** Director  
**Purpose:** Strategic routing for complex multi-plan features

#### What Works

- Director's dispatch-first philosophy is correct — it has no file/code tools, only spawn and ask
- Routing table in body is clear and well-documented
- Status tracking protocol is well-specified

#### What's Broken

- `agents` YAML: `[RnD-Manager, Exec-Planner, Exec-Manager]` — missing Support-Researcher and Support-Debugger
- Director's body says "spawn Support-Researcher" for file reading and "spawn Support-Debugger" for failures, but it literally cannot
- This means Director is **blind** — it cannot gather any information before making routing decisions

#### What's Missing

- Fast-path rules: when to skip Director entirely
- Session continuity: how Director resumes an interrupted feature

---

### Department 2: R&D

**Status:** Well-structured. Minor issues only.  
**Current members:** RnD-Manager, RnD-DDAuthor, RnD-Ideator, RnD-Architect, RnD-Estimator, RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor  
**Purpose:** Exploration, design, analysis — the "thinking" phase

#### What Works

- Clear department head (RnD-Manager) with 8 sub-agents
- Advisory agents are properly read-only
- DDAuthor has appropriate spawn chain (Ideator, Architect, Estimator, Researcher)
- Manager has full department access plus Support-Researcher
- Clear output contracts (design docs, reports, recommendations)

#### What's Broken

- RnD-DDAuthor has a handoff button to Exec-Planner. This is a UI convenience (user clicks to transition), not a spawn violation, but it implies a workflow that bypasses Director. Should be documented as "user-driven transition" not "automatic flow."

#### What's Missing

- Nothing critical. The R&D department is the best-structured department.
- Could benefit from explicit documentation of the DDAuthor → user → Exec-Planner transition as an expected workflow.

---

### Department 3: Planning

**Status:** Fragmented across three mechanisms. No clear owner.  
**Current members:** Exec-Planner (agent), feature-planning (skill), create-plan (prompt)  
**Purpose:** Creating implementation plans from designs or requirements

#### What Works

- Exec-Planner agent is well-written with clear input/output contracts
- feature-planning skill orchestrates multi-plan decomposition well
- create-plan prompt handles lightweight plan creation

#### What's Broken

**Three planning mechanisms with no routing rules:**

 | Mechanism | Scope | When to Use | Who Decides? |
 | ----------- | ------- | ------------- | -------------- |
 | `create-plan.prompt.md` | Single plan from user context | Quick single plans | User |
 | `Exec-Planner` agent | Single plan from design doc | Plan creation or amendment | Director or Exec-Manager |
 | `feature-planning` skill | Multi-plan decomposition | Large features with dependencies | User (invokes skill) |

No documentation tells the user or Director which mechanism to use when. The feature-planning skill internally dispatches Exec-Planner agents, but this relationship is only documented in the skill file, not in the hierarchy README.

#### What's Missing

- Routing rules: when each mechanism is appropriate
- Documentation of the skill → agent relationship
- The "Exec-" prefix on Planner implies it belongs to Execution, but it's used independently for initial planning

---

### Department 4: Execution

**Status:** Well-structured internally. Clean.  
**Current members:** Exec-Manager, Exec-Executor, Exec-Fixer  
**Purpose:** Implementing plans through phase-by-phase execution

#### What Works

- Exec-Manager owns the full lifecycle: Execute → Review → Fix → Re-review
- Exec-Executor is properly scoped (one phase, no spawn)
- Exec-Fixer is properly scoped (targeted repairs, no broadening)
- Max fix cycle limit (2 rounds then escalate) prevents infinite loops
- feature-execution skill provides multi-plan orchestration on top

#### What's Broken

- Exec-Manager spawns QA-Reviewer, putting QA under Execution's control. This is architecturally questionable — QA should be independent to avoid the fox guarding the henhouse.
- However, practically this works fine because QA-Reviewer's instructions are self-contained and it doesn't take orders from Exec-Manager beyond "review these files."

#### What's Missing  

- Nothing critical for the execution cycle itself.

---

### Department 5: Quality Assurance

**Status:** Embedded in Execution. Has an orphan.  
**Current members:**  

- Formal chain: QA-Reviewer → (QA-TestAnalyzer → QA-TestGenerator), (QA-DocsAnalyzer → QA-DocsGenerator)  
- Orphan: QA (qa-subagent.agent.md)  
**Purpose:** Quality verification (code review, test coverage, documentation)

#### What Works

- QA-Reviewer is well-specified with 8 verification categories
- Self-repair pattern (Analyzer spawns Generator) is elegant
- Severity classification (MINOR/PLANNING_GAP/CRITICAL) drives correct routing

#### What's Broken

**1. QA subagent orphan:**

- `qa-subagent.agent.md` (name: "QA") is a generic QA engineer with broad tools
- It has the `agent` tool (can spawn others) but no `agents` list
- Not referenced by any other agent in the hierarchy
- Not documented in the README's hierarchy tree  
- Its name "QA" could shadow or confuse with the QA-Reviewer chain
- It appears to be a standalone "QA mode" for direct user interaction — useful but undocumented

**2. No independent QA access:**

- QA-Reviewer can only be spawned by Exec-Manager
- There's no way for Director to commission an independent quality review outside of execution
- QA-DocsAnalyzer and QA-DocsGenerator are marked `user-invocable: true` but QA-Reviewer and QA-TestAnalyzer are `user-invocable: false` — inconsistent

**3. No QA Manager:**

- Six QA-related agents exist but no coordinator
- The QA subagent (orphan) could serve this role but isn't configured to

#### What's Missing

- A way to invoke QA independently of execution
- Clear ownership of the QA subagent
- Consistent `user-invocable` settings across QA agents

---

### Department 6: Support

**Status:** Well-designed as shared resources. Access gap from Director.  
**Current members:** Support-Researcher, Support-Debugger  
**Purpose:** Information gathering and failure analysis

#### What Works

- Both are well-specified with clear input/output contracts
- Properly read-only (Researcher) / diagnose-only (Debugger)
- Support-Researcher is correctly available to multiple departments (RnD-Manager, RnD-DDAuthor, RnD-Architect, Exec-Planner)
- Both are user-invocable for standalone use

#### What's Broken

- **Director cannot spawn either one** despite its instructions requiring it
- Director says: "spawn Support-Researcher" to read files, "spawn Support-Debugger" when things break
- But `agents: [RnD-Manager, Exec-Planner, Exec-Manager]` excludes both
- This is the single most impactful bug in the hierarchy

#### What's Missing

- Nothing beyond fixing the Director access gap

---

### Department 7: Not a Department

**Members:** test-probe  
**Status:** Test harness for instruction injection validation. Not a real agent.  
**Action:** Document as test fixture, add `user-invocable: false`.

---

## Phase 3: Specific Problems and Solutions

### Problem 1: Director's Routing Gap

**Root cause:** YAML `agents` field missing two agents.  
**Impact:** CRITICAL — Director is blind. Cannot gather information before routing.

**Fix:**

```yaml
# director.agent.md frontmatter
agents: [RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]
```

This aligns the YAML with the already-documented behavior, plus the new QA-Reviewer access.

---

### Problem 2: Research/Investigation Capability from Director

**Current state:** Director body says "spawn Support-Researcher" for any file/codebase questions. But can't.  
**After Problem 1 fix:** Director gains research capability. No additional changes needed.

**Alternative considered and rejected:** Give Director read tools directly. This would violate its core principle: "You have NO information-gathering tools." Director should remain a pure orchestrator.

---

### Problem 3: Planning Ownership

**Current state:** Three mechanisms, no routing rules.  
**Proposed solution:** Document routing rules rather than reorganize.

The three mechanisms serve genuinely different use cases:

 | Use Case | Mechanism | Invoked By |
 | ---------- | ----------- | ------------ |
 | Quick single plan from attached context | `create-plan.prompt.md` | User directly |
 | Single plan from design document | `Exec-Planner` agent | Director, Exec-Manager, or user directly |
 | Multi-plan decomposition from design | `feature-planning` skill | User directly (orchestrates Exec-Planner internally) |

**Action:** Add a "Planning Mechanisms" section to README.md documenting when each is appropriate.

**Naming concern:** The `Exec-` prefix on `Exec-Planner` implies it belongs to the Execution department, but it's equally used for initial planning. However, renaming would break existing references in skills and prompts. **Recommendation: keep the name, document that it's a shared resource like Support agents.**

---

### Problem 4: RnD Scope

**Current state:** RnD-Manager owns exploration and design. Produces design documents. Does NOT produce plans.  
**Proposed: No change.** This boundary is correct:

- R&D produces **what** to build and **why** (design docs)
- Planning produces **how** to build it (plan files with phases/steps)
- Execution **builds** it

If R&D also produced plans, the Design → Plan boundary would blur; design decisions and implementation details would intermingle.

**RnD-DDAuthor's handoff to Exec-Planner** is the correct bridge: after completing a design doc, DDAuthor suggests the user transition to planning. This is a workflow convenience, not a hierarchy violation.

---

### Problem 5: QA as a Department

**Proposed: Promote QA-Reviewer to independent access. Don't create a QA Manager.**

**Rationale against a QA Manager:**

- QA's current workload doesn't justify a manager layer
- QA-Reviewer already orchestrates TestAnalyzer + DocsAnalyzer
- Adding a QA Manager creates: Director → QA-Manager → QA-Reviewer → QA-TestAnalyzer → QA-TestGenerator (4 levels of dispatch for a test review)

**Proposed changes instead:**

1. **Rename `qa-subagent.agent.md` → `qa-engineer.agent.md`** with name "QA-Engineer"
   - Disambiguates from the formal QA-Reviewer chain
   - Clear identity: standalone QA for direct user interaction

2. **Add QA-Reviewer to Director's spawn list**
   - Enables Director to commission independent quality reviews outside of execution
   - Director: `[RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]`

3. **Make QA-Reviewer user-invocable**
   - Currently `user-invocable: false`
   - Users should be able to request a quality review directly

4. **Standardize user-invocable across QA agents:**
   - QA-Reviewer: `true` (entry point)
   - QA-Engineer: `true` (standalone mode)
   - QA-TestAnalyzer: `false` (sub-agent of Reviewer)
   - QA-TestGenerator: `false` (sub-agent of TestAnalyzer)
   - QA-DocsAnalyzer: `false` (sub-agent of Reviewer)
   - QA-DocsGenerator: `true` (keep — useful for standalone doc generation)

---

### Problem 6: The Simple Task Problem

**Current state:** No documentation on when to use Agent (default) vs. Director vs. specific agents.  
**Proposed: Add "Task Routing Guide" to README.md.**

 | Task Type | Route | Example |
 | ----------- | ------- | --------- |
 | Quick fix, single file | Agent (default) | "Fix this lint error" |
 | Well-defined change, known scope | Agent (default) | "Add a parameter to this method" |
 | Explore options, design | RnD-Manager directly | "What's the best way to handle X?" |
 | Create a plan from known design | Exec-Planner directly | "Create a plan from this design doc" |
 | Execute a single existing plan | `execute-plan` prompt | "Execute TASK-feature-A-foundation" |
 | Execute multi-plan feature | Director or `feature-execution` skill | "Execute all plans for schema-refactor" |
 | Quality review of changes | QA-Reviewer directly | "Review the changes in this PR" |
 | Investigate codebase | Support-Researcher directly | "How does the scan pipeline work?" |
 | Debug a failure | Support-Debugger directly | "This test is failing, why?" |
 | Full feature lifecycle | Director | Multi-plan feature from idea to completion |

**Key principle:** Director is for **coordination**, not gatekeeping. Most tasks don't need Director.

---

### Problem 7: Agent Naming Conventions

**Current naming pattern:** `{department}-{role}` (e.g., `RnD-Ideator`, `Exec-Manager`, `QA-Reviewer`)

**Issues found:**

 | Agent | Issue |
 | ------- | ------- |
 | `qa-subagent` | Name implies subordination but it's standalone. Rename to `QA-Engineer` |
 | `Exec-Planner` | `Exec-` prefix implies Execution department but it's shared. Document, don't rename |
 | `Agent` | Generic name, fine for default mode |
 | `test-probe` | Doesn't follow naming convention. Fine — it's a test harness |

**Recommendation:** Minimal renames. The naming convention mostly works.

---

## Phase 4: Proposed Architecture

### Department Structure

```
┌──────────────────────────────────────────────────────┐
│                     USER                              │
│  Can directly invoke any user-invocable agent         │
└───────────┬──────────────────────────────────────────┘
            │
            ├── Agent (default mode — full tools, any task)
            │
            ├── Director (orchestrator — multi-plan features only)
            │     ├── RnD-Manager
            │     ├── Exec-Planner
            │     ├── Exec-Manager
            │     ├── QA-Reviewer        ← NEW
            │     ├── Support-Researcher  ← FIX
            │     └── Support-Debugger    ← FIX
            │
            ├── RnD-Manager (direct R&D access)
            │     ├── RnD-DDAuthor  → [Ideator, Architect, Estimator, Researcher]
            │     ├── RnD-Ideator
            │     ├── RnD-Architect → [Researcher]
            │     ├── RnD-Estimator
            │     ├── RnD-PatternEnforcer
            │     ├── RnD-Improver
            │     ├── RnD-ComplexityAdvisor
            │     └── Support-Researcher
            │
            ├── Exec-Planner (direct planning access)
            │     └── Support-Researcher
            │
            ├── Exec-Manager (direct execution access)
            │     ├── Exec-Executor
            │     ├── QA-Reviewer → [TestAnalyzer → TestGenerator,
            │     │                  DocsAnalyzer → DocsGenerator]
            │     ├── Exec-Fixer
            │     └── Exec-Planner → [Researcher]
            │
            ├── QA-Reviewer (direct QA access)         ← NEW access path
            │     ├── QA-TestAnalyzer → QA-TestGenerator
            │     └── QA-DocsAnalyzer → QA-DocsGenerator
            │
            ├── QA-Engineer (standalone QA mode)        ← RENAMED from qa-subagent
            │
            ├── Support-Researcher (direct research)
            ├── Support-Debugger (direct debugging)
            └── test-probe (test harness — not a real agent)
```

### Agent Roster per Department

#### Executive Department

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | Director | **MODIFY** | Add Support-Researcher, Support-Debugger, QA-Reviewer to `agents` list |

#### R&D Department

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | RnD-Manager | None | Well-structured |
 | RnD-DDAuthor | None | Handoff to Exec-Planner is a UI convenience, documented |
 | RnD-Ideator | None | |
 | RnD-Architect | None | |
 | RnD-Estimator | None | |
 | RnD-PatternEnforcer | None | |
 | RnD-Improver | None | |
 | RnD-ComplexityAdvisor | None | |

#### Execution Department

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | Exec-Manager | None | Well-structured |
 | Exec-Executor | None | |
 | Exec-Fixer | None | |

#### Planning (Shared Resource)

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | Exec-Planner | **DOCUMENT** | Add "shared resource" designation in README |

#### QA Department

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | QA-Reviewer | **MODIFY** | Set `user-invocable: true` |
 | QA-TestAnalyzer | None | |
 | QA-TestGenerator | None | |
 | QA-DocsAnalyzer | **MODIFY** | Set `user-invocable: false` (sub-agent only) |
 | QA-DocsGenerator | None | Keep `user-invocable: true` for standalone doc gen |
 | QA-Engineer | **RENAME** from qa-subagent | New name, disambiguated |

#### Support (Shared Resources)

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | Support-Researcher | None | Well-designed |
 | Support-Debugger | None | Well-designed |

#### Not a Department

 | Agent | Change | Notes |
 | ------- | -------- | ------- |
 | Agent | None | Default mode |
 | test-probe | **MODIFY** | Add `user-invocable: false` |

### Spawn Chains (Proposed — No Ambiguity)

```yaml
# Definitive spawn chains
Director:
  agents: [RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]
  purpose: Strategic routing only. No tools except spawn + ask.

RnD-Manager:
  agents: [RnD-DDAuthor, RnD-Ideator, RnD-Architect, RnD-Estimator, RnD-PatternEnforcer, RnD-Improver, RnD-ComplexityAdvisor, Support-Researcher]
  purpose: R&D department head. Dispatches advisory agents and DDAuthor.

RnD-DDAuthor:
  agents: [RnD-Ideator, RnD-Architect, RnD-Estimator, Support-Researcher]
  handoffs: [Exec-Planner]  # UI transition, not spawn
  purpose: Design doc creation. Sub-agents for input gathering.

RnD-Architect:
  agents: [Support-Researcher]
  purpose: Deep implementation analysis.

Exec-Manager:
  agents: [Exec-Executor, QA-Reviewer, Exec-Fixer, Exec-Planner]
  purpose: Plan lifecycle. Owns execute/review/fix cycle.

Exec-Planner:
  agents: [Support-Researcher]
  handoffs: [Exec-Manager]  # UI transition, not spawn
  purpose: Plan creation/amendment. Shared between Director and Exec-Manager.

QA-Reviewer:
  agents: [QA-TestAnalyzer, QA-DocsAnalyzer]
  purpose: Quality gate. Accessible from Director OR Exec-Manager.

QA-TestAnalyzer:
  agents: [QA-TestGenerator]
  purpose: Test coverage analysis with self-repair.

QA-DocsAnalyzer:
  agents: [QA-DocsGenerator]
  purpose: Doc coverage analysis with self-repair.

# All others: leaf agents (no spawn capability)
```

### Fast-Path Rules

```
IF task is a quick fix or single-file change
  → Use Agent (default mode)
  → No dispatch needed

IF task is well-defined with known scope
  → Use appropriate specialist directly:
    - Codebase question → Support-Researcher
    - Design question → RnD-Manager or advisory agent
    - Create plan → Exec-Planner or create-plan prompt
    - Execute plan → execute-plan prompt
    - Quality review → QA-Reviewer
    - Debug failure → Support-Debugger

IF task requires multi-plan coordination
  → Use Director
  → Director dispatches department heads

IF task requires multi-plan planning but not execution
  → Use feature-planning skill

IF task requires multi-plan execution with existing plans
  → Use feature-execution skill or Director
```

---

## Design Goals

 | Goal | Rationale |
 | ------ | ----------- |
 | Fix Director blindness | Director must be able to gather information before routing |
 | Minimal restructuring | The hierarchy mostly works; don't reorganize what isn't broken |
 | QA independence | QA should be invocable outside of execution cycles |
 | Clear routing rules | Users and Director need to know which mechanism to use when |
 | No new agents | The roster is large enough; solve problems by fixing connections |
 | Documented fast paths | Not every task needs the full pipeline |

---

## Migration Path

### Phase A: Fix Director (Critical — Unblocks Everything)

**Files modified:** 1

1. `director.agent.md` — Update `agents` list and routing table:

   ```yaml
   agents: [RnD-Manager, Exec-Planner, Exec-Manager, QA-Reviewer, Support-Researcher, Support-Debugger]
   ```

2. Add QA routing row to Director's body routing table:

   ```
 | "Review this code/PR" | **QA-Reviewer** | 
   ```

### Phase B: Fix QA Department

**Files modified:** 3, **Files renamed:** 1

1. `qa-subagent.agent.md` → rename to `qa-engineer.agent.md`
   - Change `name` from `QA` to `QA-Engineer`
   - Update description to clarify standalone QA role
   - Remove `agent` tool from tools list (leaf agent, shouldn't spawn)

2. `qa-reviewer.agent.md` — Remove `user-invocable: false` (default is `true`)

3. `qa-docs-analyzer.agent.md` — Add `user-invocable: false`

### Phase C: Update README.md

**Files modified:** 1

1. `.github/agents/README.md` — Major update:
   - Update hierarchy tree to match actual spawn chains (including Director's full list)
   - Add "Planning Mechanisms" section documenting three planning approaches
   - Add "Task Routing Guide" section with fast-path rules
   - Add "Shared Resources" section documenting Exec-Planner and Support agents
   - Update agent table to include QA-Engineer (renamed)
   - Remove QA (old name) from table
   - Add note about test-probe being a test harness
   - Document handoffs as "UI workflow transitions" distinct from spawn chains

### Phase D: Clean Up test-probe

**Files modified:** 1

1. `test-probe.agent.md` — Add `user-invocable: false` to frontmatter

### Total Changes

 | Change Type | Count | Files |
 | ------------- | ------- | ------- |
 | Modify frontmatter | 4 | director, qa-reviewer, qa-docs-analyzer, test-probe |
 | Rename file | 1 | qa-subagent → qa-engineer |
 | Modify body content | 1 | director (add QA routing) |
 | Rewrite documentation | 1 | README.md |
 | **Total files touched** | **6** | |
 | New files | 0 | |
 | Deleted files | 0 | |

---

## Decisions Requiring User Input

### Decision 1: Director → QA-Reviewer Access

**Proposed:** Add QA-Reviewer to Director's agents list, enabling independent quality reviews outside of execution.

**Trade-off:** This gives Director 6 agents to manage (up from 3 currently, 5 documented). More routing complexity but more capability.

**Alternative:** Keep QA-Reviewer only accessible via Exec-Manager. Director routes QA requests through Exec-Manager with a "review-only" flag.

**Recommendation:** Add to Director. The routing overhead of going through Exec-Manager for a simple review is wasteful.

### Decision 2: QA-Engineer (renamed qa-subagent) Scope

**Proposed:** Rename to QA-Engineer, keep as standalone mode, remove `agent` spawn capability.

**Alternative A:** Delete qa-subagent entirely. Its functionality is covered by Agent (default mode) + QA-Reviewer.

**Alternative B:** Promote to QA-Manager, give it the QA-Reviewer chain as sub-agents.

**Recommendation:** Rename and keep. It serves as a useful QA-focused mode for direct user interaction (test planning, bug hunting, edge-case analysis) that's distinct from the formal QA-Reviewer workflow.

### Decision 3: QA-DocsAnalyzer User-Invocability

**Proposed:** Set `user-invocable: false` since it's designed as a QA-Reviewer sub-agent.

**Alternative:** Keep `user-invocable: true` — users might want to run doc analysis independently.

**Recommendation:** Set to `false`. Users wanting doc analysis should use QA-DocsGenerator directly (which stays user-invocable) or QA-Reviewer for the full analysis cycle. The Analyzer is an intermediate orchestration agent that spawns Generator anyway.

### Decision 4: Exec-Planner Naming

**Proposed:** Keep the name `Exec-Planner`, document it as a shared resource.

**Alternative:** Rename to `Planner` (removing the Exec- prefix to reflect shared ownership).

**Recommendation:** Keep name. Renaming breaks references in feature-planning skill, feature-execution skill, Director body, Exec-Manager body, DDAuthor handoff, and README. The documentation fix is cheaper.

---

## Open Questions

1. **Skill/Agent relationship documentation:** The feature-planning and feature-execution skills use agents internally but this isn't documented in the agent README. Should it be? Skills are user-facing orchestration; agents are the building blocks. The relationship exists but may over-complicate the README.

2. **Agent mode behavior:** When a user selects an agent in VS Code's chat picker, that agent's instructions become the "mode." This means agents serve dual purpose: spawnable sub-agents AND direct user modes. This is fine but undocumented.

3. **Agent tool list drift:** Several agents have large tool lists that may have drifted from what they actually need. A tool audit is separate from this hierarchy restructure but worth noting for future work.

---

## Appendix: Current vs. Proposed Director Spawn List

 | Agent | Current YAML | Documented | Proposed |
 | ------- | ------------- | ------------ | ---------- |
 | RnD-Manager | Yes | Yes | Yes |
 | Exec-Planner | Yes | Yes | Yes |
 | Exec-Manager | Yes | Yes | Yes |
 | Support-Researcher | No | Yes (desc + body) | Yes |
 | Support-Debugger | No | Yes (desc + body) | Yes |
 | QA-Reviewer | No | No | Yes (new) |

## Appendix: Agent User-Invocable Status

 | Agent | Current | Proposed | Rationale |
 | ------- | --------- | ---------- | ----------- |
 | Agent | true | true | Default mode |
 | Director | true | true | Feature orchestrator |
 | RnD-Manager | true | true | Direct R&D access |
 | RnD-DDAuthor | true | true | Direct design doc access |
 | RnD-Ideator | true | true | Direct ideation |
 | RnD-Architect | true | true | Direct architecture analysis |
 | RnD-Estimator | true | true | Direct estimation |
 | RnD-PatternEnforcer | true | true | Direct pattern audit |
 | RnD-Improver | true | true | Direct improvement suggestions |
 | RnD-ComplexityAdvisor | true | true | Direct complexity analysis |
 | Exec-Manager | true | true | Direct plan execution |
 | Exec-Executor | false | false | Internal to Exec-Manager |
 | Exec-Fixer | false | false | Internal to Exec-Manager |
 | Exec-Planner | true | true | Shared planning resource |
 | QA-Reviewer | false | **true** | Enable independent QA |
 | QA-TestAnalyzer | false | false | Internal to QA-Reviewer |
 | QA-TestGenerator | false | false | Internal to QA-TestAnalyzer |
 | QA-DocsAnalyzer | true | **false** | Sub-agent of QA-Reviewer |
 | QA-DocsGenerator | true | true | Standalone doc generation |
 | QA-Engineer | true | true | Renamed from QA/qa-subagent |
 | Support-Researcher | true | true | Shared resource |
 | Support-Debugger | true | true | Shared resource |
 | test-probe | true (implicit) | **false** | Test harness |
