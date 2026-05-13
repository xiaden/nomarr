# Collection-First Query-Spec Persistence Architecture — Design Document

**Status:** Draft  
**Author:** GitHub Copilot (RnD-DDAuthor)  
**Date:** 2026-05-09  
**Recommended slug:** `collection-first-query-spec-persistence`

---

## Overview

Nomarr’s persistence boundary should keep the public constraints already accepted in ADR-025 and ADR-030: higher layers talk only to `Database`, persistence remains schema/declarative and single-step, `EDGES` stays authoritative for relationship semantics, vector runtime registration stays narrow, and results remain storage-shaped. What needs revision is the design center. The current framing treats “verbs” as the overloaded master concept and implicitly preserves field-first access patterns as co-equal with collection surfaces.

This revision shifts the design center to **collection-first public surfaces built from validated query specs and normalized capability families**. Fields remain important, but primarily as criteria metadata inside query specs rather than as first-class API namespaces. Field accessors are no longer the conceptual backbone of the design; they are compatibility machinery that may be retained temporarily while the collection-first surface becomes normative. The persistence layer keeps only truly storage-native special capabilities special — most notably ANN search, graph traversal/cascade derived from `EDGES`, and state-graph transitions — while ordinary document operations and orchestration stop hiding behind bespoke vector- or transition-branded helper names.

The design also makes **AQL validation a first-class requirement**. Today the live query helper layer validates interpolated field names and logs AQL, but there is no broader validation model for query templates, spec compilation, or parse/plan checking. That gap is architectural, not incidental.

---

## Problem Statement

The current persistence architecture has the right boundary but the wrong center of gravity.

1. **“Verb” is carrying too much architectural weight.** It is currently doing the jobs of naming model, capability taxonomy, binding mechanism, and sometimes query shape. That makes the design harder to normalize and review.
2. **Field-first API surfaces look increasingly like legacy carry-forward complexity.** Instance-bound field accessors were defensible when field-level security or per-field binding semantics were central; that justification is much weaker now. Keeping fields as first-class public namespaces risks preserving complexity whose original reason no longer exists.
3. **Naming inconsistency is signaling unresolved architecture.** The current surface mixes collection methods, field methods, graph helpers, and vector-branded helpers without a single normalized capability vocabulary.
4. **“Vector-specialized” often means “ordinary persistence plus orchestration wearing a vector hat.”** Most vector helpers are not storage-native vector primitives. They are generic document writes, edge maintenance, or multi-step workflows that belong either in generic collection capabilities or above persistence.
5. **There is no first-class AQL validation model.** The live helper layer in `nomarr/persistence/constructor/verbs.py` executes generated AQL and validates field-name interpolation, but the design does not yet require spec-level validation, query-template linting, or parse/plan checking.

The architectural goal is therefore not “better verbs.” It is a cleaner persistence model in which:

- `Database` remains the only public entry point,
- collection namespaces are primary,
- query specs express criteria and operators,
- capability families are normalized and limited,
- truly storage-native primitives stay explicit,
- and higher-layer compositions stop accumulating in persistence.

---

## Requirements

1. Preserve `Database` as the only public persistence entry point per ADR-030.
2. Preserve ADR-025 constraints: schema/declarative source of truth, no hand-written per-collection AQL modules, and no multi-step orchestration inside persistence.
3. Preserve ADR-030 constraints that remain accepted today: `EDGES` authority, narrow vector runtime registration via `Database.register()`, and storage-shaped persistence results.
4. Recenter the design on **collection-first** public persistence surfaces rather than field-first accessors.
5. Treat fields primarily as query criteria and metadata, not as the primary public namespace, unless a compelling residual reason is documented.
6. Introduce a **normalized naming/capability taxonomy** that distinguishes generic document primitives, storage-native primitives, and higher-layer compositions.
7. Keep only truly storage-native capabilities special. ANN search is the clearest persistent example; graph traversal/cascade and state transitions remain special where they map directly to native graph/state persistence semantics.
8. Reclassify persistence helpers that are actually generic document operations or cross-call orchestration rather than keeping them under domain- or storage-themed special names.
9. Make **AQL validation and linting** a first-class architectural requirement, including static-ish validation of query specs/templates and parse/plan validation where feasible.
10. Explicitly address migration of field accessors: remove, deprecate, or retain only as compatibility shims, with rationale.
11. Produce a design useful for future planning by clearly separating what belongs in persistence from what belongs in components/workflows.

