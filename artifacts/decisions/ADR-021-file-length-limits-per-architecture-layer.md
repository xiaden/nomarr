# ADR-021: File Length Limits Per Architecture Layer

**Status:** Accepted  
**Date:** 2026-04-08  
**Tags:** conventions, file-organization, architecture, code-quality  
**Source Log:** support-researcher#L32  

## Context

The Nomarr codebase has grown significantly, with several files exceeding 500–900 lines. File length conventions were established in the per-layer GitHub instructions files (`.github/instructions/*.instructions.md`) but were never formally recorded as an Architecture Decision Record. These conventions have been consistently enforced during code review and used as triggers for refactoring decisions (e.g., the `library_files_aql/` subpackage split, the `library_svc/` mixin package split). This ADR retroactively documents the decision that was already made and is already in practice.

## Decision

File length limits are enforced per architecture layer, as documented in the corresponding `.github/instructions/` files:

 | Layer | Consider Split | MUST Split |
 | ------- | --------------- | ------------ |
 | Components | 300 lines | 500 lines |
 | Services | 300 lines | 500 lines |
 | Interfaces | 300 lines | 500 lines |
 | Workflows | 300 lines | 500 lines |
 | Persistence | 400 lines | 600 lines |

**"Consider split"** means the file should be evaluated for decomposition during the next significant change. **"MUST split"** means the file must be split before new features are added to it.

**Established split patterns:**

- **Persistence subpackage** (`library_files_aql/` pattern): Convert a single-file module into a subpackage with responsibility-named modules and an `__init__.py` aggregator that composes mixin classes into the original class name. Each module must own meaningful query/state behavior — passthrough wrappers are not permitted (per ADR-003).

- **Service mixin package** (`library_svc/` pattern): Convert a single-file service into a package with mixin classes per responsibility area. The `__init__.py` composes the final service class. Helper methods that need `self` should be defined locally per mixin for mypy compatibility rather than shared across mixins.

- **Interface router split**: Split a large router file into multiple router files, each with its own `APIRouter` instance, grouped by endpoint domain (e.g., CRUD vs. scan vs. file operations).

- **Internal method extraction**: For files where the problem is one oversized method rather than too many methods, decompose into well-named private methods. This does not require a package conversion.

The authoritative source for current limits is always the per-layer instructions files in `.github/instructions/`.

## Consequences

- Files exceeding the MUST-split threshold are blocked from receiving new features until split.
- Five files currently exceed hard limits and require splitting: `file_states_aql.py` (981 lines), `tagging_svc.py` (790 lines), `library_if.py` (754 lines), `discovery_worker.py` (662 lines), `worker_system_svc.py` (576 lines).
- Split refactors must update all callers, imports, and tests — they are not trivial renames.
- The persistence layer has a higher threshold (400/600) because AQL query methods are inherently longer than pure Python logic.
- Established patterns (`library_files_aql/`, `library_svc/`) provide proven templates, reducing design risk for future splits.
- New splits must follow the "no passthrough wrappers" constraint — each module must own real logic.

## References

- `.github/instructions/components.instructions.md` — component layer limits
- `.github/instructions/services.instructions.md` — service layer limits
- `.github/instructions/interfaces.instructions.md` — interface layer limits
- `.github/instructions/workflows.instructions.md` — workflow layer limits
- `.github/instructions/persistence.instructions.md` — persistence layer limits
- `nomarr/persistence/database/library_files_aql/` — canonical persistence subpackage pattern
- `nomarr/services/domain/library_svc/` — canonical service mixin package pattern
- ADR-003: Pure Boolean State Graph (no passthrough wrappers constraint)
- ADR-013: Expand TaggingService as Full Tags Vertical Slice (domain ownership over convenience splits)
