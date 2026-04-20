# ADR-027: Extract Shared Dependencies to Break Intra-Layer Circular Imports

**Status:** Accepted  
**Date:** 2026-04-20  
**Tags:** conventions, imports, architecture, circular-imports  
**Source Log:** agent#L1  

## Context

ADR-026 establishes that all imports must be at module level and prohibits deferred imports except for heavy third-party libraries and DI wiring. Its reasoning assumes zero circular imports, which holds across layers (import-linter enforces downward-only dependencies). However, same-layer lateral imports are explicitly allowed by the architecture rules — components may import other components, workflows may import other workflows. Within a layer, circular import chains can and do occur.

A concrete example exists in `components/ml/`: `ml_backbone` → `ml_base` → `resources/ml_vram_coordinator_comp` → (via `resources/__init__.py`) `ml_capacity_probe_comp` → `ml_cache` → `ml_backbone`. The current mitigation is a lazy `__init__.py` in `resources/` that defers the import at package level — effectively a deferred import disguised as a lazy module pattern, contradicting ADR-026's intent.

ADR-026 doesn't address this scenario. Adding "intra-layer cycles" as a deferred-import exception would be a bandage. The cycle itself is the problem: it signals that a module depends on something at a level it shouldn't.

## Decision

**When an intra-layer circular import is detected, resolve it by extracting the shared dependency — not by deferring imports.**

A circular import within a layer means two or more modules mutually depend on each other at module level. This indicates a shared concept (type, function, constant) lives in the wrong module. The fix is structural:

1. **Identify the shared resource** that creates the cycle — typically a type, base class, or utility function that both sides of the cycle need.
2. **Extract it** into a lower-level module that both participants can import without forming a loop. This may mean moving it to an existing module deeper in the dependency chain, or creating a new focused module.
3. **Verify the cycle is broken** by confirming all imports remain at module level with no deferred imports or lazy `__init__.py` workarounds.

Lazy `__init__.py` patterns (using `__getattr__` + `importlib.import_module`) are not an acceptable resolution for circular imports. They hide the cycle instead of fixing it, and they defeat static analysis just like function-body deferrals do.

This decision complements ADR-026: top-level imports remain the rule, and the way to maintain that rule when a cycle appears is to fix the architecture, not work around the import system.

## Consequences

**Cycles become architectural signals.** A circular import is treated as a design smell requiring structural resolution, not an import-ordering problem.

**No new deferred-import exceptions.** ADR-026's exception list stays unchanged. Intra-layer cycles are fixed by extraction, not deferral.

**Lazy `__init__.py` cleanup.** Existing lazy package inits that exist solely to break circular imports should be replaced with proper extractions during normal maintenance.

**Static analysis remains whole.** Import-linter and pyright continue to see the full dependency graph at module level.

## References

- ADR-026: Top-Level Imports by Default
- Architecture rules: lateral (same-layer) imports are allowed; upward imports are forbidden
- Current example: `components/ml/onnx/ml_base.py` → `components/ml/resources/` cycle
