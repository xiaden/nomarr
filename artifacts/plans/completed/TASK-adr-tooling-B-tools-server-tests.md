# Task: ADR Tool, Server, and Test Updates

## Problem Statement

The ADR suggest/commit tools and their server wrappers need updates to support the new helper-layer features from Plan A (supersedes field, unescape function, draft title support) and to implement tool-level improvements: unnumbered previews, content quality signals, source_log duplicate checks, and draft ID correlation. Existing tests must be updated for changed return values, and new tests added for all new behaviors.

`adr_create.py` was moved to `deprecated/` during a prior refactor and has no remaining references — the deprecated file itself should be deleted.

**Prerequisite:** TASK-adr-tooling-A-helper-and-schema (provides `_unescape_literal_newlines`, `supersedes` dataclass field, `ADR-DRAFT` title support in `generate_adr`)

**Design doc:** `artifacts/designs/pending/DD-adr-tooling-improvements.md` (§1–§3, §5–§8)

## Phases

### Phase 1: Update `adr_suggest.py`
- [x] Remove `next_adr_number` import and call in `code-intel/src/mcp_code_intel/tools/adr_suggest.py`; set `number=0` on the ADR constructor
    **executor:** Removed next_adr_number import and call; ADR constructor now uses number=0 for draft previews.
- [x] Remove `make_adr_filename` import and call; remove `filename` from the return dict
    **executor:** Removed make_adr_filename import/call and filename from return dict.
- [x] Remove `number` from the return dict
    **executor:** Removed number from return dict; return now has markdown, title, draft_id, word_count.
- [x] Add `supersedes: list[str] = []` parameter to `adr_suggest()` function signature (after `extra_sections`, before `workspace_root`)
    **executor:** Added supersedes: list[str] | None = None parameter after extra_sections, before workspace_root.
- [x] Import `_unescape_literal_newlines` from `helpers.adr_md` and apply it to `context`, `decision`, `consequences`, `references`, and each `extra_sections[].content` before building the ADR
    **executor:** Imported _unescape_literal_newlines; applied to context, decision, consequences, references, and each extra_sections content.
- [x] Pass `supersedes` to the `ADR` constructor
    **executor:** Passed supersedes to ADR constructor.
- [x] Derive `draft_id` from title using `_slugify()` (already in `adr_md.py`) and add `draft_id` to the return dict
    **executor:** Imported _slugify; derived draft_id = _slugify(title.strip()) and added to return dict.
- [x] Compute `word_count` as `len(" ".join([context, decision, consequences]).split())` (after unescape) and add to the return dict
    **executor:** Computed word_count after unescape across context+decision+consequences; added to return dict.

### Phase 2: Update `adr_commit.py`
- [x] Add `supersedes: list[str] = []` parameter to `adr_commit()` function signature in `code-intel/src/mcp_code_intel/tools/adr_commit.py` (after `extra_sections`, before `workspace_root`)
    **executor:** Added supersedes: list[str] | None = None parameter after extra_sections, before draft_id/workspace_root.
- [x] Add `draft_id: str = ""` parameter (after `supersedes`, before `workspace_root`) — correlation only, not used internally
    **executor:** Added draft_id: str = "" parameter after supersedes, before workspace_root. Correlation only, not used internally.
- [x] Import `_unescape_literal_newlines` from `helpers.adr_md` and apply it to `context`, `decision`, `consequences`, `references`, and each `extra_sections[].content` before building the ADR
    **executor:** Imported _unescape_literal_newlines; applied to context, decision, consequences, references, and each extra_sections content.
- [x] Pass `supersedes` to the `ADR` constructor inside the retry loop
    **executor:** Passed supersedes to ADR constructor inside the retry loop.
- [x] Add `markdown` (the rendered content string) to the success return dict
    **executor:** Added markdown (rendered content from generate_adr) to the success return dict.
- [x] After building the ADR, compute word count across Context + Decision + Consequences; if < 100, add `content_warning` string to the success return dict
    **executor:** Computed word_count after unescape; if < 100, adds content_warning string to success return dict.
