# ADR-028: Compose complex types from simpler types instead of redeclaring their fields

**Status:** Proposed  
**Date:** 2026-04-20  
**Tags:** architecture, composition, type-hierarchy, duplication  
**Source Log:** agent#L13  

## Context

The project's layered architecture composes upward: helpers → components → workflows → services. But within layers, types sometimes redeclare fields from simpler types instead of containing them. This creates duplicated metadata with inconsistent naming, type mismatches when both versions are used interchangeably, and maintenance drift when one copy is updated but not the other.

Example: `ONNXHeadModel` redeclares `backbone_name`, `head_type`, `model_name`, `labels`, `is_regression`, and `build_versioned_tag_key()` — all of which already exist on `HeadInfo` with slightly different names (`is_regression_head`, `model_path`). The discovery function builds a `HeadInfo`, extracts labels from it, passes those into `ONNXHeadModel`, and discards the original. Downstream, `HeadOutput.head` is typed `HeadInfo` but receives `ONNXHeadModel`, causing type errors and fragile attribute access that would crash if the two code paths ever mixed.

This pattern violates the same principle the layer architecture enforces at the macro level: higher-complexity constructs should build on lower-complexity ones, not reimplement them.

## Decision

**When a complex type needs metadata or behavior from a simpler type, it holds an instance of that type — it does not redeclare the fields.**

Rules:

1. If type B needs the same data as type A, B contains an A — not copies of A's fields
2. Callers that need metadata access it through the composed instance (e.g. `model.meta.name`)
3. The accessor name for the composed instance is context-dependent — use whatever reads naturally for the domain (`.meta`, `.info`, `.spec`, etc.). Naming conventions may be formalized later once patterns emerge
4. Thin delegation properties are acceptable for API compatibility during migration, but the composed instance is the source of truth
5. Factory functions that build both types pass the simpler type into the complex one instead of extracting fields and discarding it
6. Shared methods live on the simpler type only — the complex type delegates or callers use the composed instance directly

This applies at every layer, not just between layers. The same composition principle that governs helpers → components → workflows → services governs type relationships within a layer.

## Consequences

**Positive:**

- Single source of truth for shared metadata — no naming drift, no field duplication
- Type annotations stay clean — DTOs reference the simpler type, not a union of both
- Factory functions stop building-then-discarding the simpler type
- Consistent with the project's macro architecture (layers compose upward)

**Negative:**

- Existing types that redeclare fields need refactoring to compose instead
- Adds an indirection level for metadata access (e.g. `model.meta.name` vs `model.name`)

**Risks:**

- Delegation properties can accumulate if not cleaned up after migration — enforce that they are temporary

## References

- ADR-027: Extract Shared Dependencies to Break Circular Imports (same principle applied to imports)
- ASR-0011: New ML backends must plug into stable contract (composition gives them a clear metadata type to reuse)
