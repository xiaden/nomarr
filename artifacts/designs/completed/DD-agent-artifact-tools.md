# MCP Agent Artifact Tools — Design Document

**Status:** Draft  
**Author:** RnD-DDAuthor  
**Created:** 2026-04-01  
**Revised:** 2026-04-02

**Related Documents:**
- [design-agent-hierarchy-restructure.md](design-agent-hierarchy-restructure.md) — Agent hierarchy and scoping
- [.github/instructions/task-plans.instructions.md](../../.github/instructions/task-plans.instructions.md) — Plan schema (model for markdown-backed tools)
- [code-intel/README.md](../../code-intel/README.md) — MCP server overview

---

## Scope

This document covers:
1. Nine new MCP tools for creating, reading, searching, and archiving structured artifacts
2. Markdown schemas for design documents, ADRs, and agent logs
3. Restructured `artifacts/` directory with lifecycle management
4. Tool registration and server wiring
5. Agent-to-tool mapping (which agents get which tools)
6. Migration of existing `plans/` content to the new structure
7. Updates to existing plan tools for new paths

**Out of scope:** Chain-of-command enforcement in tool code (handled by agent YAML `tools:` arrays), UI for browsing artifacts.

---

## Problem Statement

Agents currently have no structured way to produce or consume durable project artifacts:

1. **Design documents** are hand-written with inconsistent formats. No tool enforces the DD schema, so agents drift from convention.

2. **Architecture decisions** are scattered across chat logs, plan annotations, and ad-hoc markdown files. There is no searchable ADR repository.

3. **Operational logs** (research trails, dead ends, observations) vanish when a session ends. Future agents repeat failed approaches because there is no institutional memory.

4. **Cross-agent knowledge transfer** relies entirely on passing file paths through spawn chains. Agents cannot discover what decisions have been made or what research has been conducted.

5. **The `plans/` directory has accumulated scope.** It now holds plans, design docs, contracts, scratch work, and speculative notes. The flat structure makes it hard for humans to see what's active vs. archived.

6. **No artifact lifecycle management.** Completed plans and design documents remain mixed with active work, making it hard to see what's in-flight at a glance.

The plan tools (`plan_read`, `plan_complete_step`) demonstrate that structured markdown + MCP tools is an effective pattern for agent-consumable artifacts. This design extends that pattern to three new artifact types and adds lifecycle transitions.

---

## Design Goals

| Goal | Rationale |
|------|----------|
| Schema enforcement at creation time | Prevent format drift; agents produce valid artifacts or get errors |
| Verified lifecycle transitions | Archive tools validate completion before moving artifacts |
| Append-only logs | Operational history is immutable; no rewriting the past |
| Auto-incrementing ADR numbers | Eliminate numbering collisions between concurrent agents |
| Human-discoverable active work | `pending/` directories show only in-flight artifacts |
| Chain-of-command log scoping | Agents read logs one level up and one level down, not laterally |
| Tool simplicity | Tools are CRUD + lifecycle — no access-control logic; scoping is in agent YAML |
| Consistent response format | All tools use `ToolOutput` with breadcrumb + metadata pattern |

---

## Architecture

### Storage Layout

```
artifacts/
├── plans/
│   ├── pending/             ← active plans (TASK-*.md)
│   └── completed/           ← finished plans (moved by plan_archive)
├── designs/
│   ├── pending/             ← DDs driving active work (DD-*.md)
│   ├── completed/           ← DDs whose plans are all done (moved by dd_archive)
│   └── parts/               ← contracts, READMEs for multi-part features
│       └── {feature}/
│           ├── CONTRACTS.md
│           └── README.md
├── decisions/
│   └── ADR-{NNN}-{slug}.md  ← flat, no lifecycle split
├── logs/
│   └── {agent-name}.log.md  ← per-agent operational logs
└── scratch/
    ├── examples/
    └── speculative/
```

**Lifecycle rules:**
- **Plans and DDs** have `pending/` → `completed/` lifecycle, gated by verification tools
- **ADRs** are reference material — no lifecycle split. Status tracked in metadata (Proposed → Accepted → Deprecated → Superseded)
- **Logs** are append-only streams — no lifecycle transition
- **Parts** stay in `designs/parts/{feature}/` regardless of DD status — plans may still reference them

### Layer Mapping

