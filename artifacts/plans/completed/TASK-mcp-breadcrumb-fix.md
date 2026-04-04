# Task: Fix Breadcrumb Formatting Across All MCP Tools

## Problem Statement

After unifying tools onto `ToolOutput`, the breadcrumb text displayed to users has several formatting issues:

1. **Redundant line info** — `_format_line_info` appends `(line 90)` or `(lines 85 to 95)` as text, but the URI already contains `#L90` or `#L85-L95`. The suffix is visual noise.

2. **Action text repeated with header** — When a breadcrumb header is set (e.g. `Found 5 instances`), each file link still renders its own action prefix (`Read`, `Found`), creating redundancy like `Found 5 instances:\nFound file:///...`.

3. **Per-tool breadcrumb phrasing** — Many tools produce awkward or redundant breadcrumb text. Each needs specific copy adjustments.

The fix has two parts: (A) change `_build_breadcrumb` / `_format_file_link_lines` to suppress action/line-info when a header is present, and (B) update each tool's `breadcrumb=` and `action=` values in `server.py` to produce clean output.

**Target format examples:**
```
[read_module_source] Read source:
file:///path/to/file.py#L74-L80

[locate_module_symbol] Located ToolOutput at:
file:///path/to/file.py#L89-L265

[search_file_text] Found 5 instances of 'assistant_content':
file:///path/to/file.py#L97
file:///path/to/file.py#L120

[edit_file_create] Created 1 file(s):
file:///path/to/file.py 3 lines

[plan_read] Read Plan at file:///path/to/plan.md
```

## Phases

### Phase 1: Fix _build_breadcrumb and _format_file_link_lines

- [x] Remove `_format_line_info` suffix from `_format_file_link_lines` — URIs already encode line info via fragments. Drop the `, line N` / `, lines N to M` text entirely from breadcrumb rendering. Keep `_format_line_info` function itself (may be used elsewhere).
    **Notes:** Removed `_format_line_info` call from `_format_file_link_lines` (lines 161-172). URIs already encode line info via `#L` fragments. `_format_line_info` function itself kept (defined at L30, now unused — plan says keep).
- [x] When `breadcrumb` is set (non-empty) and file_links exist, render links as bare `make_file_markdown_link()` URIs without action prefix. When breadcrumb is empty, keep action prefix on links for the auto-generated case.
    **Notes:** Added `bare: bool = False` parameter to `_format_file_link_lines`. When bare=True, action prefixes are suppressed. Updated `_build_breadcrumb` to pass `bare=True` when breadcrumb header is set, keeping action prefix only for the auto-generated (no breadcrumb) case.
- [x] For edit tools that report total lines (create, replace_content): add a `line_count` field to `FileLink` (optional int, default None). When set and breadcrumb is present, append ` {line_count} lines` after the URI instead of the line range fragment.
    **Notes:** Added `line_count: int | None = None` to FileLink (L80). Updated `_format_file_link_lines` to append ` {line_count} lines` suffix when line_count is set (L176).
- [x] Run `lint_project_backend(path="code-intel")` to verify changes
    **Notes:** lint_project_backend(path="code-intel") — 0 errors, 5 files checked.

### Phase 2: Fix read tool breadcrumbs in server.py

- [x] `read_module_source`: set `breadcrumb="Read source:"`, remove action from FileLink (empty string)
    **Notes:** Changed breadcrumb from `f"Read source: {qualified_name}"` to `"Read source:"` (L342). Changed FileLink action from `"Read source"` to `""` (L337). Output: `[read_module_source] Read source:\nfile:///...#L74-L80`
- [x] `read_module_api`: set `breadcrumb=f"Read API for module: {module_name} at:"`, remove action from FileLink
    **Notes:** Changed breadcrumb to `f"Read API for module: {module_name} at:"` (L303). Changed FileLink action to `""` (L300). Output: `[read_module_api] Read API for module: ... at:\nfile:///...`
- [x] `read_file_symbol_at_line`: extract symbol name from result, set `breadcrumb=f"Read {symbol_name} at:"`, remove action from FileLink
    **Notes:** Extracted `qualified_name` from result (falls back to "symbol"). Set `breadcrumb=f"Read {symbol_name} at:"` (L366). Changed FileLink action to `""` (L372). Output: `[read_file_symbol_at_line] Read ToolOutput at:\nfile:///...#L90`
- [x] `read_file_line_range` and `read_file_line`: set `breadcrumb="Read"` with empty action on FileLink so it renders as `[tool] Read\nfile:///...`
    **Notes:** Both tools: Added `breadcrumb="Read"` and `action=""` on FileLink. `read_file_line_range` at L664, `read_file_line` at L714. Output: `[read_file_line_range] Read\nfile:///...#L85-L95` and `[read_file_line] Read\nfile:///...#L90`
- [x] Run `lint_project_backend(path="code-intel")` to verify
    **Notes:** lint_project_backend(path="code-intel") — 0 errors. Fixed 2 E501 line-too-long errors by breaking FileLink args across multiple lines.

### Phase 3: Fix navigation and trace tool breadcrumbs in server.py