---

## Non-Goals

This design does **not**:

- change the public persistence boundary away from `Database`
- redesign collection names or ArangoDB schema ownership
- broaden runtime registration beyond vector collections
- move DTO shaping into persistence
- reintroduce hand-written per-collection AQL files
- invent a free-form end-user query DSL
- quietly supersede ADR-030’s accepted public-shape constraints without calling out where a future ADR may be needed

---

## Architecture

### Layer Mapping

| Component | Layer | Responsibility |
| ----------- | ------- | ---------------- |
| `nomarr/persistence/db.py` | persistence | Owns the connection, instantiates collections, exposes the stable `Database` facade, and remains the only public entry point |
| `nomarr/persistence/collections.py` | persistence | Declares concrete collection wrappers, field metadata, and collection-family selection |
| `nomarr/persistence/collections_base.py` | persistence | Defines generic collection families (`BaseCollection`, `DocumentCollection`, `EdgeCollection`, `StateGraphCollection`, `VectorCollection`) and only the storage-native special capabilities that genuinely belong in persistence |
| `nomarr/persistence/accessors.py` | persistence | Transitional binding layer for current collection/field accessor ergonomics; no longer the architectural center |
| `nomarr/persistence/query_specs.py` *(new/revised concept)* | persistence | Declarative query-spec and capability metadata for generic collection/document operations |
| `nomarr/persistence/query_templates.py` *(new/revised concept)* | persistence | Fixed, reviewed AQL templates for capability families; not a free-form query DSL |
| `nomarr/persistence/aql_validation.py` *(new/revised concept)* | persistence | Spec/template validation, linting helpers, and parse/plan validation hooks |
| components / workflows | higher layers | Own multi-step compositions, cross-collection orchestration, and domain semantics that should not live in persistence |

### Design Center

The revised design centers on three ideas:

1. **Collection-first public surfaces** — persistence is organized around collection namespaces on `Database`, not field namespaces.
2. **Query specs as the carrier of criteria** — equality, inclusion, range, pattern, and match semantics belong in validated query specs/templates rather than in sprawling field-bound surface names.
3. **Capability families instead of “verbs” as the master abstraction** — capability families describe what persistence can do; query specs describe how a particular collection operation is constrained.

The implementation may still use methods and callables under the hood — Python is still Python, not interpretive dance — but the design no longer treats the verb catalog itself as the architecture.

### Core Abstractions and Ownership

To avoid turning `query specs` into “verbs with glasses,” the design separates four concerns that the current model blurs together:

1. **Capability family**
   - the normalized operation class (`read`, `write`, `aggregate`, `relationship-native`, `state-native`, `ann-search`, `administrative`)
   - answers: *what kind of persistence operation is this?*

2. **Query spec**
   - the validated criteria/operator payload allowed for a capability on a given collection
   - answers: *what inputs are legal for this operation?*

3. **Template asset**
   - the fixed first-party AQL template used to implement a capability/spec combination
   - answers: *which reviewed AQL shape executes this operation?*

4. **Surface API**
   - the collection-level Python call shape exposed via `Database`
   - answers: *how does application code invoke this operation?*

These layers must not collapse back into one overloaded abstraction. A query spec does not own naming taxonomy, does not imply its own storage-native status, and does not authorize arbitrary new AQL.

### Public Surface Model

The normative public persistence shape becomes:

- `db.<collection>` is the primary namespace.
- Generic operations are invoked at the collection level using validated query criteria/specs.
- Field metadata remains available to validate criteria, uniqueness assumptions, and result-shape expectations.
- Field accessors are **not** the preferred long-term public surface.

Examples of the intended direction:

- collection-first read/filter operations such as `db.tags.get(...)` / `db.tags.get.many(...)` using validated criteria
- collection-first write operations such as `db.library_files.insert(...)`, `db.library_files.update(...)`, `db.library_files.upsert(...)`, `db.library_files.delete(...)`
- collection-first counting/aggregation such as `db.tags.count(...)`, `db.tags.aggregate(...)`

This design intentionally avoids standardizing a new Python call signature in the DD. The important choice is architectural: **criteria live in query specs and validated collection-level inputs, not in ever-expanding field-first mini-APIs.**

### Normalized Naming and Capability Taxonomy

The persistence surface should be described using a small number of normalized capability families.

