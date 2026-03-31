---
name: feature-planning
description: Use when decomposing a major feature design into dependency-ordered implementation plans. Handles the full pipeline from design document to validated, cross-referenced plan files with minimal drift. Trigger when user mentions planning a large feature, breaking down a design doc into parts, creating implementation plans for multi-part work, or coordinating plans that span multiple sessions. Not for single plans or simple tasks — use the Plan subagent directly for those.
---

# Feature Planning

Pipeline for turning requirements or a design document into a set of validated, dependency-ordered implementation plans. Each plan is self-contained, references concrete codebase patterns, and declares its contracts for downstream plans.

```
Requirements → [DDAuthor] → Design Doc → Decompose → Initialize Ledger → Plan in Rounds → Cross-Validate
     ↓               ↓             ↓            ↓              ↓                    ↓                ↓
  Optional    DD Author agent   Already has  parts/README  CONTRACTS.md    plans/TASK-*-{A..Z}.md  Fixes
              for new features    one?
```

## Agent Integration

This skill may dispatch agents from the `.github/agents/` hierarchy:

| Agent | When Used |
|-------|-----------|
| `DDAuthor` | Phase 0: When requirements exist but no design doc |
| `Planner` | Phase 3: For each plan in dependency order |

See [.github/agents/README.md](../../agents/README.md) for agent specifications.

---

## Hard Rules

These exist because every one was violated during real usage and caused drift or errors.

1. **Never write plans directly.** Always dispatch to the Planner agent. Direct plan authoring skips codebase research and produces layer violations, wrong method signatures, and missing patterns.
2. **Never plan out of dependency order.** A plan referencing methods from an unplanned upstream part will guess signatures.
3. **Never skip the ledger update.** The contracts ledger is the only mechanism preventing cross-plan drift. Update it after every validated plan.
4. **Never batch-validate.** Validate each plan immediately after creation. Errors found after all plans exist require multi-file fixes.
5. **Never combine parts into one subagent call.** Each part gets its own dispatch with focused context.
6. **If context budget is exhausted, stop at the round boundary.** The ledger preserves all progress. A new session resumes cleanly.

---

## Phase 0: Create Design Document (Optional)

**Skip this phase if:** Design document already exists at `plans/dev/design-{feature}.md`

If the user has requirements but no design doc, dispatch the DDAuthor agent:

```yaml
# Dispatch to DDAuthor agent
contextFiles:
  - .github/copilot-instructions.md              # Architecture rules
  - .github/instructions/{relevant_layers}.instructions.md  # Layer patterns

task:
  type: CREATE
  title: "{feature title}"
  requirements:
    - "{requirement 1 from user}"
    - "{requirement 2 from user}"
  researchFocus:
    - "existing patterns for {similar feature}"
    - "current {domain} implementation"
```

**After DDAuthor returns:**
- If `status: DONE` → design doc created at `plans/dev/design-{feature}.md`, proceed to Phase 1
- If `status: NEEDS_DECISION` → present questions to user, re-dispatch with answers
- If `status: BLOCKED` → critical information missing, stop and discuss with user

**Present the design doc to the user for review before proceeding to decomposition.**

---

## Phase 1: Decompose

**Input:** Design document (e.g., `plans/dev/design-{feature}.md`)
**Output:** `plans/dev/{feature}-parts/README.md`

Read the design doc. Identify natural part boundaries:

| Criterion | Rule |
|---|---|
| Layer boundaries | Parts touching different architectural layers → separate |
| System boundaries | Backend vs plugin vs frontend → separate |
| Dependency depth | No part depends on more than 2 others |
| Session scope | Each part ≤ 12 plan steps (≤ 2 phases) |
| Diamond avoidance | If parts A→C and B→C share most context → merge A+B |

Assign letters (A, B, C...) in topological order. Group into execution rounds.

Create `plans/dev/{feature}-parts/README.md`:

```markdown
# {Feature} — Implementation Parts

## Parts

| Part | Title | Depends On | Layers |
|---|---|---|---|
| A | {name} | None | persistence |
| B | {name} | A | workflow, service, interface |
...

## Dependency Graph
{ASCII art}

## Execution Rounds
Round 1: A, G (no deps)
Round 2: B, D, E (depend on Round 1 outputs)
Round 3: F (depends on Round 2 outputs)

## Per-Part Scope

### Part A: {title}
{3-5 sentences: what this creates, files touched, contracts exposed downstream}
```

**No separate spec files per part.** The scope summary + design doc provide context. The plan's Problem Statement section serves as the spec. Eliminating the spec→plan hop prevents lossy translation.

Present the README to the user for review before proceeding.

---

## Phase 2: Initialize Contracts Ledger

**Output:** `plans/dev/{feature}-parts/CONTRACTS.md`

