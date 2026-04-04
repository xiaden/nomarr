# ADR-012: Server-Side Pagination for Tag Editor Results

**Status:** Accepted  
**Date:** 2026-04-04  
**Tags:** frontend, performance, tag-editor  
**Source Log:** rnd-manager#L1  

## Context

The Tag Editor grid may display results from libraries with 10k+ files. Three pagination strategies were considered:\n\n1. **Client-side:** Load all results, paginate in browser. Simple but memory-intensive and slow initial load for large libraries.\n2. **Virtual scroll:** Render visible rows only with infinite scroll. Good UX but complex implementation and incompatible with MUI DataGrid community edition's selection model.\n3. **Server-side pagination:** MUI DataGrid `paginationMode="server"` with `limit`/`offset` query params. The existing `search_library_files` endpoint already supports these parameters.\n\nMUI DataGrid community edition handles server-side pagination natively with `paginationModel`, `onPaginationModelChange`, and `rowCount` props.

## Decision

Use MUI DataGrid `paginationMode="server"` with the existing `search_library_files` endpoint's `limit`/`offset` support.\n\n- Default page size: 50 rows\n- `rowCount` from API response total\n- `onPaginationModelChange` triggers new API fetch via `useTagEditorSearch` hook\n- No new backend work needed — existing endpoint supports this\n- No new dependencies or license requirements

## Consequences

**Positive:**\n- Handles 10k+ file libraries without browser memory issues\n- Reuses existing backend pagination support — zero backend changes\n- MUI DataGrid community edition supports this natively\n- Predictable performance — always loads one page at a time\n\n**Negative:**\n- Page transitions require API round-trip (mitigated by small page size and fast AQL queries)\n- "Select all" across pages requires special handling (select all on server vs. select visible only)\n- Sorting/filtering changes reset to page 1\n\n**Note:** If AQL JOIN performance degrades at 10k+ rows with complex tag filters, server-side cursor pagination may be needed. Profile before optimizing.

## References

DD-tag-editor.md