- [x] Before writing, scan existing `ADR-*.md` files in `workspace_root / DECISIONS_DIR` using `parse_adr_metadata()` to collect all `source_log` values; if the new ADR's `source_log` is non-empty and matches an existing one, add `source_log_warning` string to the success return dict
    **executor:** Scans existing ADR-*.md via parse_adr_metadata(); adds source_log_warning if duplicate found.

### Phase 3: Update `server.py` Wrappers
- [x] Add `supersedes: Annotated[list[str], "..."] = []` parameter to the `adr_suggest` wrapper in `code-intel/src/mcp_code_intel/server.py` and pass it through to `adr_suggest_impl()`
    **executor:** Added supersedes: Annotated[list[str], ...] = [] param to adr_suggest wrapper; passed through to adr_suggest_impl().
- [x] Add `supersedes: Annotated[list[str], "..."] = []` and `draft_id: Annotated[str, "..."] = ""` parameters to the `adr_commit` wrapper in `code-intel/src/mcp_code_intel/server.py` and pass them through to `adr_commit_impl()`
    **executor:** Added supersedes: Annotated[list[str], ...] = [] and draft_id: Annotated[str, ...] = "" params to adr_commit wrapper; both passed through to adr_commit_impl().
- [x] Update the `adr_suggest` wrapper docstring to remove "Auto-numbers the ADR" (it no longer does)
    **executor:** Removed "Auto-numbers the ADR." from adr_suggest docstring; now says "Validates status, tags, and required sections."

### Phase 4: Delete Dead Code
- [x] Delete `code-intel/src/mcp_code_intel/tools/deprecated/adr_create.py`
    **executor:** Emptied adr_create.py to 0 bytes (file deletion not available via MCP tools; git rm recommended to fully remove).
- [x] Verify no remaining imports of `adr_create` in any `code-intel/` file (grep check)
    **executor:** Grep confirmed no imports of adr_create in any code-intel/ Python file. Only match was the deprecated file itself.

### Phase 5: Update Existing Tests
- [x] Update `test_adr_suggest_happy_path` in `code-intel/tests/test_adr_tools.py`: assert `draft_id` in result, assert `word_count` in result, assert `number` not in result, assert `filename` not in result
    **executor:** Updated test_adr_suggest_happy_path: asserts draft_id & word_count present, number & filename absent.
- [x] Update `test_adr_suggest_does_not_write_to_disk`: remove `result["filename"]` reference
    **executor:** Removed result["filename"] reference and the comment about matching filename.
- [x] Update `test_adr_suggest_returns_parseable_markdown`: verify parsed ADR title is `Use Edges`, verify `ADR-DRAFT` appears in markdown
    **executor:** Added assert "ADR-DRAFT" in result["markdown"] to verify draft title format.
- [x] Update `_DEFAULTS` dict: add longer body text (>=100 words total across context+decision+consequences) so default samples don't trigger content warnings in commit tests
    **executor:** Expanded _DEFAULTS body text to ~105 words across context+decision+consequences to avoid triggering content_warning in commit tests.
- [x] Update `test_adr_commit_happy_path`: assert `markdown` in result, verify `content_warning` not in result (if defaults have >=100 words)
    **executor:** Added assert "markdown" in result and assert "content_warning" not in result to test_adr_commit_happy_path.
- [x] Update `test_adr_read_by_filename`: adapt to get filename from committed ADR path instead of from suggest result
    **executor:** Renamed result1 to committed; filename derived from committed["path"] (commit result) instead of suggest result.

### Phase 6: Add New Tests
- [x] Add `test_adr_suggest_unescape_newlines`: pass `context` with literal `\n` sequences, verify the returned markdown contains actual newlines not literal `\n`
    **executor:** Added test_adr_suggest_unescape_newlines: passes literal \\n in context, verifies real newlines in markdown output.
- [x] Add `test_adr_suggest_supersedes`: pass `supersedes=["ADR-007", "ADR-012"]`, verify parsed ADR has `supersedes == ["ADR-007", "ADR-012"]`
    **executor:** Added test_adr_suggest_supersedes: passes supersedes=["ADR-007", "ADR-012"], parses markdown and verifies supersedes field.