- [x] `locate_module_symbol`: set `breadcrumb=f"Located {symbol_name} at:"`, remove action from FileLink
    **Notes:** Changed breadcrumb to `f"Located {symbol_name} at:"` (L406). Changed FileLink action to `""` (L399). Output: `[locate_module_symbol] Located ToolOutput at:\nfile:///...#L89-L265`
- [x] `search_file_text`: set `breadcrumb=f"Found {count} instances of '{search_string}':"`, remove action from FileLink
    **Notes:** Changed breadcrumb to `f"Found {match_count} instance(s) of '{search_string}':"` (L762). Added `action=""` to FileLink (L755). Output: `[search_file_text] Found 5 instance(s) of 'assistant_content':\nfile:///...#L97\nfile:///...#L120`
- [x] `trace_module_calls`: set `breadcrumb=f"Traced calls from: {function} at:"` when file link exists, remove action from FileLink
    **Notes:** Changed breadcrumb to `f"Traced calls from: {function} at:"` (L441). Changed FileLink action to `""` (L436).
- [x] `trace_project_endpoint`: set `breadcrumb=f"Traced endpoint: {endpoint} at:"` when file link exists, remove action from FileLink
    **Notes:** Changed breadcrumb to `f"Traced endpoint: {endpoint} at:"` (L494). Changed FileLink action to `""` (L489).
- [x] Run `lint_project_backend(path="code-intel")` to verify
    **Notes:** lint_project_backend(path="code-intel") — 0 errors, 5 files checked.

### Phase 4: Fix edit and plan tool breadcrumbs in server.py

- [x] `edit_file_create`: set `breadcrumb=f"Created {count} file(s):"`, populate `line_count` on FileLink, remove action
    **Notes:** Set `breadcrumb=f"Created {len(files)} file(s):"` (L1036). Removed start_line/end_line, set action="" and line_count=op.get("end_line") on FileLink. Output: `[edit_file_create] Created 1 file(s):\nfile:///path 3 lines`
- [x] `edit_file_replace_content`: set `breadcrumb="Replaced:"`, populate `line_count` on FileLink, remove action
    **Notes:** Set `breadcrumb="Replaced:"` (L1064). Removed start_line/end_line, set action="" and line_count=op.get("end_line") on FileLink. Output: `[edit_file_replace_content] Replaced:\nfile:///path 3 lines`
- [x] `edit_file_replace_string`: set `breadcrumb=f"Made {count} replacement(s):"`, set FileLink start/end from result context, remove action
    **Notes:** Set `breadcrumb=f"Made {total_replaced} replacement(s):"` (L795). Changed FileLink to action="" with no line range. Gets total from result dict. Output: `[edit_file_replace_string] Made 1 replacement(s):\nfile:///path`
- [x] `edit_file_insert_at_boundary`, `edit_file_insert_at_line`, `edit_file_copy_paste_text`: fix breadcrumb text per user examples, remove action from FileLinks
    **Notes:** Fixed all 3 tools. insert_at_boundary: breadcrumb adds ":" (L1095), action="" (L1088). insert_at_line: breadcrumb adds ":" (L1135), action="" (L1128). copy_paste_text: breadcrumb changed to `f"Pasted text {len(ops)} time(s):"` (L1166), action="" (L1159).
- [x] `edit_file_move`: set `breadcrumb=f"Moved {old_path} to"`, FileLink with no action points to new path, no start_line=1
    **Notes:** Changed breadcrumb to `f"Moved {old_path} to"` (L881). Removed start_line=1 and changed action to "" on FileLink (L878). Output: `[edit_file_move] Moved old to\nfile:///new`
- [x] `plan_read`: set `breadcrumb="Read Plan at"`, no action on FileLink
    **Notes:** Changed breadcrumb to `"Read Plan at"` (L954). Changed FileLink action to `""` (L951). Output: `[plan_read] Read Plan at\nfile:///path/plan.md`
- [x] `plan_complete_step`: set `breadcrumb=f"Completed Phase {p} Step {s} at"`, no action on FileLink
    **Notes:** Parses step_id format `P<n>-S<m>` into `"Completed Phase N Step M at"` (L1004-1008). FileLink already had action="" from P4-S6 context. Output: `[plan_complete_step] Completed Phase 1 Step 1 at\nfile:///path/plan.md`
- [x] Run `lint_project_backend(path="code-intel")` to verify all changes
    **Notes:** lint_project_backend(path="code-intel") — 0 errors, 5 files checked. All phases complete.

## Completion Criteria

- No breadcrumb renders redundant line info text when URI already has line fragment
- No breadcrumb renders action prefix on file links when a header already provides context
- Each tool's breadcrumb matches the target format from the problem statement examples
- `lint_project_backend(path="code-intel")` passes clean
- All 20 tools produce well-formatted user breadcrumbs

## References

- [mcp_output_helper.py](code-intel/src/mcp_code_intel/helpers/mcp_output_helper.py) — ToolOutput, _build_breadcrumb, _format_file_link_lines
- [server.py](code-intel/src/mcp_code_intel/server.py) — all tool wrapper functions
- [TASK-mcp-unified-tool-output.md](plans/completed/TASK-mcp-unified-tool-output.md) — predecessor plan
