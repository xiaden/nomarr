---
name: code-intel-usage
description: Meta-guide for using code-intel MCP tools effectively. Covers hard rules, artifact logging (logs, ADRs, ASRs, DDs), tool usage hierarchy, context management, and agent behavior patterns. Load this skill when starting work that involves code-intel tools, creating architectural artifacts, or when you need guidance on tool selection and agent coordination.
---

# Code-Intel Usage Guide

This skill contains generic agent infrastructure policies that apply to any project using the code-intel toolchain.

---

## Hard Rules

**Never:**

- Read config or env vars at module import time
- Create or mutate global state
- Guess context or line counts in tool usage
- Spawn built-in agents (`Explore`, `default`) via subagent dispatch. Only spawn agents defined in `.opencode/agents/`. For exploration or research, use `Support-Researcher`.
- Assume context will be lost or "run out." **Context does not run out.** It compacts: tool calls and thinking blocks are stripped, verbose output is summarized, but all relevant information is retained and potentially-relevant information is linked with file references you can re-read. There is no cliff where you suddenly lose everything. Do not preemptively dump state into files, session notes, or output — that loop of "saving context" is itself what wastes context. Do the work. If you need to re-read something later, the compacted context will tell you where it is.

**Always:**

- Use dependency injection for major resources (db, config, backends) — not every operation
- Write fully type-annotated code
- Use MCP `read_module_api` before calling unfamiliar APIs (the script version is legacy fallback)
- Check venv is active before running Python commands
- Reread context if a tool errors

---

## Artifact Logging & ADR Policy

**Agents are the long-term memory of this project.** Individual conversations end, but logs, ADRs, and ASRs persist across all future sessions. Use them proactively — both writing and reading.

### Artifact Types

 | Type | Purpose | Location | Workflow |
 | ------ | --------- | ---------- | ---------- |
 | **Log** | Agent observations, decisions, dead ends, discoveries | `artifacts/logs/` | `log_write` → append-only |
 | **ASR** | Architecturally Significant Requirements — the *why* that motivates decisions | `artifacts/requirements/` | `asr_create` → direct write |
 | **ADR** | Architecture Decision Records — the *what* that was decided | `artifacts/decisions/` | `adr_suggest` → user approval → `adr_commit` |
 | **DD** | Design Documents — the *how* that guides implementation | `artifacts/designs/` | `dd_create` → direct write |

**The chain:** ASR documents the requirement → DD designs the solution → ADR records the decision — ASRs are standalone — no explicit link field; reference ADRs by number in the Notes section if relevant.

### When to Log (`log_write`)

Log entries are cheap. Silence is expensive. Log when:

 | Category | When | Example |
 | ---------- | ------ | --------- |
 | `observation` | You notice something unexpected, inconsistent, or fragile in the codebase | "Module X imports Y through a re-export chain that hides the real dependency" |
 | `decision` | You choose between approaches and want the reasoning preserved | "Used batch SQL UPDATE over per-row updates for performance — see ADR-005" |
 | `discovery` | You find a pattern, convention, or gotcha that future agents should know | "PostgreSQL foreign key constraints require the referenced row to exist before INSERT" |
 | `dead-end` | An approach didn't work — save others from repeating it | "Tried monkey-patching essentia loader — fails silently, reverted to wrapper" |
 | `blocker` | Something blocks progress and needs visibility | "Migration 015 assumes column exists but 014 was never applied in test env" |
 | `research` | You gathered useful findings during investigation | "Traced auth flow: token → middleware → service → component, no workflow layer" |

**Threshold:** If you think "a future agent might waste time rediscovering this" — log it.

### Plan Context Tagging

Whenever you write a log entry while executing, fixing, or reviewing work under a specific plan, **include the plan title as a tag**:

```
log_write(
    agent="exec-executor",
    title="Found latent import cycle in persistence layer",
    category="discovery",
    tags=["TASK-myfeature-B-build-query-layer", "persistence", "imports"],
    body="..."
)
```

This is required for all plan-context writes. It is how plan reviewers reconstruct the full execution history — including work done by multiple workers in separate sessions — without relying solely on timestamps.

### When to Create ASRs (`asr_create`)

ASRs capture the requirements that motivate architectural decisions. They are the 'why' behind ADRs.

`asr_create` writes directly to `artifacts/requirements/` (no approval workflow needed).

Create an ASR when:

- **A stakeholder expresses a non-functional or architectural requirement** — record it before design begins
- **A constraint limits design options** — e.g., "Must not require GPU at runtime"
- **A measurable quality goal shapes the architecture** — e.g., "Search must complete in < 500ms at production scale"
- **An operational requirement drives deployment decisions** — e.g., "System must recover automatically after DB restart within 30s"

Use `priority` (integer) to rank importance: 0 = most critical, increment by 100 for new entries to allow future insertions between existing priorities.

**Threshold:** If a requirement will constrain the architecture or exclude design options — it's an ASR.

### When to Create ADRs (`adr_suggest` → `adr_commit`)

ADRs use a two-phase workflow requiring explicit user approval:

1. **`adr_suggest(...)`** — writes a staging draft to `artifacts/decisions/drafts/` for review. Surface the `draft_path` link to the user.
2. **User approval** — user reads the draft file and confirms the content.
3. **`adr_commit(draft_id="<slug>")`** — loads from the staging draft, assigns a real ADR number, writes the final ADR to `artifacts/decisions/`, and deletes the staging draft. Never call this without user approval.

Create an ADR when:

- **Choosing between architectural approaches** — e.g., "event-driven vs. direct call for notifications"
- **Adopting or rejecting a technology/library** — e.g., "Use ONNX over TensorFlow Lite for inference"
- **Changing a public API contract** — e.g., "Rename `get_tracks` to `search_tracks` with filter params"
- **Establishing a new convention** — e.g., "All workflows return result objects, not raw dicts"
- **Breaking a previous decision** — supersede the old ADR, don't silently abandon it

**Threshold:** If the decision constrains future work or would surprise someone who didn't witness the conversation — it's an ADR.

Always set `source_log` to link back to the log entry that motivated the decision (e.g., `rnd-dd-author#L12`).

### When to Check Logs, ASRs & ADRs (Proactive Reading)

**Before acting, check what's already known.** This prevents contradicting existing requirements and decisions and re-treading dead ends.

 | Situation | Action |
 | ----------- | -------- |
 | Starting work in an unfamiliar area | `log_read(agent="<agent-name>")` to see prior observations; use `agent="*"` to scan all agents |
 | About to make an architectural decision | `asr_search(query="<topic>")` to check for requirements, then `adr_search(query="<topic>")` for existing decisions |
 | Encountering unexpected behavior | `log_read(agent="*", category="discovery")` and `log_read(agent="*", category="dead-end")` for prior findings |
 | Debugging a failure | `log_read(agent="support-debugger")` for prior diagnoses |
 | Planning a feature that touches existing patterns | `asr_search(query="<topic>")` + `adr_search(tag="<relevant-tag>")` to understand constraints |
 | Reviewing a completed plan (QA, plan-completion check) | Two calls: `log_read(since="<when_plan_execution_started>")` to catch all temporally adjacent logs regardless of tagging, AND `log_read(tag="<plan_title>")` to catch logs from any session explicitly tagged to this plan. Both calls are required — the time window alone misses prior sessions; the tag alone misses logs that were not tagged correctly. |

**Rule: Check before you decide.** An ADR search takes one tool call. Contradicting an existing decision and then having to unwind costs hours.

### Uncertainty Logging

**When you're unsure about something, log it explicitly.** Don't silently pick an approach and move on — future agents (and humans) need to see the uncertainty.

Use `observation` category with a tag like `uncertainty` or `needs-review`:

```
log_write(
    agent="exec-executor",
    title="Unsure if edge collection needs unique constraint",
    category="observation",
    tags=["uncertainty", "database", "schema"],
    body="The plan says to add a unique index on (source, target) but existing edges don't have one. Adding it could fail if duplicates exist. Proceeding without — flagging for review."
)
```

This is not optional. **Known unknowns must be recorded.** Silent uncertainty becomes invisible bugs.

### Passing Artifacts Between Agents

**Search tools query content, not identifiers.** When you've found a relevant artifact and need another agent to use it — whether you're invoking a subagent or returning results to a caller — pass the right lookup information, not a raw identifier the search tool won't match.

 | Artifact | Identifier Format | How to Pass to Another Agent |
 | ---------- | ------------------- | --------------------------- |
 | **ADR** | `ADR-026` | Pass `adr_read(name="ADR-026")` — direct read by number. Do NOT pass `adr_search(query="ADR-026")` — search queries title/tags, not numbers. Alternatively, pass the title or a key phrase for `adr_search(query="deferred imports")`. |
 | **ASR** | `ASR-startup-time` | Pass `asr_read(name="ASR-startup-time")` — direct read by name. `asr_search` queries title/tags, not filenames. For search, pass a topic: `asr_search(query="startup")`. |
 | **DD** | `DD-schema-refactor` | Pass `dd_read(name="DD-schema-refactor")` — direct read by name. There is no `dd_search` tool; only `dd_read` exists. If unsure of the name, list `artifacts/designs/` first. |
 | **Log entry** | `agent#L12` | Pass `log_read(agent="agent", title_query="keyword")` with a title substring. Logs have no random-access by entry ID — you filter by agent + category + tag + title_query. |

**Rules for passing artifact references:**

1. **If you know the exact artifact:** Pass the `*_read` tool call with the identifier. Example: *"Read ADR-026 with `adr_read(name='ADR-026')` for the import convention."*
2. **If the receiver needs to discover artifacts:** Give topic keywords for search, not identifiers. Example: *"Search for prior decisions about imports with `adr_search(query='imports')`."*
3. **If the artifact is already in your context:** Summarize the relevant content directly instead of forcing a re-fetch. This is faster and avoids lookup mistakes.
4. **Never assume search matches identifiers.** `adr_search`, `asr_search`, and `log_read` all query human-readable content (titles, tags, body text) — not filenames or numbers.
5. **Include tags when returning artifact references.** Tags are the primary discovery mechanism for `adr_search(tag=...)` and `log_read(tag=...)`. When reporting that you found a relevant ADR or log entry, always include its tags so the receiving agent can find related artifacts.
