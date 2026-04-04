# ADR-015: Cross-Page Selection Pattern for Paginated Bulk Operations

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** frontend, ux, patterns, pagination  
**Source Log:** rnd-manager#L3  

## Context

The Tag Editor requires bulk operations (rename, merge, split) across potentially thousands of songs that span multiple pages of server-side paginated results (per ADR-012). Standard table selection only tracks rows on the currently visible page — selecting items on page 1, navigating to page 3, and selecting more items loses the page 1 selections.

This is a general UX problem for any paginated bulk-operation UI, not specific to the Tag Editor. Other features (library management, playlist editing) will face the same challenge. A reusable pattern avoids reinventing this for each feature.

## Decision

Adopt a cross-page selection pattern as a reusable frontend pattern for paginated bulk-operation UIs.

**Core mechanics:**
- Maintain a `Set<string>` of selected item IDs in React state, independent of the currently-loaded page
- Selecting/deselecting rows on any page adds/removes IDs from the set — navigation between pages preserves selections
- Display a persistent selected count (e.g., "47 songs selected across 3 pages") visible regardless of current page
- Bulk operations apply to ALL selected items in the set, not just the currently visible page

**"Select All Matching" behavior:**
- "Select All Matching" sends the current filter/search criteria to the backend, which returns the full set of matching IDs (lightweight ID-only query, not full documents)
- This allows selecting thousands of items without loading them all into the frontend
- The returned IDs are added to the selection set
- A "Clear Selection" action empties the set

**Pattern scope:**
- This is a general-purpose frontend pattern, not Tag Editor-specific
- Implemented as a reusable hook or utility (e.g., `useCrossPageSelection`)
- Any paginated UI with bulk operations can adopt it
- The pattern is purely client-side state management — no backend changes beyond the "get matching IDs" endpoint

## Consequences

**Positive:**
- Users can select across pages without losing selections — intuitive bulk operation UX
- Reusable across features — Tag Editor, library management, playlists, etc.
- "Select All Matching" scales to large result sets without loading full documents
- Clear visual feedback ("N items selected") prevents confusion about selection scope

**Negative:**
- Memory usage grows with selection size (but `Set<string>` of IDs is lightweight — 10K IDs ≈ 200KB)
- "Select All Matching" requires a backend endpoint per feature (ID-only query)
- Stale selections possible if items are deleted between selection and action — bulk operations must handle missing IDs gracefully

**Neutral:**
- Does not dictate UI component library — works with MUI DataGrid, custom tables, or any list
- Does not prescribe how bulk operations are dispatched — only how selections are maintained

## References

DD-tag-editor.md, ADR-012 (server-side pagination)
