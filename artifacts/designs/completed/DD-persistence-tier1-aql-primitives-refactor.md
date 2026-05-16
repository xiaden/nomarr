# Persistence Tier 1 AQL Primitives Refactor — Design Document

**Status:** Completed  
**Author:** GitHub Copilot  
**Created:** 2026-05-15  

**Related Documents:**

- [ADR-031: AQL Primitives and Intent Sub-Facades as Canonical Persistence Architecture](../../decisions/ADR-031-aql-primitives-and-intent-sub-facades-as-canonical-persistence-architecture.md) — Governing three-tier persistence architecture
- [DD: Persistence Tier 2 Domain Capability Bindings Refactor](../completed/DD-persistence-tier2-domain-capability-bindings-refactor.md) — Immediate upstream consumer of Tier 1 primitives (completed)
- [DD: Persistence Tier 3 Intent API Refactor](../completed/DD-persistence-tier3-intent-api-refactor.md) — Downstream public surface that depends on disciplined lower layers (completed)
- [ASR-0014](../../requirements/ASR-0014.md) — Layer boundaries are crossed only through defined contracts

---

## Scope

`nomarr/persistence/aql/primitives.py`, the `SafeDatabase` execution boundary in `nomarr/persistence/arango_client.py`, and tests/docs that define or validate the Tier 1 primitive contract.

This DD covers the **Tier 1 primitive API surface only**. It does not redesign schema, Tier 2 module ownership, or Tier 3 caller contracts.

---

## Problem Statement

`ADR-031` establishes Tier 1 as pure reusable AQL primitives, but the current codebase still treats the primitive layer as a convenience module rather than a tightly governed internal API.

That leaves several risks:

1. **Primitive growth can become abstraction creep.** A helper that looks reusable in one refactor can quietly become a mini query framework if the extension rules are not explicit.
2. **The stop line between Tier 1 and Tier 2 is too fuzzy.** Without written rules, contributors can either over-generalize domain logic into primitives or underuse primitives and duplicate low-level shapes in many `*_aql.py` modules.
3. **Safety is a contract, not just an implementation detail.** Field-name validation, bind-var discipline, and JSON-safe execution through `SafeDatabase` are central to the architecture. They should be treated as Tier 1 design rules, not incidental helper behavior.
4. **Primitive naming and return-shape discipline matter.** If primitives start returning domain-specific projections or accepting business-language parameters, Tier 1 stops being reusable and becomes a hidden second Tier 2.

The missing DD means Tier 1 is directionally correct but not yet protected against future overreach.

---

## Non-Goals

This refactor does **not**:

- make Tier 1 importable by callers above persistence
- create a generic query DSL or spec compiler at Tier 1
- require every piece of AQL to be expressed as a primitive
- remove handwritten AQL from Tier 2 when the query is genuinely domain-specific
- expand `SafeDatabase` into a full ORM or mapper
- change the meaning of `_id`, `_key`, collection names, or ArangoDB graph semantics

---

## Architecture

## Core Decision

Tier 1 is the **smallest reusable AQL shape layer**.

A Tier 1 primitive exists only when all of the following are true:

1. the query shape is reusable across multiple persistence domains
2. the primitive can stay collection-agnostic or near-agnostic
3. the inputs can be described in storage-generic terms, not business terms
4. the return shape is plain Python data, not domain semantics
5. the primitive improves clarity more than an inline AQL statement would

Tier 1 is therefore intentionally narrow. It is not a framework, not a declarative language, and not a second public API.

### Tier 1 contract rules

1. **Tier 1 exports pure functions only.**
2. **Tier 1 functions accept a `SafeDatabase` plus primitive storage parameters.**
3. **Tier 1 functions return plain Python values or plain document dictionaries.**
4. **Tier 1 never knows Nomarr business concepts like library intent, scan lifecycle, tag curation, or calibration publication.**
5. **Tier 1 validates every dynamic AQL identifier it interpolates.**
6. **Tier 1 passes all values through bind vars, never string interpolation.**
7. **Tier 1 should be boring.** If a primitive is clever, it is probably too high-level.

### What belongs in Tier 1

Good Tier 1 candidates:

- fetch documents by `_key`
- fetch documents by one validated field
- fetch filtered documents with validated equality filters
- list one field from filtered documents
- delete many documents by key
- insert one document
- update one document by key
- upsert by one validated field
- normalize optional limits
- execute AQL and materialize cursor results

Bad Tier 1 candidates:

- `get_library_by_name`
- `replace_file_vectors`
- `transition_file_states`
- `list_tracks_for_matching`
- `remove_library`
- `replace_tag_references`
- anything that knows which collections constitute one Nomarr concept