| Component | Layer | Location | Responsibility |
|-----------|-------|----------|----------------|
| `dd_create` | tool | `tools/dd_create.py` | Validate + write DD to `designs/pending/` |
| `dd_read` | tool | `tools/dd_read.py` | Parse DD from pending or completed |
| `dd_archive` | tool | `tools/dd_archive.py` | Verify all linked plans completed, move DD |
| `adr_create` | tool | `tools/adr_create.py` | Auto-number + validate + write ADR |
| `adr_read` | tool | `tools/adr_read.py` | Parse + return ADR as structured JSON |
| `adr_search` | tool | `tools/adr_search.py` | Glob + grep ADR files, return summaries |
| `log_write` | tool | `tools/log_write.py` | Append timestamped entry to agent log |
| `log_read` | tool | `tools/log_read.py` | Parse + filter + return log entries |
| `plan_archive` | tool | `tools/plan_archive.py` | Verify all steps complete, move plan |
| `dd_md` | helper | `helpers/dd_md.py` | DD markdown parser and generator |
| `adr_md` | helper | `helpers/adr_md.py` | ADR markdown parser and generator |
| `log_md` | helper | `helpers/log_md.py` | Log markdown parser and appender |
| `server.py` | registration | `server.py` | `@mcp.tool()` wrappers, imports, `TOOL_IMPLS` |

All paths relative to `code-intel/src/mcp_code_intel/`.

---

### Data Model: Design Document Schema

```markdown
# {Title} — Design Document

**Status:** {Draft | Approved | Completed | Superseded}  
**Author:** {agent-name or human}  
**Created:** {YYYY-MM-DD}

**Related Documents:**
- [{title}]({relative-path}) — {description}

---

## Scope
{What this covers and what is out of scope}

## Problem Statement
{What and why}

## Design Goals
{Table or list of goals with rationale}

## Architecture
{Layer mapping, data model, API surface, workflows}

## Constraints
{Non-functional requirements, performance, compatibility}

## Open Questions
{Decisions deferred to implementation}
```

**Required sections:** Scope, Problem Statement, Architecture  
**Optional sections:** Design Goals, Constraints, Open Questions, Appendix: Research Findings, any other `## Header`  
**Filename:** `DD-{feature-slug}.md` where `feature-slug` is lowercase with hyphens (validated by regex `^[a-z0-9][a-z0-9-]*[a-z0-9]$`)

### Data Model: ADR Schema

```markdown
# ADR-{NNN}: {Title}

**Status:** {Proposed | Accepted | Deprecated | Superseded}  
**Date:** {YYYY-MM-DD}  
**Tags:** {comma-separated list}  
**Source Log:** {agent-name}#{entry-id}  ← optional, for log-to-ADR promotion

## Context
{Why this decision is needed}

## Decision
{What we decided}

## Consequences
{What follows from this decision — both positive and negative}

## References
- {links to DDs, plans, or external resources}
```

**Required sections:** Context, Decision, Consequences  
**Optional sections:** References, any other `## Header`  
**Required metadata:** Status, Date, Tags (at least one tag)  
**Optional metadata:** Source Log  
**Filename:** `ADR-{NNN}-{title-slug}.md` where NNN is zero-padded auto-incrementing (001, 002, ...)

### Data Model: Agent Log Schema

Each log file is a single markdown document with append-only entries:

```markdown
# Agent Log: {agent-name}

---

## [{entry-id}] {title}
**Date:** {YYYY-MM-DDTHH:MM:SS}  
**Category:** {research | decision | blocker | discovery | dead-end | implementation | observation}  
**Tags:** {optional comma-separated freeform tags}

{Body text — freeform markdown}

---

## [{entry-id}] {title}
...
```

**Entry IDs** auto-generate as `L{N}` (e.g., `L1`, `L2`, `L42`), incrementing per log file.  
**Required fields:** title, category  
**Optional fields:** tags, body  
**Filename:** `{agent-name}.log.md` where `agent-name` matches the agent's log identity (e.g., `rnd-dd-author`, `exec-executor`)

---

### API Surface

#### `dd_create`

```python
def dd_create(
    title: str,           # e.g., "Schema Refactor v1"
    slug: str,            # e.g., "schema-refactor-v1" → DD-schema-refactor-v1.md
    status: str,          # Draft | Approved | Superseded
    author: str,          # agent name or "human"
    scope: str,           # Scope section content (markdown)
    problem_statement: str,  # Problem Statement section content
    architecture: str,    # Architecture section content
    design_goals: str = "",
    constraints: str = "",
    open_questions: str = "",
    related_documents: list[dict[str, str]] | None = None,  # [{title, path, description}]
    extra_sections: list[dict[str, str]] | None = None,     # [{heading, content}]
    workspace_root: Path,
) -> dict[str, Any]
```

