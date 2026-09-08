# ADR-047: Application Semantics and Persistence Representation Boundary

**Status:** Accepted  
**Date:** 2026-08-31  
**Tags:** architecture, persistence, domain-model, identity, intent-facade, embedding, song-move
**Source Log:** rnd-manager#L156  
**Supersedes:** ADR-032  

## Context

ADR-032 established an important boundary after ArangoDB storage vocabulary (`_id`, `_key`, revisions, collection names, and edge terminology) leaked through the application. Its anti-leakage objective remains correct: persistence must shield application code from storage representation, and mapping belongs in persistence. However, ADR-032 framed that boundary too absolutely. It treated natural keys as universally required, treated storage-generated identifiers as categorically forbidden, and risked implying that any value represented in persistence is disqualified from a domain contract. That framing can make the architecture optimize for persistence-language purity rather than useful separation of concerns.

Nomarr now uses the PostgreSQL persistence architecture established by ADR-040, domain-contract and mapper guidance in ADR-041, and the public intent-facade caller boundary in ADR-046. The architecture needs a precise distinction between application semantics and persistence representation. A database primary key answers which storage row is addressed; an application identity answers which Nomarr concept is being represented. They may coincide, but they are not the same architectural category. Persistence also owns more than row conversion: internal identity resolution, foreign-key handling, joins, storage deduplication, delete ordering, transaction boundaries, and other persistence choreography.

At the same time, some values that are persisted are genuine application concepts. For example, an embedding backbone can identify an ML model family used by application behavior; tier or lifecycle state may carry application policy; a tag namespace may express meaningful ownership or source. Excluding such values merely because they are stored would produce artificial contracts. The opposite failure is equally undesirable: renaming a row, freezing it in a dataclass, or wrapping it in a DTO does not make a storage projection a domain object.

The current embedding persistence migration is a concrete stress case. It must distinguish meaningful contracts such as `SongIdentity`, backbone, tier where semantically required, embedding streams, vector matches, and output identity/index where semantically required from PostgreSQL IDs, foreign keys, row layouts, index mechanics, and transaction choreography. Its approved record-preservation constraints remain authoritative and must not be altered by this boundary ADR.

ADR-046 is adjacent and remains in force: services, workflows, and service-classified workers may make thin calls to injected public persistence intent facades, while persistence internals and reconstructed choreography remain prohibited.

This ADR determines the canonical lifecycle identity of Song for move and rename semantics. A persisted Song's stable `song_id` is its application/entity identity for the lifetime of that Song, including filesystem moves and renames. `library`, `path`, and `normalized_path` are mutable locators. They identify where the current physical file is located, but do not determine whether it is the same Song. This scoped decision does not authorize raw storage IDs to leak through persistence boundaries generally; it intentionally adopts Song `song_id` as application identity for the Song lifecycle and requires persistence to retain storage translation and transaction ownership.

## Decision

Nomarr application-facing APIs use identities and values defined by application semantics. Persistence implementations own how those identities and values are represented, keyed, indexed, joined, translated, and transacted.

1. **Semantic identity is distinct from persistence identity.** A domain identity is part of an application-facing contract and is defined by the owning domain/application decision. A database primary key, generated row ID, foreign key, surrogate key, or storage identifier is persistence-internal by default. Persistence owns all translation between application identity and persistence identity. Domain and database identity may coincide as an implementation choice, but architecture must not require that they coincide or forbid the coincidence.

2. **Generated IDs require intentional adoption.** A generated identifier may become application/domain identity only through an explicit domain decision that names its semantic referent, scope, stability guarantee, lifecycle, and application or external contract. For Songs, this ADR intentionally adopts the stable `song_id` as the entity identity for the lifetime of a persisted Song, including filesystem moves and renames. The identity remains stable while the Song row is updated in place and ends when the Song is deleted. A later delete/recreate is a new Song identity, even if a locator is reused. No unrelated generated IDs become application identities by implication.

