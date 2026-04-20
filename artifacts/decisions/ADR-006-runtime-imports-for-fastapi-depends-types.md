# ADR-006: Runtime Imports for FastAPI Depends Types

**Status:** Accepted  
**Date:** 2026-04-03  
**Tags:** fastapi, interfaces, imports, convention  
**Source Log:** support-debugger#L1  

## Context

Several API endpoint files used `from __future__ import annotations` (PEP 563) combined with `TYPE_CHECKING`-guarded imports for service types used in `Annotated[ServiceType, Depends(factory)]` parameters. This caused `/openapi.json` generation to fail with a Pydantic `class-not-fully-defined` error: when all annotations are strings, FastAPI cannot resolve the `Depends()` metadata, falls back to treating the parameter as a `Query`, and Pydantic fails to build a TypeAdapter for the unresolvable forward reference.

The `TYPE_CHECKING` guards were overcautious — interfaces importing services is a **downward** dependency (interfaces → services), which is the correct direction per the project's layer rules. No circular imports existed.

## Decision

In FastAPI route files that use `from __future__ import annotations`, service types used in `Depends()` annotations must be imported at runtime (not under `TYPE_CHECKING`). This is architecturally valid: interfaces depend on services.

Files corrected: `public_if.py`, `admin_if.py`, `navidrome_v1_if.py`, `vectors_if.py`.

Files already correct (no `from __future__ import annotations`): `analytics_if.py`, `calibration_if.py`, `info_if.py` — these use string-quoted annotations which FastAPI can still resolve because `Depends()` is visible at definition time.

## Consequences

**Convention:** Any new FastAPI route file using `from __future__ import annotations` must import `Depends()` parameter types at runtime. `TYPE_CHECKING` guards are only for types used in non-runtime contexts (type hints that FastAPI/Pydantic don't need to resolve).

## References

- Pydantic error: <https://errors.pydantic.dev/2.12/u/class-not-fully-defined>
- Layer rules: interfaces → services → workflows → components → persistence/helpers