### The stop-line rule

When deciding whether logic belongs in Tier 1 or Tier 2, ask:

- Does this helper still make sense if all Nomarr collection names were renamed?
- Could two unrelated persistence domains reuse this exact shape?
- Are the parameters generic storage terms like `collection`, `field_name`, `filters`, `keys`, `payload`?

If the answer is no, it is not Tier 1.

---

## Primitive Taxonomy

Every Tier 1 primitive should fit one of these families:

| Family | Purpose | Examples |
| --- | --- | --- |
| **Execution** | Run safe AQL and materialize results | `execute` |
| **Validation** | Guard dynamic query construction | `_validate_field_name`, `_require_allowed_field` |
| **Normalization** | Normalize generic query inputs | `normalize_limit` |
| **Read by identity** | Fetch by `_key` or one validated field | `get_many_by_keys`, `get_many_by_field` |
| **Filtered reads** | Fetch or project from equality-filtered documents | `get_filtered_docs` |
| **Generic counts** | Count generic graph/document shapes | `count_distinct_edge_sources_to_filtered_vertices` |
| **Generic writes** | Insert/update/upsert/delete one reusable document shape | `insert_document`, `update_document_by_key`, `upsert_by_field`, `delete_many_by_field`, `delete_many_by_keys` |

This taxonomy is intentionally small. If a candidate primitive needs a new family, that is a sign it may belong in Tier 2 instead.

---

## Safety Contract

Tier 1 owns the persistence layer’s reusable AQL safety rules.

### Field-name validation

Any primitive that interpolates a field name into AQL text must validate it first.

Rules:

- reject empty names
- reject names starting with `_` when not explicitly intended
- reject names starting with `.`
- reject spaces and non-identifier punctuation
- allow dotted nested paths only when explicitly safe for attribute access
- require membership in an allowed-field set when the primitive supports only a constrained schema

### Bind-variable discipline

Tier 1 never inlines user data or payload values directly into AQL strings.

Rules:

- data values always go through bind vars
- collection names use Arango bind syntax where possible
- the only allowed string interpolation is validated structural text such as field names in known-safe positions

### JSON-serialization boundary

Tier 1 depends on `SafeDatabase` for bind-var sanitization.

That means:

- wrappers with primitive `.value` may be unwrapped
- non-serializable objects are rejected before reaching Arango
- Tier 1 may assume its bind vars are normalized through `SafeDatabase`, but it must still pass clean, predictable structures

Tier 1 should not compensate for arbitrary caller objects. If a payload is not JSON-safe, fix the caller or Tier 2 binding that assembled it.

---

## Return-Shape Contract

Tier 1 returns only plain data shapes:

- `list[dict[str, Any]]`
- `dict[str, Any]`
- `list[str]`
- `int`
- `None`
- other simple Python primitives when justified

Tier 1 does not:

- instantiate DTOs
- map results into domain models
- rename `_id` or `_key`
- merge documents into app-facing semantic views
- hide storage-shaped results behind richer abstractions

If a result needs interpretation, that belongs in Tier 2 or Tier 3.

---

## Extension Rules

### When to add a new primitive

Add a new primitive only when:

- at least two Tier 2 modules need the same query shape, or one module clearly will not be the only consumer for long
- the primitive remains generic after naming and parameter review
- the function can be explained without referencing Nomarr domain jargon
- the helper reduces duplication without making the call site harder to understand

### When not to add a new primitive

Do **not** add a primitive when:

- the query is only used in one domain and includes domain-specific joins/traversals
- the helper would require callback-style configuration or mini-language inputs
- the primitive name starts to describe business intent rather than storage shape
- a short inline AQL block in Tier 2 would be clearer

### Duplication is sometimes preferable

A little duplication in Tier 2 is cheaper than a bad primitive in Tier 1.

The primitive layer should grow slowly and reluctantly. If there is doubt, keep the AQL in Tier 2 first. A later refactor can extract a real primitive once reuse is proven.

---

## Current Primitive Inventory Guidance

The existing primitive inventory is already close to the right size:

**Keep as Tier 1 primitives:**

- `execute`
- `normalize_limit`
- `get_many_by_keys`
- `get_many_by_field`
- `get_filtered_docs`
- `count_distinct_edge_sources_to_filtered_vertices`
- `delete_many_by_keys`
- `delete_many_by_field`
- `upsert_by_field`
- `insert_document`
- `update_document_by_key`

**Internalized during Tier 2 refactor (no longer public Tier 1 symbols):**

- `list_field_values` — removed after Part C; had 0 remaining callers
- `upsert_many_by_field` — internalized after Part C; single caller was moved into `library_files_aql.py`

