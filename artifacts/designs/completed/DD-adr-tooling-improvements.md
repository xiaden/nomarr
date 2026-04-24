# ADR Tooling Improvements — Design Document

**Status:** Draft  
**Author:** rnd-dd-author  
**Created:** 2026-04-04  

**Related Documents:**

- [ADR-001](artifacts/decisions/ADR-001-use-onnx-runtime-for-ml-inference.md) — Demonstrates stub quality (3 one-liner sections)
- [ADR-002](artifacts/decisions/ADR-002-normalize-all-code-intel-file-reads-to-lf-only.md) — Missing `source_log` field
- [ADR-007](artifacts/decisions/ADR-007-tag-editor-service-home-libraryservice-extension-via-mixin.md) — Contains literal `\n` in body text (serialization bug)
- [ADR-013](artifacts/decisions/ADR-013-expand-taggingservice-as-full-tags-vertical-slice.md) — Uses informal `**Supersedes:**` metadata not in the ADR dataclass
- [DD-code-intel-tool-fixes-v1](artifacts/designs/completed/DD-code-intel-tool-fixes-v1.md) — Prior code-intel reliability fixes

---

## Scope

Code-intel MCP ADR tools (`adr_suggest`, `adr_commit`, `adr_read`, `adr_search`) and the shared `adr_md.py` helper. Adds one new schema file. No changes to the Nomarr backend — this is entirely within `code-intel/`.

---

## Problem Statement

The ADR tooling produces structurally valid but qualitatively poor ADRs. Inspecting existing ADRs reveals four categories of problems:

1. **Stub content** — ADR-001 has three one-sentence sections ("We need a fast ML inference backend that works cross-platform", "Use ONNX Runtime as the primary inference engine", "Must convert all models to ONNX format before deployment"). The tools accept this without warning.

2. **Escaped newline bug** — ADR-007's Context and Decision sections contain literal `\n` characters instead of actual line breaks. The MCP transport serializes `\n` as the two-character sequence `\n`, and the tools pass it through to markdown without unescaping.

3. **Missing structured fields** — ADR-002 has no `source_log` despite being a substantive decision. ADR-013 uses an informal `**Supersedes:** ADR-007` line that the parser ignores — `Supersedes` is not a recognized metadata field in the `ADR` dataclass.

4. **Eager number assignment** — `adr_suggest` calls `next_adr_number()` to assign a real number during preview. If the user requests multiple previews before committing, or abandons a preview, the number shown in the preview may collide with a subsequently committed ADR. The preview should be unnumbered.

5. **Dead code** — `adr_create.py` exists as an empty file. It was gutted during the two-phase refactor but never deleted.

---

## Design Goals

- Fix the `\n` serialization bug at tool entry points
- Remove eager numbering from previews
- Add `Supersedes` as a first-class metadata field (multi-value)
- Add suggest→commit correlation via `draft_id`
- Add content quality signals (word count warnings, not hard blocks)
- Define the ADR format as a JSON schema
- Clean up dead code

---

## Architecture

### Layer Mapping

 | Component | Layer | Responsibility |
 | ----------- | ------- | ---------------- |
 | `helpers/adr_md.py` | Helper | ADR dataclass, parser, generator |
 | `tools/adr_suggest.py` | Tool | Preview generation (unnumbered), unescape, word count, draft ID |
 | `tools/adr_commit.py` | Tool | Disk write, numbering, unescape, warnings, draft ID correlation |
 | `tools/adr_read.py` | Tool | No changes |
 | `tools/adr_search.py` | Tool | No changes |
 | `server.py` | Server | Registration updates |
 | `schemas/ADR_MARKDOWN_SCHEMA.json` | Schema | Format definition (documentation for agents) |

Dependency direction: `server.py` → `tools/*` → `helpers/adr_md.py` (unchanged).

---

## Change Specifications

### 1. Unnumbered Previews in `adr_suggest`

**Problem:** `adr_suggest` calls `next_adr_number(workspace_root)` and shows a real number in the preview. This number may be stale by the time `adr_commit` runs.

**Change:** Remove the `next_adr_number()` call from `adr_suggest`. The preview title becomes `ADR-DRAFT: {title}` instead of `ADR-NNN: {title}`. The `number` field in the ADR dataclass is set to `0` (or a sentinel) during preview generation.

**`generate_adr` update:** When `adr.number == 0`, emit `# ADR-DRAFT: {title}` instead of `# ADR-000: {title}`.

