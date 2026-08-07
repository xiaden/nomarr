# ADR-042: Simplification Program — Dead Code Removal, Enforcement Consolidation, and ADR Normalization

**Status:** Accepted  
**Date:** 2026-08-06  
**Tags:** architecture, enforcement, persistence, dead-code  
**Supersedes:** ADR-024-aql-subpackage-naming-convention-and-collection-origination-principle.md, ADR-025-schema-driven-persistence-constructor-supersedes-hand-written-aql-conventions.md  

## Context

The PostgreSQL migration (ADR-040) replaced ArangoDB as the persistence store, but the codebase still carried the residue of the old stack and of years of incremental growth:

- **ArangoDB residue:** stale ArangoDB-shaped naming, dead scaffolding, and adapter modules left over from the migration, plus ADRs that still described the ArangoDB architecture as live.
- **Dead code:** accumulated scaffolding, maintenance facades, and superseded modules that no longer had consumers.
- **Overlapping enforcement:** architecture-rule checking was fragmented across overlapping tools — grimp, vulture, radon, deptry, import-linter, and custom scripts (e.g., check-arango-fields.sh) — each checking similar concerns with different rules and different gaps.
- **Mixin sprawl:** service-layer mixins had sprawled into passthrough wrappers and convenience splits that duplicated domain ownership instead of adding behavior.
- **Monolithic facade:** the persistence facade exposed a single large `LibraryDb` mixing five distinct concerns, making transactions and intent boundaries hard to reason about.

## Decision

Adopt a simplification program of six workstreams executed in four rounds, each round gated by a safety net that proves enforcement catches regressions:

- **Round 0 — WS0 (safety net):** build the characterization harness (`tests/characterization/` with `_normalize()` and snapshots) and the dead-code pipeline (`scripts/dead_code_pipeline.py`), plus a sabotage suite that intentionally breaks rules to verify the enforcement gates actually fail.
- **Round 1 — WS1 (dead scaffolding removal) and WS5 (dependency/CI cleanup)** run in parallel. The dependency toolchain is consolidated to deptry as the sole dependency checker; unused and overlapping tools are removed from `pyproject.toml`.
- **Round 2 — WS2 (persistence facade rebuild):** split `LibraryDb` into four intent sub-facades — `LibraryFilesDb`, `LibraryTagsDb`, `LibraryScansDb`, `LibraryRegionsDb` — behind a thin `LibraryDb` forwarder. Add unit-of-work `transaction()` discipline with `_require_transaction` guards, escalate the four `FacadeMisuseWarning` shims to hard errors, eliminate `cast(Any)`, and introduce TypedDict DTOs so the facade returns domain-shaped objects (per DD-persistence-intent-facade-rebuild, authoritative for this workstream).
- **Round 3 — WS3 (service mixin consolidation):** audit service mixins against AR-6 discipline and inline/delete only mixins that are empty, single-method, or sub-50-LOC passthroughs without cross-mixin dependencies; **WS4 (enforcement consolidation):** import-linter contracts, `test_architecture_qc.py`, ruff (ARG/TC rules), and deptry become the sole enforcement toolchain — grimp, vulture, radon, and check-arango-fields.sh are removed; **WS6 (ADR normalization):** supersede ArangoDB-era ADRs (ADR-004/010/016/024/025/030/031/036), resolve the ADR-033/034 duplicate, amend ADR-003/008/014/032 bodies to be storage-agnostic, and create this ADR. WS6 runs last and makes no code changes.

**Accepted outcome (2026-08-06):** WS3 was executed as a measured audit rather than inlining. All 12 remaining service mixins were audited and kept (12/12 KEEP) — zero inlined, zero deleted, zero source changes; the audit record is `MIXIN_AUDIT.md`. The only mixin deleted by the program is the already-empty `LibraryEntitiesMixin`, which was removed in Round 1 (Part B). `CurationMixin` (`TaggingCurationMixin`) and all other mixins remain in place as legitimate, cohesive ADR-021 splits — the pre-execution expectation that passthrough mixins would be inlined was superseded by the measured audit. All other rounds delivered as decided: the four-sub-facade `LibraryDb` with `transaction()`/`FacadeMisuseError` discipline, the consolidated enforcement toolchain (import-linter, `test_architecture_qc.py`, ruff ARG/TC, deptry), and the normalized ADR corpus.

## Consequences

**Positive:**

- **Reduced code:** dead scaffolding and adapter modules removed; the enforcement toolchain shrinks from overlapping tools to one cohesive set with explicit contracts.
- **Consolidated enforcement:** a single authority — import-linter contracts, `test_architecture_qc.py`, ruff, deptry — backed by the characterization and sabotage suites that prove each gate catches real regressions.
- **Normalized ADRs:** the corpus is consistent with the PostgreSQL architecture — ArangoDB-era decisions are retired or amended, and no Accepted ADR asserts the old stack as live.
- **4-sub-facade persistence architecture:** `LibraryDb` is replaced by four intent sub-facades with transaction discipline and domain-shaped DTOs, making persistence boundaries and transaction policy explicit and testable.

**Negative:**

- The sub-facade split is a breaking change for persistence consumers — callers across components, workflows, and services were updated in the same change set.
- Enforcement consolidation removed tools with partial coverage; the safety net must stay green to preserve confidence in the remaining gates.
- Retired ADRs are superseded rather than deleted, so the corpus grows with historical records (intentional — history is preserved).

**Neutral:**

- No runtime stack replacement — PostgreSQL remains the store; ArangoDB is not restored. The program is cleanup and consolidation, not re-architecture.

## References

artifacts/designs/pending/DD-nomarr-simplification-program.md, artifacts/designs/pending/DD-persistence-intent-facade-rebuild.md