**Keep as private support helpers inside `primitives.py`:**

- `_validate_field_name`
- `_require_allowed_field`
- `_normalize_bind_key`
- `_build_filter_lines`

**Do not promote from Tier 2 without strong evidence:**

- graph traversal helpers tied to one edge meaning
- vector search helpers
- file-state transition helpers
- output-stream edge maintenance helpers
- model-output and calibration graph helpers

---

## Relationship to Tier 2

Tier 2 is the only intended consumer of Tier 1.

Expected usage pattern:

- Tier 2 uses primitives for generic read/write/filter/count shapes
- Tier 2 writes custom AQL for domain-specific joins, traversals, or multi-collection mutation
- Tier 2 decides when inline custom AQL is clearer than extracting a new primitive

Tier 1 should make Tier 2 simpler, not weaker. It exists to remove repeated low-level scaffolding, not to eliminate Tier 2 judgment.

---

## Testing Contract

Tier 1 should be tested as a pure query-shape and safety layer.

Test focus:

- valid and invalid field-name validation
- limit normalization behavior
- expected bind-var assembly
- query text shape for reusable primitives
- correct materialization of cursor results
- safe handling of empty inputs
- correct interaction with `SafeDatabase`-style mocked handles

Tier 1 tests should not prove business semantics like “scan lifecycle works” or “tag merge removes source tags.” Those belong above Tier 1.

---

## Migration Strategy

### Phase 1 — Freeze the contract

Treat the current primitive inventory as the baseline contract. New additions require explicit review against this DD.

### Phase 2 — Push back overreach

As Tier 2/Tier 3 refactors continue, reject attempts to add domain-aware helper functions into `primitives.py` unless they clearly satisfy the Tier 1 criteria.

### Phase 3 — Extract only proven shapes

If several Tier 2 modules duplicate the same low-level query scaffolding, extract a primitive only after verifying that the abstraction remains generic and improves readability.

### Phase 4 — Keep safety central

Any new primitive that interpolates structural AQL text must include validation logic and tests before adoption.

---

## Validation

This refactor is correct when all of the following are true:

1. `nomarr/persistence/aql/primitives.py` remains small, generic, and comprehensible
2. Tier 1 helpers can be explained without Nomarr business-domain language
3. dynamic AQL interpolation is always validated and all data values use bind vars
4. Tier 2 reuses Tier 1 where appropriate, but still writes custom AQL for genuinely domain-specific shapes
5. no higher layer outside persistence depends on Tier 1 directly
6. tests cover both happy-path query assembly and rejection of unsafe inputs

Recommended validation passes:

- targeted unit tests under `tests/unit/persistence/aql/`
- review of any new primitive additions during Tier 2 work
- grep/import review to confirm Tier 1 is not used directly outside persistence/tests

---

## Risks

- **Framework relapse.** If Tier 1 starts growing config-heavy helpers, the codebase recreates a new generic query framework by accident.
- **False reuse.** A primitive extracted too early can be harder to understand than two straightforward Tier 2 AQL blocks.
- **Safety drift.** A helper that interpolates unvalidated field names or bypasses bind vars would undermine the core security/correctness contract.
- **Leaky semantics.** Domain-aware primitive names would blur the line between Tier 1 and Tier 2 and make future refactors harder.

---

## Open Questions

1. ~~Should Tier 1 remain a single `primitives.py` module, or is there enough stable separation to justify submodules?~~ **Resolved:** Single `primitives.py` is the current live state and the right shape for the current inventory size. At 11 public primitives the overhead of a submodule split is not justified.
2. ~~Are there any current repeated Tier 2 query shapes that are genuinely generic enough to become primitives?~~ **Resolved by Part C of the Tier 2 refactor:** `delete_many_by_field` was the one proven-generic extraction (7 Tier 2 callers). The inventory is now at the right ceiling with no remaining obvious candidates.
3. ~~Should the Tier 1 safety contract (`_validate_field_name`, bind-var discipline, `SafeDatabase` boundary) be explicitly documented in `nomarr/persistence/PERSISTENCE.md`?~~ **Resolved — safety rules documented in `nomarr/persistence/PERSISTENCE.md` Section 6 as part of Plan A.**

---

## Completion Criteria

This refactor is complete when:

- Tier 1 has an explicit narrow contract
- contributors can tell quickly whether a helper belongs in Tier 1 or Tier 2
- AQL safety rules are treated as architectural requirements, not incidental implementation details
- `primitives.py` remains a reusable toolbox instead of becoming a mini persistence framework
- the live code and this DD agree on what Tier 1 is for
