# ADR-011: MUI DataGrid Inline Cell Editing for Single-Tag Edits

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** frontend, ux, tag-editor  
**Source Log:** rnd-manager#L1  

## Context

The Tag Editor needs a UX pattern for editing one tag on one song. Three approaches were considered:\n\n1. **Inline cell editing:** Click a cell, edit in-place. Native MUI DataGrid feature via `editable: true` + `processRowUpdate`.\n2. **Popover:** Click a cell, open a popover with a form. More control but heavier UX for simple edits.\n3. **Side panel:** Select a row, edit in a side panel. Good for complex forms but overkill for single-value edits.\n\nMUI DataGrid (community edition, v8.27) supports inline editing natively with custom `renderEditCell` for autocomplete. The project already uses @mui/x-data-grid.

## Decision

Use MUI DataGrid native inline cell editing:\n- `editable: true` on user-editable tag columns\n- `processRowUpdate` callback to commit changes via `useCommitTagEdits` hook\n- Custom `renderEditCell` with MUI Autocomplete for tag value suggestions (backed by `useUniqueTagValues`)\n- `nom:` columns rendered as read-only (grey cells, `editable: false`)\n- Optimistic update: displayed row updates immediately, rolls back on API error

## Consequences

**Positive:**\n- Familiar spreadsheet-like UX — click, type, tab to next cell\n- No new dependencies — uses existing MUI DataGrid capabilities\n- Autocomplete reduces typos and encourages tag reuse\n- Zero-overhead for read-only browsing (editing only activates on click)\n\n**Negative:**\n- MUI DataGrid community edition doesn't support clipboard paste across multiple cells\n- No native undo (Ctrl+Z) for cell edits — would require custom implementation\n- Dynamic column changes (when tag keys change) may cause DataGrid remount — needs testing\n\n**Mitigations:**\n- Bulk edit dialog covers the multi-cell paste use case\n- Undo deferred to Open Questions — not critical for alpha

## References

DD-tag-editor.md
