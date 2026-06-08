---
name: artifact-logging
description: Procedures for logging observations, decisions, and discoveries during agent work. Load when you need to write or read logs, create ADRs, or understand logging conventions.
---

# Artifact Logging

## When to Log

Log proactively. Silence is expensive — future agents (including yourself in later sessions) need context about what happened and why.

| Situation | Category | Example |
|-----------|----------|---------|
| You notice something fragile or inconsistent | `observation` | "Config loading in X bypasses ConfigService — potential layer violation" |
| You're unsure about an approach and pick one anyway | `observation` + tag `uncertainty` | "Unclear if this migration needs a down path — proceeding without" |
| You discover a codebase pattern or gotcha | `discovery` | "AQL UPSERT requires all three clauses even when update is empty" |
| An approach fails and you switch strategies | `dead-end` | "Tried using rename on re-exported symbol — doesn't follow re-exports" |
| You make a choice between approaches | `decision` | "Used component-level caching over service-level — keeps DI simpler" |
| You uncover useful context during research | `research` | "Library scan workflow depends on filesystem watcher, not polling" |
| A plan deviates from design doc | `observation` | Record the drift |
| You resolve a blocker | `decision` | Record how and why |
| A fix cycle reveals a recurring issue | `discovery` | Save others from repeating it |
| Escalation is triggered | `blocker` | Record what went wrong |

## Log Entry Format

```python
log_write(
    agent="your-agent-name",  # e.g., "exec-manager", "qa-reviewer"
    category="observation",   # or "discovery", "decision", "dead-end", "research", "blocker"
    message="Clear description of what happened",
    tags=["plan-title", "module-name"]  # Optional but recommended
)
```

**Always include:**
- `agent`: Your agent name (e.g., "exec-manager", "rnd-dd-author")
- `category`: One of the categories above
- `message`: Clear, specific description

**Often include:**
- `tags`: Plan title (e.g., "TASK-myfeature-A-build-query-layer"), module name, or other context

## Reading Logs

Before starting work, check for relevant context:

```python
# Check for prior observations about this module/area
log_read(agent="your-agent-name", tag="module-name")

# Check for logs from a specific plan
log_read(tag="plan-title")

# Check for specific categories
log_read(category="discovery")
log_read(category="dead-end")

# Reconstruct execution history (for managers picking up mid-stream)
log_read(since="<timestamp>")  # All logs since a time
log_read(tag="<plan-title>")   # All logs for a plan
```

## ADR Workflow

When you make a decision that constrains future work:

1. **Log the reasoning first:**
   ```python
   log_write(
       agent="your-agent-name",
       category="decision",
       message="Chose X over Y because Z",
       tags=["topic"]
   )
   ```

2. **Create the ADR:**
   ```python
   adr_suggest(
       title="Brief title",
       context="Why this decision is needed",
       decision="What was decided",
       consequences="What follows from this decision",
       source_log="log-entry-id"  # Reference the log entry
   )
   ```

3. **User approves** (you must ask)

4. **Commit the ADR:**
   ```python
   adr_commit(draft_id="slug-from-suggest")
   ```

**When to create ADRs:**
- Architectural decisions that constrain future work
- Choosing between approaches with significant tradeoffs
- Changes to public APIs or contracts
- Breaking a previous ADR (supersede it, don't silently ignore)

**When NOT to create ADRs:**
- Implementation details (those go in design docs)
- One-off fixes (those go in logs)
- Trivial choices (just log them)

## Log Access Rules

Agents can read logs from:
- **Own logs**: Your own agent name
- **Up**: Agents that manage you (e.g., exec-manager can read director logs)
- **Down**: Agents you manage (e.g., exec-manager can read exec-executor logs)
- **Audit targets**: Specific agents you're responsible for reviewing

Agents **cannot** read logs from:
- Peer agents (unless explicitly allowed)
- Agents in unrelated departments

## Common Patterns

### Plan Tag Required

Every `log_write` during a fix cycle or plan execution must include the plan title as a tag:

```python
log_write(
    agent="exec-fixer",
    category="observation",
    message="Fix revealed deeper issue in query layer",
    tags=["TASK-myfeature-B-build-query-layer"]  # Mandatory
)
```

This is how QA and managers reconstruct the full execution history.

### Mid-Stream Context Recovery

When picking up a plan mid-execution:

```python
# Get all logs from this work period
log_read(since="<when_plan_execution_started>")

# Get all logs for this specific plan
log_read(tag="<plan_title>")
```

Both calls are required. The time window alone misses prior sessions; the tag alone misses logs written without the plan tag.

### Discovery Logging

When you discover something that might help future work:

```python
log_write(
    agent="your-agent-name",
    category="discovery",
    message="Found that X requires Y before Z",
    tags=["module-name", "workflow-name"]
)
```

### Dead-End Logging

When an approach fails:

```python
log_write(
    agent="your-agent-name",
    category="dead-end",
    message="Tried X but it doesn't work because Y",
    tags=["module-name"]
)
```

This prevents future agents (including yourself) from repeating the mistake.
