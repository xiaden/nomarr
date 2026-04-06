# ADR-020: REST API Naming Convention: Kebab-Case Full Words

**Status:** Accepted  
**Date:** 2026-04-06  
**Tags:** api, naming, convention, rest  
**Source Log:** rnd-manager#L20  

## Context

Nomarr exposes ~108 REST endpoints accumulated organically over alpha development. Naming is inconsistent: a mix of kebab-case and flat words, abbreviations (`/ml`, `/fs`, `/auth`), inconsistent singular/plural usage, and no documented convention. A full API restructure is underway (see DD-api-restructure) to consolidate endpoints under a coherent URL scheme. A naming convention is needed to guide both the restructure and all future endpoint additions.

## Decision

All REST API URL segments follow these rules:

1. **Kebab-case, full words only.** No abbreviations, even for common terms:
   - `/machine-learning` not `/ml`
   - `/file-system` not `/fs`
   - `/authentication` not `/auth`

2. **Two segment types, same rules:**
   - **Entity resources** use singular nouns: `/library`, `/model`, `/vector`, `/tag`
   - **Process/domain groups** use their natural name: `/analytics`, `/authentication`, `/tag-curation`, `/calibration`

3. **No exceptions.** Both segment types follow kebab-case full words universally. There is no exceptions list.

4. **Query parameters** use snake_case: `?sort_by=name&include_hidden=true`

5. **Path parameters** use the entity's natural identifier: `/library/{library_key}/track/{track_key}`

New endpoints must follow this convention. Existing endpoints are renamed as part of the API restructure.

## Consequences

- All ~108 endpoints renamed to match the convention during the API restructure
- Frontend API clients must update all endpoint references
- New endpoints added after this decision must follow the convention — PR review enforces compliance
- No abbreviations means slightly longer URLs but eliminates ambiguity (`/auth` could mean authentication or authorization)
- The convention is simple enough to apply without a lookup table — if you can describe it in plain English, that's the URL segment
- Router prefix mapping updated: `machine-learning`, `file-system`, `authentication` replace abbreviated forms

## References

DD-api-restructure