**Validation:**
- Slug matches `^[a-z0-9][a-z0-9-]*[a-z0-9]$`
- Status is one of the allowed values
- Required sections are non-empty
- File does not already exist in `pending/` or `completed/` (no overwrites, no duplicates)

**Returns:** `{"path": "artifacts/designs/pending/DD-schema-refactor-v1.md", "title": "..."}` or `{"error": "...", "message": "..."}`

#### `dd_read`

```python
def dd_read(
    name: str,            # DD name with or without prefix/extension
    workspace_root: Path,
) -> dict[str, Any]
```

**Name resolution:** Accepts `DD-schema-refactor-v1`, `DD-schema-refactor-v1.md`, or `schema-refactor-v1`. Normalizes to `DD-{slug}.md`. Searches both `artifacts/designs/pending/` and `artifacts/designs/completed/`.

**Returns:** Structured dict with `title`, `status`, `author`, `created`, `sections` (keyed by heading), `related_documents`, `location` (`"pending"` or `"completed"`).

#### `dd_archive`

```python
def dd_archive(
    name: str,            # DD name (same resolution as dd_read)
    workspace_root: Path,
) -> dict[str, Any]
```

**Verification before moving:**
1. Resolve DD in `artifacts/designs/pending/` (error if already in `completed/` or not found)
2. Extract the slug from the DD filename
3. Scan `artifacts/plans/pending/` for plans matching `TASK-{slug}-*.md` (convention-based link)
4. If `artifacts/designs/parts/{slug}/README.md` exists, also check plan names listed there (fallback link)
5. For each linked plan: if it exists in `pending/` → error (still active)
6. All linked plans in `completed/` (or no linked plans at all) → move DD to `artifacts/designs/completed/`
7. Update the DD's `**Status:**` line to `Completed`

**Returns:** `{"archived": true, "path": "artifacts/designs/completed/DD-foo.md", "linked_plans_completed": ["TASK-foo-A", "TASK-foo-B"]}` or `{"error": "active_plans", "pending_plans": ["TASK-foo-C"]}`

#### `adr_create`

```python
def adr_create(
    title: str,           # e.g., "Use edges instead of FK properties"
    status: str,          # Proposed | Accepted | Deprecated | Superseded
    tags: list[str],      # At least one tag required
    context: str,         # Context section content
    decision: str,        # Decision section content
    consequences: str,    # Consequences section content
    references: str = "",
    source_log: str = "", # Optional "agent-name#L42" for log-to-ADR promotion
    extra_sections: list[dict[str, str]] | None = None,
    workspace_root: Path,
) -> dict[str, Any]
```

**Auto-numbering:** Scans `artifacts/decisions/ADR-*.md`, extracts highest NNN, increments. Retries up to 3 times on collision.

**Validation:**
- At least one tag
- Status is one of the allowed values
- Required sections are non-empty
- `source_log` format validated if provided: `{agent-name}#L{N}`

**Returns:** `{"path": "artifacts/decisions/ADR-003-use-edges.md", "number": 3, "title": "..."}` or error.

#### `adr_read`

```python
def adr_read(
    name: str,            # ADR name, e.g., "ADR-003" or "ADR-003-use-edges"
    workspace_root: Path,
) -> dict[str, Any]
```

**Name resolution:** Accepts `ADR-003`, `ADR-003-use-edges`, `ADR-003-use-edges.md`. If only number provided, globs for `ADR-003-*.md`.

**Returns:** Structured dict with `number`, `title`, `status`, `date`, `tags`, `source_log`, `sections`.

#### `adr_search`

```python
def adr_search(
    query: str = "",      # Search in title, tags, and body text
    tag: str = "",        # Filter by exact tag match
    status: str = "",     # Filter by status
    limit: int = 50,      # Max results (capped at 50)
    workspace_root: Path,
) -> dict[str, Any]
```

**Behavior:** Scans all `artifacts/decisions/ADR-*.md` files. Parses only the metadata header (title, tags, status, date) for performance — no full-body parse unless `query` is provided. Results sorted by ADR number descending (newest first).

**Returns:** `{"results": [{"number": 3, "title": "...", "status": "...", "tags": [...], "date": "...", "path": "..."}], "total": N}`

#### `log_write`