**Draft ID:** `adr_suggest` derives a `draft_id` from the title by slugifying it (e.g. title "Use ONNX Runtime" → `draft_id` "use-onnx-runtime"). This is a correlation key only — not persisted, not ordered, not a persistent draft. `adr_commit` accepts an optional `draft_id` parameter so the caller can say "commit the draft I previewed earlier." The number is still assigned fresh at commit time. ADRs can be suggested and committed in any order regardless of `draft_id`.

**Return value change:**

 | Field | Before | After |
 | ------- | -------- | ------- |
 | `number` | `int` (real number) | Removed from response |
 | `filename` | `str` (real filename) | Removed from response |
 | `markdown` | Preview with real number | Preview with `ADR-DRAFT` |
 | `title` | `str` | `str` (unchanged) |
 | `draft_id` | — | `str` (new, slug derived from title) |
 | `word_count` | — | `int` (new, see §5) |

**`adr_commit` change:** Accepts an optional `draft_id: str = ""` parameter. This is for caller-side correlation only — `adr_commit` does not use it internally. It already calls `next_adr_number()` independently in its retry loop.

### 2. Fix `\n` Serialization Bug

**Problem:** When MCP transports content containing newlines, the JSON serialization converts `\n` to the literal two-character string `\n`. The ADR tools receive these escaped strings and write them directly to markdown. ADR-007 demonstrates this: its Context section contains visible `\n` instead of line breaks.

**Change:** Add a helper function `_unescape_literal_newlines(text: str) -> str` in `adr_md.py` that replaces the two-character sequence `\n` with an actual newline character (`\x0a`). Also handle `\t` → tab for completeness.

**Application point:** Both `adr_suggest` and `adr_commit` call `_unescape_literal_newlines()` on all body-text parameters (`context`, `decision`, `consequences`, `references`, and each `extra_sections[].content`) before passing them to the `ADR` dataclass. This is a tool-level concern — the helper/generator remain unaware of transport encoding.

**Not applied to:** `title`, `status`, `tags`, `source_log`, `supersedes` — these are single-line metadata fields where literal `\n` would be a genuine error, not a transport artifact.

### 3. Add `Supersedes` Field (Multi-Value)

**Problem:** ADR-013 uses an informal `**Supersedes:** ADR-007 — Tag Editor Service Home (LibraryService Extension via Mixin)` line that the parser does not extract into a structured field. Supersession is a first-class ADR relationship that should be in the dataclass. An ADR may supersede multiple prior ADRs.

**Data model change:**

```
# Before
@dataclass
class ADR:
    number: int
    title: str
    status: str
    date: str
    tags: list[str] = field(default_factory=list)
    source_log: str | None = None
    sections: dict[str, str] = field(default_factory=dict)

# After
@dataclass
class ADR:
    number: int
    title: str
    status: str
    date: str
    tags: list[str] = field(default_factory=list)
    source_log: str | None = None
    supersedes: list[str] = field(default_factory=list)  # NEW — e.g. ["ADR-007", "ADR-012"]
    sections: dict[str, str] = field(default_factory=dict)
```

**Parser changes (`parse_adr` and `parse_adr_metadata`):** Recognize `**Supersedes:**` as a metadata key. Parse comma-separated values into the `supersedes` list (matching how Tags works). Example: `**Supersedes:** ADR-007, ADR-012` → `["ADR-007", "ADR-012"]`.

**Generator change (`generate_adr`):** If `adr.supersedes` is non-empty, emit `**Supersedes:** {comma-separated values}` after `Source Log` in the metadata block. Single `**Supersedes:**` line with comma-separated values.

**Tool signature changes:** Both `adr_suggest` and `adr_commit` gain an optional `supersedes: list[str] = []` parameter (a list of ADR identifiers). When non-empty, it is passed through to the ADR dataclass.

**Validation:** Each entry in the `supersedes` list should match the pattern `ADR-\d{3}`. Warn but do not block on format mismatches — the field is advisory.

### 4. Create `ADR_MARKDOWN_SCHEMA.json`

**Location:** `code-intel/schemas/ADR_MARKDOWN_SCHEMA.json` (alongside existing `PLAN_MARKDOWN_SCHEMA.json`).

**Purpose:** Machine-readable definition of the ADR markdown format. Serves as documentation for agents generating ADR content.

**Schema structure (conceptual — not implementation code):**

- **Required metadata fields:** title (pattern: `# ADR-NNN: {text}` or `# ADR-DRAFT: {text}`), status (enum: Proposed/Accepted/Deprecated/Superseded), date (ISO 8601), tags (comma-separated, min 1)
- **Optional metadata fields:** source_log (pattern: `{agent-name}#L{number}`), supersedes (comma-separated list, each matching `ADR-\d{3}`)
- **Required sections:** Context, Decision, Consequences
- **Optional sections:** References, any custom `## Heading`
- **Section ordering:** Context → Decision → Consequences → (extras) → References (last)
- **Content constraints:** Each required section must be non-empty. Total body word count across Context + Decision + Consequences should be ≥100 (advisory).