The contracts ledger accumulates verified facts from completed plans. Downstream Plan subagents receive it as context, replacing guesswork with concrete signatures.

Create from template — see [references/ledger-format.md](references/ledger-format.md).

Initial content:
- Feature name and design doc reference
- Architectural rules relevant to this feature (extracted from `copilot-instructions.md`)
- Empty sections: Collections & Methods, API Contracts, DTOs, Decisions

**The ledger must exist before any Plan subagent is dispatched.**

---

## Phase 3: Plan in Rounds

For each execution round from the README:

### 3a. Dispatch Planner Agent

For each part in the round, dispatch the Planner agent:

```yaml
# Dispatch to Planner agent (see .github/agents/planner.agent.md)
contextFiles:
  - plans/dev/design-{feature}.md               # Design doc
  - plans/dev/{feature}-parts/README.md         # Parts breakdown
  - plans/dev/{feature}-parts/CONTRACTS.md      # Current contracts
  - .github/instructions/{layers}.instructions.md  # Per layer in this part

task:
  type: CREATE
  feature: "{feature}"
  part: "{letter}"
  partScope: "{scope from README}"              # 3-5 sentence scope summary
  priorContracts: true                          # Ledger has upstream methods
```

**Parallel dispatch** within a round is allowed — parts in the same round have no mutual dependencies. But only if token budget permits; otherwise dispatch sequentially within the round.

### 3b. Validate Plan

After receiving subagent output:

1. Save to `plans/TASK-{feature}-{letter}-{descriptor}.md`
2. Run `plan_read` — must parse without errors
3. Quick-scan for:
   - Layer violations (workflow receiving a service, component importing interface)
   - Missing lint verification steps
   - References to methods not in the contracts ledger or existing codebase
   - Step count (>12 steps → consider splitting)

Fix issues before proceeding. Re-run `plan_read` after fixes.

### 3c. Update Contracts Ledger

After validating **each plan** (not after each round), update CONTRACTS.md:

| What to record | Example |
|---|---|
| Methods created | `upsert_scrobble(nd_user: str, nd_id: str, file_id: str \| None, artist: str, timestamp_ms: int)` |
| API endpoints | `POST /api/v1/scrobble` — body: ScrobbleRequest, auth: verify_key, returns: 204 |
| DTOs | `TasteProfile(nd_user, clusters, backbone_id, total_track_count, generated_at_ms)` |
| Collections | `navidrome_play_history` — _key: `{nd_user}:{nd_id}`, indexes: [...] |
| Decisions | "Workflows take `db: Database` directly, not service wrappers" |

### 3d. Proceed to Next Round

The next round's subagents receive the updated ledger. This is the anti-drift mechanism.

---

## Phase 4: Cross-Validate

After all plans exist and are individually valid:

| Check | What to look for |
|---|---|
| **Dependency completeness** | Every method/API called by a plan is defined in a prior plan's steps |
| **Contract consistency** | JSON shapes referenced by multiple plans (e.g., API response consumed by plugin AND generated by backend) match exactly |
| **Layer compliance** | No workflow receives a service. No component imports interfaces. Check against project architecture rules |
| **Coverage** | Every design doc section maps to at least one plan |
| **Gaps** | Methods needed downstream but never created upstream |
| **Overlap** | Two plans creating the same artifact |

Fix issues by editing plan files directly. Update CONTRACTS.md if fixes change any contracts.

Present the cross-validation results to the user with specific issues and fixes applied.

---

## Context Budget Management

Large features will exceed a single session. The skill is designed for this.

**The contracts ledger IS the continuity artifact.** When resuming in a new session:

1. Read `plans/dev/{feature}-parts/README.md` — execution rounds
2. Read `plans/dev/{feature}-parts/CONTRACTS.md` — all completed decisions
3. Check which plans exist in `plans/TASK-{feature}-*.md`
4. Resume at the next incomplete round

**Budget estimation:** Each Plan subagent dispatch consumes ~3-5k tokens of orchestrator context (prompt construction + result processing + ledger update). A 7-part feature needs ~25-35k tokens of orchestrator budget. Plan for 4-5 parts per session.

**If budget is tight within a round:**
- Finish the current plan dispatch + validation + ledger update
- Stop at the round boundary
- Do NOT write remaining plans directly to "save time"

---

## Validation Checklist

Before declaring feature planning complete:

- [ ] All parts have plans in `plans/TASK-{feature}-{A..Z}-*.md` **→ No gaps**
- [ ] All plans parse via `plan_read` **→ Schema compliance**
- [ ] CONTRACTS.md has entries for every method/API/DTO across all plans **→ Ledger complete**
- [ ] Cross-validation found no unresolved issues **→ Coherence**
- [ ] No plan references a method not defined in a prior plan **→ Dependency order correct**
- [ ] User has reviewed README and CONTRACTS.md **→ Alignment**