| Capability family | Scope | What belongs here | What does not belong here |
| ------------------- | ------- | ------------------- | --------------------------- |
| **Document read** | generic persistence | get one, get many, equality/inclusion/range/pattern criteria, pagination | graph traversals, ANN search, multi-step fetch pipelines |
| **Document write** | generic persistence | insert, update, upsert, delete | cross-collection orchestration, edge maintenance side effects not intrinsic to one collection write |
| **Aggregation** | generic persistence | count, aggregate, distinct/collect-like storage-shaped summaries | domain DTO shaping, business scoring, semantic post-processing |
| **Relationship-native** | storage-native persistence | graph traversal, cascade delete, relationship-count primitives that are genuinely graph-native and reusable across collections | collection-specific relinking workflows or domain curation pipelines |
| **State-native** | storage-native persistence | atomic state-graph transition on `StateGraphCollection` | use-case orchestration around transition retries, auditing, or follow-up writes |
| **ANN search** | storage-native persistence | approximate nearest-neighbor vector search and only the minimal inputs/filters required by the storage engine | vector ingestion flows, edge maintenance, collection moves, domain ranking logic |
| **Administrative maintenance** | narrow persistence/admin | truncate and similar storage-maintenance primitives with clear single-step semantics | batch business actions or migration orchestration |

Key normalization rules:

1. **Operators are not capability families.** `eq`, `in`, `gte`, `lte`, and `like` are query-spec operators/criteria forms, not separate architectural namespaces.
2. **Collection is primary; field is metadata.** Fields define what may be queried or matched, but they do not automatically earn dedicated public method trees.
3. **A special name requires special semantics.** If an operation is not storage-native, it should either become a generic collection capability or move above persistence.
4. **Vector is not a permission slip for bespoke naming.** Only ANN search clearly qualifies as vector-native. Most other vector-branded methods should be reclassified.

### Public Naming Grammar

The collection-first API must follow a naming grammar strict enough to prevent drift back into bespoke helper names.

#### Grammar rules

1. **Capability family names are small and stable.**
   - Preferred roots are families such as `read`, `write`, `aggregate`, `relationship`, `state`, `search`, and `admin`.
   - The exact Python spelling may be finalized during planning, but the family inventory must remain closed and reviewed.

2. **Criteria are expressed as data, not method explosion.**
   - Equality, inclusion, range, pattern, uniqueness, and match-key semantics belong in validated criteria/query-spec payloads.
   - Avoid method names that encode query predicates as endless suffixes.

3. **Domain nouns do not appear in generic persistence helper names.**
   - Names such as `delete_by_file_id`, `upsert_vector`, or `get_vectors_by_file_ids` are presumptively wrong unless they describe a genuinely storage-native primitive.
   - If a helper name contains domain context to explain itself, it likely belongs above persistence.

4. **Special names are reserved for special semantics.**
   - Only storage-native primitives may keep dedicated names such as `ann_search` or a future normalized relationship/state primitive.
   - “Special because history” is not a valid naming rationale.

5. **Collections expose one normative surface.**
   - Compatibility aliases may exist during migration, but the DD should not bless parallel long-term naming systems.

#### Consequences

- Generic persistence naming is governed by capability families plus validated criteria payloads.
- Query operators stop multiplying public method names.
- Existing helper names that fail this grammar must either be reclassified as generic capabilities, renamed as true storage-native primitives, or moved out of persistence.

### Field Accessor Policy

Field accessors should be treated as follows:

- **Not the design center.** New design work should not start by asking “which field accessor should own this?”
- **Deprecated as a first-class architectural concept.** The DD no longer treats field-first surfaces as co-equal with collection-first surfaces.
- **Retained as compatibility shims during migration.** Because ADR-030 currently preserves field-bound ergonomics and the live code exposes `FieldAccessor`-based APIs such as `db.library_files.path.get(...)` and `db.tags.rel.get.many(...)`, immediate removal would create contract churn without a follow-up decision.
- **No new field-first surface area by default.** New capability additions should target collection-first query-spec surfaces unless a compelling exception is documented.

Recommended direction: **deprecate field accessors as the normative API and retain them only as migration/compatibility shims until collection-first call sites and design conventions are established.** A later ADR may fully remove or drastically reduce them if the migration proves low-risk.

### Field Accessor Kill Criteria

Field accessors should not linger indefinitely as “temporary forever” compatibility surface. Their retirement criteria should be explicit:

1. **Immediate rule:** no new field-first APIs or enhancements are allowed unless a design review documents a compelling exception.
2. **Design-complete rule:** every new persistence feature introduced after this DD must target the collection-first surface first.
3. **Migration-ready rule:** once the collection-first surface has parity for current generic document primitives, internal persistence code must stop depending on field accessors except for compatibility adapters.
4. **Caller-migration rule:** once downstream call sites have a proven migration path and compatibility metrics are understood, field-first call sites should be migrated planfully rather than opportunistically forever.
5. **Removal rule:** full removal or severe narrowing of field accessors should occur only after a follow-up ADR confirms that ADR-030’s field-ergonomics expectations have been intentionally superseded.

Success condition: field accessors become a shrinking compatibility shell, not a second living architecture.

### Generic Document and Collection Primitives

The following belong in persistence as generic collection-first capabilities:

- read one / read many
- filter by validated criteria (including equality, inclusion, range, pattern)
- insert
- update
- upsert / batch upsert where the match key is explicit
- delete
- count
- aggregate / collect-like storage-shaped summaries
- truncate or similarly narrow maintenance primitives

These should be expressed through a normalized collection-first API backed by validated query specs/templates. They should not be split into separate field-first namespaces unless compatibility requires temporary aliases.

### Genuine Storage-Native Primitives

The following remain explicit persistence capabilities because they reflect native storage semantics that do not generalize cleanly into ordinary document query specs:

- **Graph traversal** compiled from `DocumentCollection.EDGES`
- **Cascade delete** compiled from the same `EDGES` authority
- **State transitions** on `StateGraphCollection.transition(...)`, but only if Nomarr keeps proving that this is a true atomic state-graph primitive rather than merely a named instance of a broader relationship mutation family
- **ANN search** on `VectorCollection.ann_search(...)`

Potentially storage-native but requiring normalization review rather than bespoke naming:

- inbound/outbound relationship counting helpers currently exposed on `BaseCollection`
- other graph-topology-aware aggregate helpers that may merit one reusable relationship-native family if they are broadly applicable

The rule is strict: an operation stays special only when the underlying storage engine or graph/state model makes it materially different from generic document access.

For `transition(...)` specifically, the burden of proof is higher than in the previous DD revision. It remains special only if all of the following stay true:

- the operation must preserve an atomic state-graph invariant that generic document/edge writes do not capture cleanly
- the operation cannot be normalized into a more general, reusable relationship/state mutation family without losing clarity
- the operation remains single-step persistence rather than orchestration hiding behind a storage-flavored name

If those conditions stop holding during implementation planning, `transition` should be demoted or reclassified rather than grandfathered in.

### Collection Family Status

The current collection family split (`DocumentCollection`, `EdgeCollection`, `StateGraphCollection`, `VectorCollection`) should be treated as **implementation scaffolding**, not as untouchable public architecture.

- **`DocumentCollection`** and **`EdgeCollection`** remain useful internal categories because Arango distinguishes documents from edges in real storage semantics.
- **`VectorCollection`** is justified only to the extent it carries truly vector-native behavior (`ann_search`) and narrow runtime-registration rules; it is not a blanket excuse for bespoke persistence helpers.
- **`StateGraphCollection`** is justified only if `transition` remains a true storage-native primitive under the stricter test above.

If future planning shows that a family exists only to preserve helper names or historical code layout, the family should collapse into simpler implementation scaffolding rather than shaping the long-term architecture.

### Higher-Layer Compositions That Should Not Live in Persistence

The following should be treated as higher-layer composition unless they can be justified as reusable, single-step, storage-native primitives:

- vector ingestion helpers that combine document upsert with edge maintenance (`upsert_vector(...)` plus `file_has_vectors` maintenance)
- latest-vector retrieval policies such as `get_vector(file_id)` when they encode selection semantics rather than raw collection access
- bulk vector delete helpers that are only thin orchestration over generic delete criteria
- vector/document collection move/re-point helpers where the real work is multi-step copy/delete/edge repair orchestration
- domain workflows such as tag relinking, bulk tag replacement, or transition follow-up behavior

In short: if the operation is really “a few generic persistence calls plus orchestration,” it belongs above persistence.

### Source of Truth

The declarative source-of-truth model becomes explicitly layered:

1. **Collection declarations and field metadata** define what collections and fields exist.
2. **`EDGES` metadata** remains the single authority for traversal and cascade semantics.
3. **Capability-family definitions** define the generic persistence operations Nomarr supports.
4. **Query specs and fixed templates** define how generic operations are validated and compiled.

