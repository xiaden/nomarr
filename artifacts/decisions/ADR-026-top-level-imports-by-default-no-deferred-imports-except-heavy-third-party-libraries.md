# ADR-026: Top-Level Imports by Default — No Deferred Imports Except Heavy Third-Party Libraries

**Status:** Accepted  
**Date:** 2026-04-20  
**Tags:** conventions, imports, architecture, code-quality  
**Source Log:** agent#L1  

## Context

Deferred imports (imports inside function or method bodies) have appeared in the codebase without consistent justification. Some are legitimate — optional heavy third-party libraries like essentia and onnxruntime that may not be installed in all environments. Others are cargo-culted: standard library or first-party imports placed inside functions "just in case," despite zero circular imports existing in the codebase.

Deferred imports cause real problems:

1. **Broken imports hide until runtime.** A missing or renamed module won't surface until that code path executes — potentially minutes or hours into a running server.
2. **Static analysis blind spots.** Import-linter and pyright cannot trace dependencies inside function bodies. Layer violations in deferred imports go undetected.
3. **Scattered dependency declarations.** When imports are spread through function bodies, the top of the file no longer tells you what the module depends on, making it harder to reason about coupling.
4. **No performance justification.** Nomarr is a long-running server, not a CLI tool. Modules load once at startup. Deferring first-party imports saves nothing meaningful.

Similarly, `TYPE_CHECKING` blocks have appeared in multiple locations within single files. A single consolidated block at the top of the file makes type dependencies immediately visible alongside runtime imports.

This codebase has zero circular imports. The layered architecture (interfaces → services → workflows → components → persistence/helpers) with import-linter enforcement ensures downward-only dependencies. Deferring imports to "prevent" circular imports is solving a problem that doesn't exist.

## Decision

**All imports must be at module level (top of file) by default.** Deferred imports are prohibited unless they meet one of the following exceptions:

### Allowed Exceptions

1. **Heavy third-party libraries that are environment-conditional.** Libraries like `essentia` and `onnxruntime` that may not be installed in all deployment environments may be imported inside function bodies. The deferral must be meaningful — the library is large, optional, or unavailable in some environments.

2. **DI wiring in application entry points.** `app.py` and worker entry point files (e.g., `discovery_worker.py`) import services and components inside initialization functions as part of the dependency injection pattern. This is factory registration, not deferred importing.

### TYPE_CHECKING Convention

`if TYPE_CHECKING:` blocks remain standard practice for type-only imports. Per file, there must be exactly **one** `TYPE_CHECKING` block, placed at the top of the file immediately after runtime imports. This single block declares all type-only dependencies in one place, making it easy to see what types the file uses alongside its runtime dependencies.

### What This Prohibits

- Importing standard library modules inside function bodies (e.g., `import ast` inside a parsing function)
- Importing first-party nomarr modules inside function bodies to "avoid circular imports" when no circular import exists
- Scattering multiple `TYPE_CHECKING` blocks through a file
- Deferring lightweight third-party library imports without environment-conditional justification

## Consequences

**Convention enforced:** New code reviews should reject deferred imports unless they cite one of the two allowed exceptions. Existing deferred imports that don't meet the exceptions should be migrated to top-level during normal maintenance.

**Static analysis coverage improves:** Import-linter and pyright gain full visibility into the dependency graph when imports are at module level.

**Fail-fast behavior:** Import errors surface at startup rather than hiding in rarely-executed code paths.

**TYPE_CHECKING readability:** One consolidated block per file keeps type dependencies visible and co-located with runtime imports.

**ADR-006 unaffected:** The requirement that FastAPI `Depends()` types be runtime-imported (not under `TYPE_CHECKING`) remains in effect and is compatible with this decision — those imports were already at the top of the file.

## References

- ADR-006: Runtime Imports for FastAPI Depends Types
- Layer rules: interfaces → services → workflows → components → persistence/helpers
- Import-linter: enforces layer boundaries at the static import level
