# ADR-046: Allow Thin Persistence Intent-Facade Calls from Services and Workflows

**Status:** Accepted  
**Date:** 2026-08-30  
**Tags:** architecture, persistence, intent-facade, layer-boundaries, domain-model  
**Source Log:** nyx#L19  

## Context

Nomarr uses a three-tier PostgreSQL persistence architecture: public intent facades over repositories and SQL primitives. The intent facade is the sanctioned boundary that hides storage mechanics, transaction handling, persistence identifiers, collection choreography, and database mappings. ADR-032 and ADR-041 establish the domain-object boundary and domain-dataclass contract; ADR-040 establishes the current PostgreSQL-backed facade architecture.

The repository contains contradictory caller-scope rules. Current architecture artifacts and active contracts treat components, workflows, and services as facade callers: ADR-042 records callers across all three layers, ASR-0014 explicitly names components, workflows, and services, and persistence design contracts pass injected Database instances into workflows. Conversely, the pyproject.toml import-linter contracts around lines 326-336 restrict runtime persistence imports by workflows and describe service access as type-hints-only. Layer guidance is also inconsistent about whether services may call the facade directly. This makes the intended boundary difficult to enforce and causes a components-only interpretation to conflict with existing callers and accepted architecture.

The question is not whether higher layers may access persistence internals: those internals must remain prohibited. The question is whether higher layers may call the public, injected intent facade. “Above component” means services and workflows, including workers classified as services. Interfaces and helpers have separate responsibilities and remain excluded.

## Decision

Adopt a yes-with-constraints rule. Components, services, and workflows—including service-classified workers—may call the public persistence intent facade through an injected Database instance and its public db.library, db.app, and db.ml sub-facades. Public nested sub-facades rooted in those namespaces are allowed where exposed by the facade. Interfaces and helpers may not call persistence.

A higher-layer facade call must be thin and represent one atomic persistence intent or one thin recipe step. Services and workflows must not reconstruct persistence intents by sequencing lower-level calls, implement business rules or state-machine transitions, manage collection-level writes, or perform multi-call persistence choreography. Such behavior belongs in a component or an intent-complete facade method. Side-effectful reads, such as hydration, are treated as commands for review purposes rather than being classified solely by method names.

The facade remains the sole public persistence boundary. This decision expands the set of permitted facade callers; it does not permit access to Tier-1 SQL primitives, Tier-2 repositories, collection/accessor internals, ORM/database models, mappers, direct sessions or transactions, persistence implementation classes, storage identifiers, raw storage shapes, collection names, or persistence-owned fields outside persistence.

## Consequences

Benefits:
- Aligns the normative architecture with existing service and workflow callers, ADR-042, ASR-0014, and active facade contracts.
- Avoids meaningless pass-through components for thin operations.
- Preserves one public persistence boundary and keeps storage mechanics, transaction choreography, and mappings inside persistence.
- Gives service workers the same explicit rule as other service callers.
- Retains domain-object, natural-key, Tier-1/Tier-2, and dependency-direction guarantees.

Risks and issues:
- Services and workflows may accumulate business logic or become transaction scripts.
- Higher-layer code may create non-atomic read-modify-write sequences or bypass components that own state transitions.
- The facade may grow into an incohesive god object.
- Import-linter can enforce module boundaries but cannot determine whether a call is semantically thin; static inventories can miss aliases, dynamic dispatch, distributed choreography, and hidden side effects.
- Apparently read-oriented operations may mutate state, increasing review and classification cost.
- Optional inventories or registries can drift and create false confidence.

Mitigations:
- Enforce the thin, single-atomic-intent rule through code review and architecture guidance.
- Keep ASR-0013’s intent-completeness requirement in force; move multi-intent operations into intent-complete facade methods.
- Treat hydration and other side-effectful reads as commands during review.
- Preserve separate Tier-1/Tier-2 and collection/accessor import bans.
- If an AST inventory is introduced, use it as a review tripwire rather than semantic proof, seed it from a fresh live scan, and record its measurement criterion and date.
- Keep facade growth and ownership under periodic architectural review rather than introducing an arbitrary threshold before live evidence exists.

## Alternatives Considered

**Components-only gateway — Rejected.** Conflicts with ADR-042, ASR-0014, current production callers, and persistence documentation; introduces pass-through components without demonstrated benefit.

**Read-open/write-gated access — Rejected as the primary rule.** Method names do not reliably reveal side effects, and hydration demonstrates that a read-oriented operation may mutate state. Query/command classification remains a review discipline.

**New data-access seam — Rejected.** The intent facade already provides the required translation and boundary; a second seam risks pass-through ceremony or another component-like layer.

**Unrestricted access from every layer — Rejected.** Interfaces and helpers have distinct adapter and purity responsibilities and remain persistence-free.

## Enforcement and Migration

This is a policy and documentation reconciliation, not a runtime compatibility migration. Follow-up changes must:
1. Re-scope the import-linter caller contract to permit components, services, and workflows.
2. Remove the obsolete workflow TYPE_CHECKING-only exception.
3. Remove the service type-hints-only restriction for public facade calls.
4. Preserve separate Tier-1/Tier-2 and collection/accessor internal bans.
5. Replace contradictory “never call persistence directly” guidance with the thin-call rule.
6. Retain and clarify injected workflow Database examples in persistence documentation.
7. Optionally add an architecture-QC inventory/classification tripwire.

No caller-by-caller migration, compatibility alias, deprecation window, or business-logic relocation is required merely to adopt this policy; existing service/workflow facade usage is being codified.

## Supersession and Preservation

Upon acceptance, this ADR supersedes or amends only contradictory caller-scope rules: the pyproject.toml import-linter contract named “Only components and services may import persistence,” the service “Database for type hints only” restriction, and stale service/workflow guidance that forbids direct calls to the public facade. It also supersedes any remaining interpretation inherited from ADR-031 that excludes services or workflows.

ADR-031 itself is already Superseded by ADR-040 and is not newly superseded by this ADR. ADR-032, ADR-040, ADR-041, ADR-042, ADR-043, ASR-0013, and ASR-0014 remain in force. This ADR does not weaken the domain-object contract, intent-completeness requirement, public-sub-facade-only boundary, or Tier-1/Tier-2 internal bans.

## References

- ADR-031 — AQL Primitives and Intent Sub-Facades as Canonical Persistence Architecture (already superseded by ADR-040; historical lineage only)
- ADR-032 — Domain-Model Boundary: Persistence Returns Only Domain Objects, Never Storage Shapes
- ADR-040 — PostgreSQL + pgvector Migration: Hard-Cut Replacement of ArangoDB
- ADR-041 — Domain Dataclasses as the Persistence-Component Contract
- ADR-042 — Simplification Program: Dead Code and Enforcement Consolidation
- ADR-043 — Use Songs as the Sole Library Entity and Source of Truth
- ASR-0013 — Intent-complete persistence facades
- ASR-0014 — Public Database sub-facades as the persistence boundary
- artifacts/designs/completed/DD-persistence-intent-facade-rebuild.md
- artifacts/designs/parts/persistence-tier3-intent-api-refactor/CONTRACTS.md
- artifacts/designs/parts/library-domain-facades/CONTRACTS.md
- pyproject.toml (import-linter caller contracts around lines 326-336)
- tests/test_architecture_qc.py
- nomarr/persistence/PERSISTENCE.md
- docs/dev/architecture.md
- .opencode/skills/nomarr-layers/SKILL.md
- artifacts/designs/pending/DD-persistence-facade-caller-layer.md
- artifacts/designs/process/ADVERSARIAL-persistence-facade-caller-layer.md
