# Task: ADR Helper Layer Changes and Schema Definition

## Problem Statement

The ADR tooling in `code-intel/` has several issues traceable to the shared helper module `adr_md.py`:

1. **Missing `supersedes` field** — ADR-013 uses an informal `**Supersedes:**` line that the parser ignores. Supersession is a first-class ADR relationship that needs dataclass, parser, and generator support.
2. **Eager numbering in previews** — `generate_adr` always emits `# ADR-NNN:` even when `number == 0`, producing `# ADR-000:` for drafts. It should emit `# ADR-DRAFT:` when number is 0.
3. **Escaped newline bug** — MCP transport serializes `\n` as literal two-character `\n`. A helper function is needed to unescape these before content reaches the ADR dataclass. (Wiring into tools is Plan B.)
4. **No formal schema** — The ADR markdown format has no machine-readable definition. A JSON schema should be created alongside the existing `PLAN_MARKDOWN_SCHEMA.json`.

This plan covers helper-layer and schema changes only. Tool changes (`adr_suggest`, `adr_commit`), server registration, tests, and dead code cleanup are in Plan B.

**Design doc:** `artifacts/designs/pending/DD-adr-tooling-improvements.md` (§1–§4)

## Phases

### Phase 1: ADR Dataclass Update
- [x] Add `supersedes: list[str] = field(default_factory=list)` field to the `ADR` dataclass in `code-intel/src/mcp_code_intel/helpers/adr_md.py`, positioned after `source_log` and before `sections`
    **Note:** Added `supersedes: list[str] = field(default_factory=list)` after `source_log` and before `sections` in the ADR dataclass.

### Phase 2: Parser Updates
- [x] In `parse_adr()`, add handling for `**Supersedes:**` metadata key — parse comma-separated values into a `list[str]`, stripping whitespace from each entry. Pass the result as `supersedes` to the `ADR` constructor
    **Note:** Added `elif key == "Supersedes"` branch in parse_adr() metadata handling. Comma-separated values parsed into list[str]. Passed as `supersedes=supersedes` to ADR constructor.
- [x] In `parse_adr_metadata()`, add the same `**Supersedes:**` extraction logic and include `supersedes` in the returned dict (default to empty list when absent)
    **Note:** Added `elif key == "Supersedes"` branch in parse_adr_metadata(). Added `supersedes` key to returned dict with default empty list.

### Phase 3: Generator Updates
- [x] In `generate_adr()`, when `adr.supersedes` is non-empty, emit `**Supersedes:** {comma-separated values}  ` line after the Source Log line (or after Tags if no Source Log)
    **Note:** Added `if adr.supersedes:` block after Source Log in generate_adr() metadata section. Emits comma-separated values with trailing two-space line break.
- [x] In `generate_adr()`, when `adr.number == 0`, emit `# ADR-DRAFT: {title}` instead of `# ADR-000: {title}`
    **Note:** Changed title generation: `adr.number == 0` now emits `# ADR-DRAFT: {title}` instead of `# ADR-000: {title}`.

### Phase 4: Unescape Helper Function
- [x] Add `_unescape_literal_newlines(text: str) -> str` function to `adr_md.py` that replaces literal two-character `\n` with actual newline (`\x0a`) and literal `\t` with actual tab (`\x09`)
    **Note:** Added `_unescape_literal_newlines(text: str) -> str` in the helpers section. Also added `DRAFT_TITLE_PATTERN` and updated both parsers to handle `ADR-DRAFT:` titles for round-trip compatibility.

### Phase 5: ADR Markdown Schema
- [x] Create `code-intel/schemas/ADR_MARKDOWN_SCHEMA.json` defining the ADR markdown format per DD §4. Use `PLAN_MARKDOWN_SCHEMA.json` as a style reference. Include: title pattern (`ADR-NNN` and `ADR-DRAFT`), required metadata (status enum, date, tags), optional metadata (source_log, supersedes), required sections (Context, Decision, Consequences), optional sections (References, custom headings), and advisory word count minimum (100 words across body sections)
    **Note:** Created ADR_MARKDOWN_SCHEMA.json (draft-07) with title pattern supporting ADR-NNN and ADR-DRAFT, required metadata (status enum, date, tags), optional metadata (source_log, supersedes), required sections (Context, Decision, Consequences), optional sections (References, custom headings), and advisory word count minimum definition (100 words).

## Completion Criteria

- `ADR` dataclass has `supersedes: list[str]` field with default empty list
- `parse_adr()` extracts `**Supersedes:**` into `adr.supersedes` for both new and old-format ADRs (missing → empty list)
- `parse_adr_metadata()` returns `supersedes` key in its dict
- `generate_adr()` emits `**Supersedes:**` line when non-empty, omits when empty
- `generate_adr()` emits `# ADR-DRAFT: {title}` when `number == 0`
- `_unescape_literal_newlines()` exists and handles `\n` → newline, `\t` → tab
- `ADR_MARKDOWN_SCHEMA.json` exists and is valid JSON Schema (draft-07)
- No changes to tool files, server.py, or test files

## References

- Design doc: `artifacts/designs/pending/DD-adr-tooling-improvements.md`
- Current helper: `code-intel/src/mcp_code_intel/helpers/adr_md.py`
- Schema style reference: `code-intel/schemas/PLAN_MARKDOWN_SCHEMA.json`