This preserves ADR-025’s declarative intent without overloading a single “verb catalog” to also carry naming, capability taxonomy, and query semantics.

---

## AQL Validation and Linting Strategy

### Why this must be first-class

The live helper layer in `nomarr/persistence/constructor/verbs.py` already performs minimal safety validation for interpolated field names and logs executed AQL, but that is not enough for the next persistence design. Once query specs/templates become the architectural center for generic operations, validation must happen at the same level.

### Required validation layers

#### 1. Spec-time validation

Each query spec/template pairing must validate, before execution where possible:

- referenced collection exists in the declarative persistence model
- referenced fields exist on the target collection
- operator is allowed for the referenced field/capability family
- uniqueness assumptions are explicit rather than implied
- pagination/aggregation inputs are structurally valid
- sort/filter/aggregate fields are whitelisted by metadata rather than raw string pass-through
- template bind variables are complete and match the template contract
- no raw AQL fragments are accepted from higher layers

#### 2. Compile-time or bind-time validation

When generic collection capabilities are attached/bound, the system should validate:

- the capability family is valid for the collection family
- the result shape promised by the capability is compatible with the collection/field metadata
- unsupported combinations fail early and deterministically
- dynamic vector collections validate against the template family plus representative collection naming rules, not ad hoc runtime guesses

#### 3. Parse / plan validation

Where feasible, Nomarr should validate first-party AQL templates using Arango parse/plan facilities before they are relied on in production:

- compile every first-party query template with representative schema contexts in tests/CI
- run parser/explain validation on generated AQL for the supported capability families
- validate representative dynamic vector namespaces as part of the same suite
- surface explain/plan failures as design-time or CI failures, not only runtime surprises

This does not require every application startup to block on a full validation pass, but the architecture must make such checks possible and normal in development/CI.

#### 4. Runtime safety expectations

At runtime, persistence should execute only reviewed, cataloged query templates/spec combinations. Unknown template IDs, unsupported operators, or incomplete bindings should fail fast with explicit errors rather than falling back to stringly-typed AQL assembly.

### Concrete design expectations

- Query templates are **fixed assets**, not per-call AQL builders.
- Validation utilities are first-party modules in persistence, not incidental test helpers.
- Every generic capability family has validation coverage proving that its supported query-spec shapes compile correctly.
- The design should support future lint commands/tests that enumerate all first-party templates and run parse/explain checks.
- AQL logging remains useful, but logging alone is not validation.

---

## Alternatives Considered

### Alternative A — Keep the descriptor-bound verb-spec framing with field-first surfaces preserved as peers

**Summary:** Retain the current DD direction, formalize verb specs, and continue treating collection and field surfaces as co-equal architectural targets.

**Pros**

- Lowest change to the existing document and live API framing
- Easier to migrate incrementally without confronting field-surface complexity directly

**Cons**

- Preserves the overloaded “verb” concept as the architectural center
- Keeps field-first complexity alive without proving it still earns its cost
- Does not normalize naming well
- Encourages more special-case helper growth under inconsistent namespaces

**Assessment:** Rejected as the main direction. It improves internal structure but not the core architectural framing problem.

### Alternative B — Collection-first query-spec and capability-family model with field accessors demoted to shims (**recommended**)

**Summary:** Keep `Database` as the only public boundary, make collection namespaces primary, use validated query specs for generic document operations, keep only truly storage-native primitives special, and treat field accessors as transitional compatibility shims.

**Pros**

- Addresses the overengineered field-first surface directly
- Produces a normalized vocabulary that separates generic operations from storage-native behavior
- Makes AQL validation an explicit architectural responsibility
- Keeps ADR-025 and ADR-030 constraints intact while clarifying where a future ADR may refine field ergonomics further
- Better distinguishes persistence responsibilities from higher-layer orchestration

**Cons**

- Requires a deliberate migration story rather than a purely internal refactor
- May eventually require an ADR to supersede or narrow the field-ergonomics part of ADR-030 once migration is proven
- Forces sharper decisions about which existing helpers do not belong in persistence

**Assessment:** Best fit for the user critique and the current architecture direction.

### Alternative C — Fully generic persistence DSL / template engine

**Summary:** Generalize persistence into a flexible spec language capable of expressing arbitrary AQL-shaped queries.

**Pros**

