---
name: artifact-context
description: Generates a structured prompt for spawning Support-Librarian to gather relevant ADRs, logs, and design docs before a design, planning, or execution task. Use before starting any significant work — designing a feature, creating a plan, executing a plan, or reviewing code — to ensure prior decisions and dead ends are known. Trigger automatically in agents that have this skill, or manually when entering an unfamiliar area.
---

# Artifact Context Gathering

Before acting on any significant task, spawn `Support-Librarian` to search the artifact corpus for relevant constraints, warnings, and context. This skill templates the prompt.

## When to Use

| You're about to... | Use this skill |
|--------------------|---------------|
| Design a feature (DDAuthor) | Yes — before writing the design doc |
| Create an implementation plan (Exec-Planner) | Yes — before creating the plan |
| Route work to a department (Director, RnD-Manager) | Yes — before dispatching |
| Execute a plan phase (Exec-Executor) | No — the plan should already reflect artifact context |
| Do a quick fact check | No — overhead not worth it |

**Threshold:** If the task touches architecture, creates artifacts, or makes decisions that constrain future work — gather context first. If it's mechanical execution of an already-validated plan — skip.

## How to Use

### Step 1: Identify the Task Shape

Determine what you're about to do and what scope it touches:

```yaml
task:
  action: "design"           # design | plan | execute | review | debug
  subject: "ML tagging pipeline redesign"
  scope: "nomarr/components/ml, nomarr/workflows/processing"
```

### Step 2: Spawn Support-Librarian

Use this prompt template, filling in the task details:

```
Search the artifact corpus for everything relevant to this task:

Task: {action} — {subject}
Scope: {scope}

Specific concerns:
- {any specific questions or areas of uncertainty}

Return a structured briefing with constraints (ADRs/decisions that must be respected), 
warnings (dead ends, failed approaches), context (useful background), and open questions 
(unresolved uncertainties from prior work).
```

### Step 3: Incorporate the Briefing

The Librarian returns a structured briefing. Use it:

| Section | What to do |
|---------|-----------|
| `constraints` | These are non-negotiable. Your design/plan must comply. |
| `warnings` | Avoid these approaches. If you must use one, document why. |
| `context` | Consider this background. May influence your approach. |
| `open_questions` | Surface these to the user or document your resolution. |
| `no_relevant_artifacts` | Proceed with confidence — no prior work constrains you here. |

## Example: DDAuthor Using This Skill

```
# Before writing the design doc:

1. Identify task: design — "notification system for scan completion"
   Scope: nomarr/services, nomarr/workflows/processing, frontend/

2. Spawn Support-Librarian:
   "Search the artifact corpus for everything relevant to this task:
   Task: design — notification system for scan completion
   Scope: nomarr/services, nomarr/workflows/processing, frontend/
   Specific concerns:
   - Are there existing ADRs about event-driven patterns?
   - Has anyone tried WebSocket-based notifications before?
   Return a structured briefing..."

3. Librarian returns:
   - Constraint: ADR-003 requires state flags, not event pipelines
   - Warning: Log shows WebSocket attempt was abandoned (connection pooling issues)
   - Context: DD-schema-refactor-v1 added event tracking tables

4. DDAuthor writes design doc that:
   - Uses state-flag polling instead of event pipeline (respects ADR-003)
   - Avoids WebSockets (heeds warning)
   - Leverages existing event tracking tables (uses context)
```

## Example: Director Using This Skill

```
# Before routing a feature to R&D:

1. Identify task: design — "playlist generation from ML embeddings"
   Scope: nomarr/components/ml, nomarr/workflows

2. Spawn Support-Librarian with task context

3. Librarian returns:
   - Constraint: ADR-001 mandates ONNX for all ML inference
   - Context: Prior design doc exists for embedding pipeline

4. Director includes in dispatch to RnD-Manager:
   "Design playlist generation feature. 
   Constraints from artifact review:
   - Must use ONNX runtime (ADR-001)
   - Prior embedding pipeline design exists — build on it, don't redesign"
```

## Anti-Patterns

- **Don't skip this for "small" design decisions** — Small decisions that contradict ADRs cause big problems.
- **Don't re-search what the Librarian already found** — Trust the briefing. Read cited artifacts only if you need more detail.
- **Don't ignore `no_relevant_artifacts`** — An empty briefing is signal: you're in uncharted territory. Log your decisions for future sessions.
- **Don't spawn Librarian during mechanical execution** — If you're following a plan step-by-step, the plan author should have already gathered context.