### 5. Minimum Content Heuristic

**Problem:** ADR-001 has ~30 words total across its three body sections. The tools accept this silently.

**Change in `adr_commit`:** After building the ADR, count words in Context + Decision + Consequences. If total < 100, include a `"content_warning"` key in the success response: `"ADR has only N words across body sections (minimum recommended: 100). Consider expanding before accepting."`  This is advisory — does not block creation.

**Change in `adr_suggest`:** Include `"word_count": N` in the response so the calling agent can see the count before committing.

**Word counting:** Simple `len(text.split())` across concatenated section content. No need for sophisticated NLP.

### 6. Unique `source_log` Advisory

**Problem:** Multiple ADRs could reference the same log entry, which may indicate copy-paste or insufficient traceability.

**Change in `adr_commit`:** Before writing, scan existing `ADR-*.md` files using `parse_adr_metadata()` to collect all `source_log` values. If the new ADR's `source_log` matches an existing one, include a `"source_log_warning"` key in the success response: `"source_log '{value}' is also used by ADR-NNN. Consider using a unique log reference."`  Does not block creation.

### 7. Review Gate in Response

**Problem:** `adr_commit` returns `{"path": ..., "number": ..., "title": ...}` — the calling agent cannot verify what was written without a separate `adr_read` call.

**Change in `adr_commit`:** Add `"markdown": rendered_markdown` to the success response. The calling agent can inspect the full rendered ADR in the commit response.

**`adr_suggest` already returns `"markdown"`** — no change needed there.

### 8. Clean Up `adr_create.py`

**Current state:** `code-intel/src/mcp_code_intel/tools/adr_create.py` is an empty file. It was gutted during the two-phase suggest/commit refactor.

**Change:** Delete the file. Remove any remaining imports or references in `server.py` or `__init__.py`.

---

## Files to Modify

 | File | Changes |
 | ------ | --------- |
 | `code-intel/src/mcp_code_intel/helpers/adr_md.py` | Add `supersedes: list[str]` to ADR dataclass. Add `_unescape_literal_newlines()`. Update `parse_adr()` and `parse_adr_metadata()` to extract Supersedes as comma-separated list. Update `generate_adr()` to emit Supersedes and handle `number == 0` for draft titles. |
 | `code-intel/src/mcp_code_intel/tools/adr_suggest.py` | Remove `next_adr_number()` call. Set `number=0`. Add `supersedes` param (`list[str]`). Call `_unescape_literal_newlines()` on body fields. Add `word_count` and `draft_id` to response. Remove `number` and `filename` from response. |
 | `code-intel/src/mcp_code_intel/tools/adr_commit.py` | Add `supersedes` param (`list[str]`). Add optional `draft_id` param (correlation only). Call `_unescape_literal_newlines()` on body fields. Add `markdown` to success response. Add content warning logic. Add source_log duplicate check. |
 | `code-intel/src/mcp_code_intel/server.py` | Update `adr_suggest` and `adr_commit` wrapper signatures to include `supersedes` and `draft_id`. Remove any `adr_create` references. |
 | `code-intel/tests/test_adr_tools.py` | Update existing tests for changed return values (no `number`/`filename` in suggest, new `draft_id`). Add tests for: unescape, supersedes field (multi-value), word count, source_log warning, markdown in commit response, draft title format, draft_id generation and correlation. |

## Files to Create

 | File | Purpose |
 | ------ | --------- |
 | `code-intel/schemas/ADR_MARKDOWN_SCHEMA.json` | ADR format JSON schema (documentation for agents) |

## Files to Delete

 | File | Reason |
 | ------ | --------- |
 | `code-intel/src/mcp_code_intel/tools/adr_create.py` | Empty file, dead code from pre-two-phase refactor |

---

## Constraints

- **No breaking changes to `adr_read` or `adr_search`** — these tools consume existing ADRs and must continue working with both old-format (no Supersedes) and new-format ADRs.
- **Backward-compatible parsing** — `parse_adr()` must handle ADRs with or without `Supersedes` metadata. Missing Supersedes → empty list.
- **Advisory warnings only** — Content length and source_log uniqueness checks produce warnings in tool responses. They never block ADR creation or commit.
- **No retroactive fixup** — This design does not auto-repair existing ADRs. Issues in existing ADRs are addressed separately by humans or agents.
- **Draft ID is stateless** — `draft_id` is a derived slug, not a stored resource. No server-side state is created by `adr_suggest`.

---

## Open Questions

All resolved — no remaining open questions.