- Maximum flexibility
- Could absorb many edge cases under one engine

**Cons**

- Violates ADR-025’s constrained persistence direction
- Makes validation, review, and security materially harder
- Blurs the line between persistence primitives and orchestration/query authoring

**Assessment:** Rejected. Nomarr needs tighter scope, not a more ambitious query language.

---

## Migration and Rollout Strategy

### Migration stance

This revision does **not** recommend immediate breaking removal of field accessors from the live system. It recommends **architectural demotion first, compatibility-shim retention second, and eventual removal only after explicit follow-up review/ADR if warranted**.

### Recommended rollout phases

1. **Inventory and classify the live persistence surface**
   - categorize every current method as generic document primitive, storage-native primitive, or higher-layer composition
   - explicitly identify vector-branded helpers that are not truly vector-native

2. **Define the normalized capability taxonomy and query-spec model**
   - establish the canonical collection-first naming model
   - document supported criteria/operator forms separately from capability family names

3. **Introduce AQL validation infrastructure early**
   - add spec/template validation rules
   - add parse/explain validation coverage for first-party templates
   - make validation failure a development/CI concern rather than a runtime surprise

4. **Add collection-first surfaces as the normative path**
   - route new design and implementation work through collection-first capabilities
   - forbid creation of new field-first APIs unless explicitly justified
   - forbid new generic persistence helper names that violate the naming grammar

5. **Retain field accessors only as compatibility shims**
   - preserve existing call sites temporarily where required for stability
   - document them as compatibility paths rather than normative architecture
   - plan call-site migration explicitly; do not rely on “opportunistic” cleanup as the primary retirement strategy

6. **Move non-native helper logic above persistence**
   - re-home orchestration-heavy vector/transition helpers into components or workflows
   - keep only genuinely storage-native primitives special in persistence

7. **Consider final field-accessor removal or narrowing in a follow-up ADR**
   - once collection-first usage and migration risk are understood
   - only if compatible with broader persistence direction and caller impact

### Exit Criteria

The migration is not complete merely because new modules exist. It is complete only when:

- the normative collection-first surface is documented and used for all new persistence work
- no new field-first helpers have been added since adoption of this DD
- generic helper naming conforms to the public naming grammar
- every legacy specialized helper has been classified as generic capability, true storage-native primitive, or higher-layer composition
- internal persistence implementation no longer depends on field accessors as an architectural concept
- a follow-up ADR decision has been made on whether field accessors remain as compatibility shell or are formally removed/narrowed

### Migration guardrails

- `Database` remains the only public entry point throughout migration.
- `EDGES` remains authoritative throughout migration.
- runtime registration remains vector-only unless separately re-decided.
- persistence continues returning storage-shaped results.
- no migration step may smuggle multi-step orchestration into persistence.

---

## Risks and Mitigations

### 1. Compatibility churn from demoting field accessors

**Risk:** The codebase may still rely heavily on field-first call sites, and a too-aggressive migration would create noise or breakage.

**Mitigation:**

- keep field accessors as explicit compatibility shims first
- stop adding new field-first APIs
- migrate callers in planned phases rather than forcing immediate flag-day removal

### 2. Replacing one overloaded abstraction with another

**Risk:** “Query spec” could become just a more fashionable way to hide uncontrolled complexity.

**Mitigation:**

- keep capability families small and reviewed
- keep operators/criteria separate from capability-family naming
- keep query specs separate from template assets and from public API naming
- prohibit raw AQL or unbounded spec extensibility

### 3. Misclassifying storage-native vs higher-layer behavior

**Risk:** Some helpers may be prematurely pushed upward or incorrectly kept special.

**Mitigation:**

- require justification for every special capability
- classify based on storage-native semantics, not historical naming
- prefer composition above persistence when the operation is really several generic calls

### 4. AQL validation depending too heavily on runtime environment

**Risk:** Parse/plan validation may require infrastructure that is not always present locally.

**Mitigation:**

- separate spec-time validation from environment-backed parse/explain checks
- make parse/plan checks mandatory in CI and available locally where practical
- keep runtime failure modes explicit when validation cannot be completed ahead of time

### 5. Circular imports or instance-state leakage during refactor

**Risk:** Reworking query specs/templates/validation could recreate prior import-cycle or shared-state hazards.

**Mitigation:**

- keep metadata/spec modules side-effect free
- bind runtime state per `Database` instance only
- avoid class-level caches that capture database handles
- respect ADR-026 by treating deferred first-party imports as emergency workarounds, not the final design