```python
def log_write(
    agent: str,           # Agent log identity (e.g., "rnd-dd-author")
    title: str,           # Entry title
    category: str,        # research | decision | blocker | discovery | dead-end | implementation | observation
    body: str = "",       # Entry body (freeform markdown)
    tags: list[str] | None = None,  # Optional freeform tags
    workspace_root: Path,
) -> dict[str, Any]
```

**Behavior:** Creates the log file with header if it doesn't exist. Appends new entry with auto-incremented ID and current timestamp. Entries are separated by `---` horizontal rules.

**Validation:**
- `agent` matches `^[a-z][a-z0-9-]*[a-z0-9]$`
- `category` is one of the allowed values
- `title` is non-empty

**Returns:** `{"path": "artifacts/logs/rnd-dd-author.log.md", "entry_id": "L7", "title": "..."}` or error.

#### `log_read`

```python
def log_read(
    agent: str,           # Agent log identity to read
    category: str = "",   # Filter by category
    tag: str = "",        # Filter by tag
    title_query: str = "",  # Search in entry titles
    limit: int = 50,      # Max entries (capped at 50)
    workspace_root: Path,
) -> dict[str, Any]
```

**Behavior:** Reads and parses the agent's log file. Returns entries newest-first. Filters are AND-combined. Only returns entry metadata + body (not the full file).

**Returns:** `{"agent": "rnd-dd-author", "entries": [{"id": "L7", "title": "...", "date": "...", "category": "...", "tags": [...], "body": "..."}], "total": N}`

#### `plan_archive`

```python
def plan_archive(
    plan_name: str,       # Plan name (same resolution as plan_read)
    ignore_blocked: bool = False,  # If True, archive even if steps have **Blocked:** annotations
    workspace_root: Path,
) -> dict[str, Any]
```

**Verification before moving:**
1. Resolve plan in `artifacts/plans/pending/` (error if already in `completed/` or not found)
2. Parse the plan via existing `plan_md.parse_plan()`
3. Check every step is `checked: True` — if any unchecked → error with list of incomplete step IDs
4. Check for steps with `**Blocked:**` annotations:
   - If `ignore_blocked=False` (default): return error with blocked step details and message suggesting the caller verify blockers are resolved, then retry with `ignore_blocked=True`
   - If `ignore_blocked=True`: proceed despite blocked annotations
5. All clear → move from `artifacts/plans/pending/` to `artifacts/plans/completed/`

**Returns:** `{"archived": true, "path": "artifacts/plans/completed/TASK-foo.md", "steps_completed": 12}` or `{"error": "incomplete", "incomplete_steps": ["P2-S3", "P2-S4"], "blocked_steps": ["P1-S2"]}`

---

### Tool Registration Pattern

Follows the established pattern in `server.py`:

1. **Implementation module** in `tools/` — pure function, receives `workspace_root: Path`, returns `dict[str, Any]`
2. **Import** in `server.py` with `_impl` suffix
3. **`TOOL_IMPLS` registry** entry
4. **`@mcp.tool()` wrapper** with `Annotated` parameter descriptions, delegates to `_impl`, wraps response in `ToolOutput`

Example registration (for `plan_archive`):

```python
# In server.py imports:
from .tools.plan_archive import plan_archive as plan_archive_impl

# In TOOL_IMPLS:
"plan_archive": plan_archive_impl,

# Wrapper:
@mcp.tool()
def plan_archive(
    plan_name: Annotated[str, "Plan name (with or without .md extension)"],
) -> CallToolResult:
    """Archive a completed plan.

    Verifies all steps are complete and none are blocked before moving
    from pending to completed. Returns error with details if validation fails.
    """
    result = plan_archive_impl(plan_name=plan_name, workspace_root=ROOT)
    return ToolOutput(
        tool_name="plan_archive",
        breadcrumb=f"Archived {plan_name}" if result.get("archived") else f"Cannot archive: {result.get('error')}",
        metadata=result,
    ).to_call_tool_result()
```

### Helper Module Pattern

Follows the `plan_md.py` pattern:

- **Parser:** Regex-based line-by-line parsing of markdown sections
- **Generator:** String-building function that assembles valid markdown from structured inputs
- **Validation:** At creation time, not read time
- **Data classes:** `@dataclass` for internal structure (like `Plan`, `Phase`, `Step`)

Proposed data classes:

```python
# helpers/dd_md.py
@dataclass
class DesignDocument:
    title: str
    status: str
    author: str
    created: str
    related_documents: list[dict[str, str]]
    sections: dict[str, str]  # heading → content

# helpers/adr_md.py
@dataclass
class ADR:
    number: int
    title: str
    status: str
    date: str
    tags: list[str]
    source_log: str | None
    sections: dict[str, str]

# helpers/log_md.py
@dataclass
class LogEntry:
    id: str          # "L42"
    title: str
    date: str        # ISO 8601
    category: str
    tags: list[str]
    body: str

@dataclass
class AgentLog:
    agent: str
    entries: list[LogEntry]
```

---

### Agent-to-Tool Mapping

Tools are exposed to agents via their `.agent.md` YAML `tools:` array using the `nomarr_dev/{tool_name}` naming convention.

| Agent | New Tools |
|-------|-----------|
| Director | `dd_read`, `adr_search`, `adr_read`, `log_read` |
| RnD-Manager | `dd_read`, `adr_search`, `adr_read`, `log_read`, `log_write` |
| RnD-DDAuthor | `dd_create`, `dd_read`, `adr_create`, `adr_read`, `log_write` |
| RnD-Architect | `dd_read`, `adr_create`, `adr_search`, `adr_read`, `log_write` |
| RnD-Advisory (Ideator, Estimator, etc.) | `adr_read`, `log_write` |
| Support-PatternEnforcer | `adr_read`, `log_write` |
| Exec-Manager | `dd_read`, `dd_archive`, `adr_search`, `adr_read`, `plan_archive`, `log_read`, `log_write` |
| Exec-Executor | `log_write` |
| Exec-Planner | `dd_read`, `adr_search`, `adr_read`, `log_write` |
| Exec-Fixer | `log_write` |
| QA-Reviewer | `dd_read`, `adr_search`, `adr_read`, `log_write`, `log_read` |
| QA-Leaf agents | `log_write` |
| Support-Researcher | `dd_read`, `adr_search`, `adr_read`, `log_write`, `log_read` |
| Support-Debugger | `adr_search`, `adr_read`, `log_write`, `log_read` |

**Archive tool scoping:** Only Exec-Manager gets `plan_archive` and `dd_archive`. Archiving is a management/lifecycle action, not a worker action.

### Log-Read Chain-of-Command Scoping

Log-Read scoping is NOT enforced in tool code. The `log_read` tool accepts any `agent` parameter. Scoping is enforced by:
1. Only granting `log_read` to agents that need it
2. Documenting the allowed `agent` values in each agent's instructions

| Agent with `log_read` | Can Read Logs Of |
|-----------------------|-----------------|
| Director | Own, `rnd-manager`, `exec-manager` (direct reports) |
| RnD-Manager | Own, `director` (up), all `rnd-*` agents (down) |
| Exec-Manager | Own, `director` (up), `exec-executor`, `exec-fixer`, `exec-planner` (down) |
| QA-Reviewer | Own, `exec-manager` (up), `exec-executor` (audit target), `qa-test-analyzer`, `qa-docs-analyzer` (down) |
| Support-Researcher | Own, `director`, `rnd-manager`, `exec-manager` (manager-level) |
| Support-Debugger | Own, `director`, `rnd-manager`, `exec-manager` (manager-level), `exec-executor` (audit target) |

This keeps the tool simple and the access model in the configuration layer where it belongs.

---

### Existing Tool Updates

The directory restructure requires updates to existing plan tools:

| Tool | Change |
|------|--------|
| `plan_read` | Base path changes from `plans/` to `artifacts/plans/pending/`; also search `artifacts/plans/completed/` |
| `plan_complete_step` | Base path changes from `plans/` to `artifacts/plans/pending/` (only operates on pending plans) |
| All agent files | Context file paths referencing `plans/` must update to `artifacts/plans/pending/` |
| Skills | `feature-planning`, `feature-execution` path references updated |
| Instructions | `task-plans.instructions.md`, `copilot-instructions.md` path references updated |

---

### Migration Plan

Existing content in `plans/` moves to the new structure:

| Current Location | New Location |
|-----------------|--------------|
| `plans/TASK-*.md` (active) | `artifacts/plans/pending/TASK-*.md` |
| `plans/completed/TASK-*.md` | `artifacts/plans/completed/TASK-*.md` |
| `plans/dev/design-*.md` | `artifacts/designs/pending/DD-*.md` (renamed to DD- prefix) |
| `plans/dev/{feature}-parts/` | `artifacts/designs/parts/{feature}/` |
| `plans/scratch/` | `artifacts/scratch/` |
| `plans/speculative/` | `artifacts/scratch/speculative/` |
| `plans/examples/` | `artifacts/scratch/examples/` |
| `plans/dev/` (remaining) | `artifacts/scratch/dev/` (if anything left) |
| `plans/PLAN_SCHEMA.json` | `artifacts/plans/PLAN_SCHEMA.json` |