3. **Persistence owns representation and mechanics.** Persistence owns rows, tables, columns, storage layouts, internal IDs, foreign keys, joins, indexes, serialized payloads, row/document mapping, identity resolution, storage-specific deduplication, delete ordering, session/transaction boundaries, and persistence choreography. This ownership includes implementing an intent-complete atomic operation when a persistence intent spans multiple tables or representations. Callers must not construct row payloads, resolve foreign keys, enumerate storage partitions, reproduce delete/insert sequences, manage transactions, or otherwise reconstruct persistence mechanics.

4. **Meaningful persisted concepts may cross the facade.** A value may appear in an application/domain contract when at least one application use case, invariant, state machine, capability, or user-visible behavior depends on its meaning independently of the current storage schema. Examples may include an embedding backbone, a semantically meaningful tier or lifecycle state, a tag namespace, a model output position, or the existing application `SongIdentity` used to identify the song intent in the embedding migration. Persistence may encode, rename, split, combine, or index such values without changing the application contract. A value used only for row identification, joining, indexing, partitioning, storage maintenance, or transaction ordering remains persistence-internal. Storage-only details such as table/column names, FK mechanics, index names, row revisions, ORM models, sessions, and transaction handles do not become domain concepts merely by being exposed.

5. **No raw-shape leakage or DTO laundering.** Persistence-row DTOs, raw dictionaries, repository records, table projections, and storage mappings remain persistence-internal. Renaming, freezing, annotating, or wrapping a storage row does not make it a domain object. A contract is storage-shaped when its field set, nullability, cardinality, lifecycle, nesting, or naming is determined primarily by a table/query result rather than an application capability or invariant. Domain/application contracts must not be created solely to avoid mapping work. Domain classes must not gain `from_row`, `from_db_doc`, row-shaped `to_dict`, or equivalent persistence constructors/projections. This does not prohibit intentional transport/API serialization of an application contract; it prohibits persistence-row projections crossing the persistence boundary.

6. **Use the smallest semantically sufficient contract.** A scalar, enum, tuple/value object, count, status, command, or dataclass may be used according to the meaning and structure required by the application. Do not introduce wrappers, repositories, aggregate roots, or domain objects solely to disguise persistence vocabulary or comply mechanically with a no-storage-types rule. Conversely, simplicity does not permit a raw storage mapping to cross the facade. A domain type is justified by semantic identity, a meaningful invariant, cohesive behavior/capability, or a stable application contract that differs from the storage shape.

7. **Preserve the public intent-facade boundary.** ADR-046 remains in force without expansion or narrowing of its caller-scope decision. Components, services, workflows, and service-classified workers may call injected public `Database` intent facades for thin calls representing one atomic persistence intent or thin recipe step. Interfaces and helpers remain persistence-free. No caller may import or receive Tier-1 SQL primitives, Tier-2 repositories, ORM/database models, persistence mappers, sessions, transactions, collection/table internals, storage identifiers, raw storage shapes, or persistence-owned fields. Application orchestration remains legitimate when it sequences application intents; it must not reconstruct persistence choreography.

8. **Song identity and move/rename lifecycle.** A persisted Song's stable `song_id` is the application/entity identity for the lifetime of that Song. `library`, `path`, and `normalized_path` are mutable locators and may change when the physical file is moved or renamed. A move/rename MUST update the existing Song row in place rather than delete and recreate it merely because its locator changed. The persistence intent for a move owns one atomic transaction covering the path, normalized path, and related scan metadata; it either updates all required fields or none. Locator uniqueness constraints remain authoritative: a destination conflict fails without changing the source locator or scan metadata. Existing references keyed to the Song, including tags, state assignments, embeddings, claims, playlists, and other associations, remain attached because the Song identity is unchanged. A delete followed by a later create is a new Song identity and is not a move/rename.

9. **Embedding persistence execution boundary.** For the approved embedding-persistence migration, `Database.ml` / `MlDb` remains the sole public persistence boundary; no second facade, compatibility facade, aggregate root, or broad unrelated `MlDb` refactor is introduced. The application contracts include `SongIdentity`, vector values and typed vector-write commands, `backbone`, `VectorMatch`, `EmbeddingCounts`, and stable output identity/index where semantically required. Table names, row IDs, foreign keys, raw rows, storage tiers or predicates when not semantically required, SQL, sessions, storage timestamps/metadata, transaction handles, and persistence-generated IDs remain internal. `MlDb` accepts and returns application concepts and persistence resolves `SongIdentity` internally.