---

## Constraints

- Must remain compliant with ADR-025’s schema-driven, declarative, single-step persistence boundary.
- Must keep `Database` as the only public persistence entry point per ADR-030.
- Must keep `EDGES` as the authoritative source for traversal and cascade semantics.
- Must keep dynamic runtime registration narrow and vector-only unless explicitly re-decided.
- Must preserve storage-shaped persistence results.
- Must not reintroduce hand-written per-collection AQL modules.
- Must not turn persistence into an orchestration layer.
- Must account for ADR-026 by using clean package seams rather than normalizing deferred first-party imports.

---

## Open Questions

1. **Does full removal of field accessors require a follow-up ADR that narrows or supersedes the field-ergonomics portion of ADR-030?**
   - Current recommendation: yes, if Nomarr wants more than architectural demotion plus shims.

2. **Should relationship-count helpers become one normalized storage-native family, or should they move above persistence if they are not broadly reusable?**
   - Current recommendation: review explicitly during implementation planning; do not preserve bespoke names by default.

3. **Should collection move/re-point helpers remain in persistence as administrative primitives, or move upward as orchestration?**
   - Current recommendation: be skeptical of keeping them in persistence unless they are clearly single-step and storage-native.

4. **How much parse/plan validation should run in local development versus CI?**
   - Current recommendation: spec validation should be local and cheap; parse/explain validation must be normal in CI and available locally when infrastructure exists.

5. **What exact Python surface should collection-first query specs use?**
   - Current recommendation: decide during planning/implementation, but keep the architectural rule fixed: criteria belong to validated query specs on collection surfaces, not new field-first namespaces.

6. **Does `transition` survive as a dedicated persistence primitive after applying the stricter storage-native test, or does it collapse into a more general relationship/state mutation family?**
   - Current recommendation: require explicit justification during planning rather than preserving it by inheritance from the current model.

---

## Appendix: Research Findings

### Artifact findings

- **ADR-025** keeps persistence schema-driven, declarative, and single-step, and rejects drifting back to hand-written per-collection AQL organization.
- **ADR-026** rejects deferred first-party imports as the normal architectural answer to circular imports.
- **ADR-030** fixes `Database` as the only public persistence entry point, keeps `EDGES` authoritative, keeps runtime registration vector-only, and keeps persistence results storage-shaped.
- Prior persistence DDs and design parts show recurring concern about descriptor/class-level shared state and support per-instance `Database` ownership as the safer binding model.

### Live code findings

- `nomarr/persistence/db.py` instantiates concrete collections per `Database` instance and limits runtime registration to vector collection templates via `Database.register(...)`.
- `nomarr/persistence/accessors.py` exposes both `FieldAccessor` and collection accessors; field surfaces currently include operations such as `get`, `many`, `in_`, `gte`, `lte`, `like`, `update`, `upsert`, `count`, and aggregate-adjacent helpers.
- `nomarr/persistence/collections_base.py` shows the real family split already present in code: generic collection methods on `BaseCollection`, graph-native behavior on `DocumentCollection`, edge collections on `EdgeCollection`, state-native transitions on `StateGraphCollection`, and ANN/vector helper methods on `VectorCollection`.
- `nomarr/persistence/constructor/verbs.py` currently executes fixed AQL templates, logs AQL, and validates interpolated field names, but it does not yet provide the fuller spec/template validation and parse/plan checking model this DD now requires.

### References

- `artifacts/decisions/ADR-025-schema-driven-persistence-constructor-supersedes-hand-written-aql-conventions.md`
- `artifacts/decisions/ADR-026-top-level-imports-by-default-no-deferred-imports-except-heavy-third-party-libraries.md`
- `artifacts/decisions/ADR-030-adopt-descriptor-based-database-facade-for-persistence-access.md`
- `artifacts/designs/pending/DD-persistence-schema-refactor.md`
- `artifacts/designs/pending/DD-persistence-instance-refactor.md`
- `artifacts/designs/pending/DD-db-register-and-template-split.md`
- `artifacts/designs/parts/class-schema/README.md`
- `artifacts/designs/parts/persistence-instance-refactor/README.md`
- `nomarr/persistence/db.py`
- `nomarr/persistence/accessors.py`
- `nomarr/persistence/collections_base.py`
- `nomarr/persistence/constructor/verbs.py`