DD renaming during migration:
| Current Name | New Name |
|-------------|----------|
| `design-schema-refactor-v1.md` | `DD-schema-refactor-v1.md` |
| `design-cascade-delete.md` | `DD-cascade-delete.md` |
| `design-db-issues-investigation.md` | `DD-db-issues-investigation.md` |
| `design-agent-hierarchy-restructure.md` | `DD-agent-hierarchy-restructure.md` |

---

## Constraints

| Constraint | Detail |
|------------|--------|
| No concurrent write protection for logs | Agents run sequentially in VS Code; no true concurrency. Simple append is sufficient. |
| ADR auto-numbering race condition | Mitigate with glob-then-write; if file exists, increment and retry (max 3 retries). Sufficient for agent workloads. |
| No DD overwrites | `dd_create` fails if file exists. Edits to DDs use general-purpose file editing tools. |
| Log append-only | `log_write` only appends. No edit or delete tool. Log files can be manually edited if needed. |
| Max 50 results | `adr_search` and `log_read` cap results at 50 to bound context window usage. |
| No full-text indexing | Search is grep-based over flat files. Acceptable at expected scale (tens of ADRs, hundreds of log entries). |
| Workspace-root relative | All paths resolved relative to `workspace_root`, same as plan tools. No absolute paths stored in artifacts. |
| Archive is one-way | No "un-archive" tool. Manually move files back if needed. |

---

## Open Questions

1. **DD versioning** — Should `dd_create` support creating a new version of an existing DD (e.g., `DD-schema-refactor-v2.md`), or is that just a new DD with a different slug? Current design says new slug — revisit if needed.

2. **ADR supersession** — When an ADR is superseded, should the tool update the old ADR's status? Current design: no — manual edit or a future `adr_update` tool.

3. **Log rotation** — At what point do log files become too large? Current design has no rotation. Could add a "max entries per file" with overflow to `{agent-name}.log.2.md` if needed, but premature for now.

4. **Extra sections ordering** — `dd_create` and `adr_create` accept `extra_sections`. Should they be placed after the required sections in a fixed order, or should the caller control ordering? Current design: appended after required sections in the order provided.

5. **`plan_archive` and blocked annotations** — Should `plan_archive` fail if any step has a `**Blocked:**` annotation, even if the step is checked? Current design says yes — blockers indicate unresolved issues even on "complete" steps. This may be too strict.

---

## Appendix: Research Findings

### Existing Tool Pattern (server.py)

- Tools are registered with `@mcp.tool()` decorator in `server.py`
- Implementation lives in `tools/{name}.py` as a pure function
- Functions receive `workspace_root: Path` as injected parameter
- Responses wrapped in `ToolOutput(tool_name=..., breadcrumb=..., metadata=...)` → `CallToolResult`
- All tools listed in `TOOL_IMPLS` dict for programmatic access
- Parameters use `Annotated[type, description]` for MCP schema generation

### Plan Tool Pattern (model for new tools)

- `plan_read.py`: validate name → resolve path → check exists → parse markdown → return dict
- `plan_complete_step.py`: validate inputs → resolve path → parse → mutate → write back → re-parse → return response
- Path validation rejects `/`, `\`, `..` (traversal prevention)
- Name normalization strips `.md` extension
- Errors returned as `{"error": "error_code", "message": "human readable"}`

### Existing Design Doc Format

- Four DDs exist in `plans/dev/`: `design-schema-refactor-v1.md`, `design-cascade-delete.md`, `design-db-issues-investigation.md`, `design-agent-hierarchy-restructure.md`
- Consistent format: H1 title with " — Design Document" suffix, bold metadata block, `---` separator, H2 sections
- All use: Status, Author, Created metadata; Related Documents list; Scope and Problem Statement sections

### Agent Tool References

- Agent YAML `tools:` arrays use `nomarr_dev/{tool_name}` format (e.g., `nomarr_dev/plan_read`)
- New tools will be referenced as `nomarr_dev/dd_create`, `nomarr_dev/adr_search`, etc.
- Tool access scoping is purely a YAML configuration concern — no code-level ACL needed