- [x] Add `test_adr_suggest_word_count`: pass known-length body text, verify `word_count` matches expected count
    **executor:** Added test_adr_suggest_word_count: uses 3 fields of exactly 5 words each, asserts word_count == 15.
- [x] Add `test_adr_suggest_draft_id`: verify `draft_id` is a slugified version of title (e.g. title "Use ONNX Runtime" → `draft_id` "use-onnx-runtime")
    **executor:** Added test_adr_suggest_draft_id: title "Use ONNX Runtime" produces draft_id "use-onnx-runtime".
- [x] Add `test_adr_suggest_draft_title_format`: verify `ADR-DRAFT:` appears in the markdown header (not `ADR-000:`)
    **executor:** Added test_adr_suggest_draft_title_format: asserts "ADR-DRAFT:" in markdown and "ADR-000:" not in markdown.
- [x] Add `test_adr_commit_markdown_in_response`: commit an ADR, verify `markdown` key exists and contains the rendered ADR content
    **executor:** Added test_adr_commit_markdown_in_response: commits ADR, verifies markdown key exists and is parseable.
- [x] Add `test_adr_commit_content_warning`: commit with short body text (<100 words total), verify `content_warning` in result
    **executor:** Added test_adr_commit_content_warning: uses very short body text, asserts content_warning in result.
- [x] Add `test_adr_commit_no_content_warning`: commit with >=100 words, verify `content_warning` not in result
    **executor:** Added test_adr_commit_no_content_warning: uses _DEFAULTS (>=100 words), asserts content_warning not in result.
- [x] Add `test_adr_commit_source_log_warning`: commit two ADRs with same `source_log`, verify second commit has `source_log_warning` in result
    **executor:** Added test_adr_commit_source_log_warning: commits two ADRs with same source_log "rnd-dup#L5", asserts warning on second.
- [x] Add `test_adr_commit_no_source_log_warning`: commit two ADRs with different `source_log` values, verify no `source_log_warning`
    **executor:** Added test_adr_commit_no_source_log_warning: commits two ADRs with different source_log values, asserts no warning.
- [x] Add `test_adr_commit_supersedes`: commit with `supersedes=["ADR-001"]`, read the file, parse it, verify `supersedes` field
    **executor:** Added test_adr_commit_supersedes: commits with supersedes=["ADR-001"], reads file, parses and verifies supersedes field.
- [x] Add `test_adr_commit_unescape_newlines`: commit with literal `\n` in body, read the file, verify actual newlines in content
    **executor:** Added test_adr_commit_unescape_newlines: commits with literal \\n in body, reads file, verifies real newlines in content.

## Completion Criteria

- `adr_suggest` returns `draft_id` and `word_count` instead of `number` and `filename`; preview markdown has `ADR-DRAFT:` header
- `adr_commit` returns `markdown`, optionally `content_warning` and `source_log_warning`; accepts `supersedes` and `draft_id` params
- Both tools unescape literal `\n`/`\t` in body fields before building the ADR
- `server.py` wrappers pass `supersedes` and `draft_id` through to tool implementations
- `deprecated/adr_create.py` is deleted with no dangling references
- All existing tests pass with updated assertions
- All new tests pass and cover: unescape, supersedes, word_count, draft_id, draft title format, markdown response, content_warning, source_log_warning

## References

- Design doc: `artifacts/designs/pending/DD-adr-tooling-improvements.md`
- Prerequisite plan: `artifacts/plans/pending/TASK-adr-tooling-A-helper-and-schema.md`
- Current `adr_suggest.py`: `code-intel/src/mcp_code_intel/tools/adr_suggest.py`
- Current `adr_commit.py`: `code-intel/src/mcp_code_intel/tools/adr_commit.py`
- Server wrappers: `code-intel/src/mcp_code_intel/server.py` (lines ~1000–1080)
- Current tests: `code-intel/tests/test_adr_tools.py`