10. **Intent-complete persistence choreography.** Persistence owns row-to-domain mapping, collection/table enumeration, batch deletion, tier predicates, `embed_dim` derivation from the supplied vector, stable output-ID mapping, output-stream deduplication, and SQL/transaction choreography. In particular, multi-table inference replacement remains an intent-complete, persistence-owned operation; callers do not reconstruct its vector/stream delete/insert sequence or transaction boundary. This execution scope includes every caller required for one coherent embeddings contract, including taste profile, playlist building, vector service/API, retrieval/persistence components, maintenance, and inference writes, while retaining ADR-046's thin-call constraints.

11. **Record preservation and bounded caller-visible repair.** Existing persisted oddities are preservation constraints, not semantic endorsements or migration targets. The embedding migration preserves the established `model_id <- semantic suite hash` mapping, `model_suite_hash == ""`, `segmentation_hash IS NULL`, hot insertion, vector ordering, genres/nullability, existing stream IDs/values/order/bytes, and millisecond timestamp behavior, with no schema/data migration or stored-value correction. The approved search repair—`score = clamp(1 - cosine_distance, -1, 1)` while preserving cosine semantics, existing limit/filter behavior, and `{file_id, score, vector}` transport shape—is a caller-visible/API contract repair and not a record migration.

12. **Trimmed execution scope is authoritative.** The embedding migration's approved exclusions remain unchanged: calibration implementation; standalone embedding-stream modernization, restore, schema, or value work; model pruning and broad model-registry cleanup; `VectorIndexStatus`; dependency changes; broad import-linter restructuring; and unrelated `MlDb` methods. The pending DD, its contracts/README, and Plans A–E are implementation artifacts that explain and sequence this bounded execution; they do not expand this ADR or replace its normative decisions. Legacy methods are retired only after complete production, test, worker, export, and dynamic-dispatch evidence.

## Consequences

**Positive**

- Preserves ADR-032's useful anti-leakage boundary while replacing an absolute storage-avoidance rule with a semantic test.
- Makes ownership of domain-to-persistence translation explicit, including the case where a domain identity differs from a PostgreSQL primary key.
- Allows honest application contracts for persisted concepts such as `SongIdentity`, backbone, meaningful tier/state, namespace, or output position without exposing storage mechanics.
- Prevents raw rows from leaking and prevents DTO laundering, artificial wrappers, and persistence-language cargo cult from being mistaken for domain modeling.
- Keeps persistence-specific identity resolution, multi-table choreography, and transaction ownership behind intent-complete facade operations.
- Gives the embedding persistence migration a precise contract test without authorizing unrelated schema or data changes.
- Makes the approved embedding migration executable while explicitly separating its scoped `SongIdentity` use from the Song move/rename lifecycle contract.
- Makes the preserved odd mappings and the search-score repair explicit, separating record preservation from caller-visible contract repair.

**Negative and risks**

- Determining whether a persisted value is semantically meaningful requires judgment and cannot be fully enforced by import rules or type checks. Code review must ask whether an application use case, invariant, state machine, capability, or user-visible behavior depends on the value independently of the current schema.
- Existing transitional dataclasses and ML DTOs may still be storage-shaped despite domain-oriented names; audits and targeted migrations remain necessary.
- Avoiding accidental generated-ID adoption for concepts other than Song requires explicit identity decisions and review of new contracts.
- Richer intent-complete facade methods may be needed instead of convenient row queries, increasing persistence implementation responsibility.
- Persistence and application orchestration can be confused. Review must distinguish application-level sequencing from storage choreography.
- Existing `SongIdentity(library, normalized_path)` usages may need clarification or revision where they describe a mutable locator rather than stable Song identity.
- The embedding migration has wide required caller churn; excluding required callers would leave the boundary incoherent, while including unrelated `MlDb` concerns would violate the trimmed scope.

**Mitigations**

- Keep persistence mappers and repository records private to persistence; use architecture checks as guardrails, not proof of semantic shape.
- Require explicit documentation for adopted generated identities, including scope, stability, lifecycle, and external contract.
- Review facade calls for thinness and atomic intent under ADR-046 and retain Tier-1/Tier-2 import bans.
- Prefer the smallest contract that expresses application meaning and reject row mirrors and cargo-cult wrappers.
- Keep this Song lifecycle decision synchronized with affected domain contracts and tests; unresolved identity questions for other concepts still require separate decisions.
- Govern the embedding execution with the approved DD, CONTRACTS.md, Plans A–E, inventory/retirement evidence, and preservation/transaction tests; do not use those artifacts to authorize excluded work.

## Alternatives Considered

**Retain ADR-032 unchanged — Rejected.** Its anti-leakage goal remains valuable, but a universal natural-key and no-persisted-concept interpretation confuses application semantics with storage representation and encourages artificial abstractions.

**Permit all persisted values and facade results — Rejected.** Persistence representation would leak through renamed rows, raw mappings, generated IDs, and storage choreography; the boundary would become nominal rather than useful.

**Require every application contract to be a new domain wrapper — Rejected.** A wrapper that merely sanitizes a database row is DTO laundering. The contract should be the smallest meaningful application shape, which may be a scalar or existing value object.

**Require domain identity always to be different from the database PK — Rejected.** Coincident identities can be a sound implementation choice. The architecture requires intentional semantic ownership, not artificial difference.

**Move all multi-table sequences to callers — Rejected.** This reconstructs persistence choreography and weakens atomicity. Persistence must own intent-complete operations and transaction boundaries, while callers retain genuine application orchestration.

## References

- ADR-032 — Domain-Model Boundary: Persistence Returns Only Domain Objects, Never Storage Shapes
- ADR-038 — Canonical int8 temporal embedding streams for post-hoc segmentation
- ADR-040 — PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB
- ADR-041 — Domain Dataclasses as the Persistence-Component Contract
- ADR-042 — Simplification Program — Dead Code Removal, Enforcement Consolidation, and ADR Normalization
- ADR-046 — Allow Thin Persistence Intent-Facade Calls from Services and Workflows
- ASR-0013 — Intent-complete persistence facades
- ASR-0014 — Public Database sub-facades as the persistence boundary
- artifacts/designs/pending/DD-embedding-persistence-intent-facade-migration.md — governing implementation design
- artifacts/designs/parts/embedding-persistence-intent-facade/CONTRACTS.md — approved execution contracts
- artifacts/designs/parts/embedding-persistence-intent-facade/README.md — plan sequencing overview
- artifacts/plans/pending/TASK-embedding-persistence-intent-facade-A-inventory-contracts.md
- artifacts/plans/pending/TASK-embedding-persistence-intent-facade-B-domain-persistence.md
- artifacts/plans/pending/TASK-embedding-persistence-intent-facade-C-read-search-callers.md
- artifacts/plans/pending/TASK-embedding-persistence-intent-facade-D-write-maintenance-callers.md
- artifacts/plans/pending/TASK-embedding-persistence-intent-facade-E-retirement-preservation.md
- artifacts/designs/process/ADVERSARIAL-embedding-persistence-intent-facade-migration.md
- artifacts/designs/process/ARCHITECTURE-embedding-persistence-intent-facade-migration.md
- artifacts/designs/process/COMPLEXITY-embedding-persistence-intent-facade-migration.md
- artifacts/designs/process/ESTIMATE-embedding-persistence-intent-facade-migration.md
- nomarr/persistence/PERSISTENCE.md
- .opencode/skills/persistence-domain-model/SKILL.md
- .opencode/skills/ml-output-identity/SKILL.md
- .opencode/skills/ml-inference-path/SKILL.md

## Amendment Note

Amended after explicit user approval on 2026-09-08. This amendment resolves the former non-decision in the Context and Decision §8: stable `song_id` is Song entity identity; `library`, `path`, and `normalized_path` are mutable locators; moves and renames update the existing row in place through one atomic persistence intent. The remainder of this ADR is preserved in substance.
