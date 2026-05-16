# Persistence Tier 2 Domain Capability Bindings Refactor — Design Document

**Status:** Draft  
**Author:** GitHub Copilot  
**Created:** 2026-05-15  

**Related Documents:**

- [ADR-031: AQL Primitives and Intent Sub-Facades as Canonical Persistence Architecture](../../decisions/ADR-031-aql-primitives-and-intent-sub-facades-as-canonical-persistence-architecture.md) — Governing three-tier persistence architecture
- [DD: Persistence Layer Consolidation: AQL Primitives + Intent Facade](./DD-persistence-aql-primitives-intent-facade.md) — Parent DD that defines Tier 1 / Tier 2 / Tier 3 roles
- [DD: Persistence Tier 3 Intent API Refactor](../completed/DD-persistence-tier3-intent-api-refactor.md) — Public sub-facade cleanup that depends on correct Tier 2 ownership
- [ASR-0013](../../requirements/ASR-0013.md) — Tier 3 must expose complete caller-facing intent APIs
- [ASR-0014](../../requirements/ASR-0014.md) — Layer boundaries are crossed only through defined contracts
- [ADR-004: Schema Refactor V1 — Graph Normalization and Collection Decomposition](../../decisions/ADR-004-schema-refactor-v1-graph-normalization.md) — Preserved storage model constraints
- [Persistence Lower-Tier Bindings + Primitives Refactor — Parts README](../parts/persistence-lower-tier-bindings-primitives-refactor/README.md) — Existing lower-tier decomposition and sequencing context
- [Persistence Lower-Tier Bindings + Primitives Refactor — Contracts Ledger](../parts/persistence-lower-tier-bindings-primitives-refactor/CONTRACTS.md) — Existing lower-tier contract lock and module-family ownership matrix

---

## Scope

`nomarr/persistence/database/**`, the Tier 2-facing wiring in `nomarr/persistence/db.py` and `nomarr/persistence/api/**`, and tests/docs that define or validate the Tier 2 contract.

This DD covers the **Tier 2 internal API surface only**. It does not redesign the schema, replace Tier 1 primitives, or change the Tier 3 rule that callers use only `db.library`, `db.app`, and `db.ml`.

It also assumes the lower-tier work happens **after** the Tier 3 public-surface cleanup gate described in the existing parts/ledger artifacts. This DD is therefore a contract-clarification and implementation-shaping document for persistence internals, not a reopening of the caller-facing Tier 3 API.

---

## Problem Statement

`ADR-031` correctly defines Tier 2 as a set of thin domain capability bindings over `SafeDatabase`, but the live codebase still treats Tier 2 more as an implementation habit than an explicit contract.

Today Tier 2 has useful structure — `LibrariesAqlOperations`, `LibraryFilesAqlOperations`, `TagsAqlOperations`, `AppAqlOperations`, `VectorsAqlOperations`, and so on — but several important rules are only implied:

1. **The boundary between Tier 2 and Tier 3 is under-specified.** Some Tier 2 methods are legitimate capability bindings, while others expose partial mechanics that Tier 3 should compose privately and never mirror one-to-one for callers.
2. **The boundary between Tier 2 and Tier 1 is under-specified.** Some modules correctly reuse primitives; others hand-write AQL for small convenience shapes with no documented reason; still others need custom AQL but do not clearly state why the primitive layer stops short.
3. **Tier 2 method shape is inconsistent.** Some methods express a domain capability (`remove_files`, `vector_search`), some are storage-shaped helper steps (`upsert_file_has_vector_edge`, `upsert_library_scan_edge`), and some are destructive reset routines that now belong on maintenance surfaces higher up the stack.
4. **Migration sequencing is easy to get wrong.** The Tier 3 refactor already showed that removing thin compatibility methods too early causes contract drift and caller breakage. The same risk exists for Tier 2: promoted Tier 3 intents need stable internal backing before low-level helpers are removed, split, or internalized.

Without a dedicated Tier 2 DD, the refactor risks cleaning up Tier 3 while leaving Tier 2 as a semi-public bag of ad hoc methods. That would preserve the leak one layer lower instead of actually closing it.

---

## Current Codebase Observations

The live repository already implements parts of the intended architecture, which this DD should codify rather than ignore:

1. **Tier 3 wiring already exists.** `nomarr/persistence/db.py` already constructs `db.library`, `db.app`, and `db.ml`, and its inline comments explicitly describe direct Tier 2 aliases as persistence-internal compatibility debt rather than supported caller API.
2. **Maintenance namespaces already exist.** `LibraryDb`, `AppDb`, and `MlDb` already expose `.maintenance` companions, so this DD should treat maintenance isolation as live architecture, not a future idea.
3. **Legacy Navidrome isolation already exists.** `AppDb` already confines plugin-era mapping/play persistence to `db.app.legacy_navidrome`, which means the Tier 2 contract should describe `NavidromeAqlOperations` as an isolated legacy surface rather than an ordinary app-domain public contract.
4. **Architecture enforcement already exists.** `tests/test_architecture_qc.py` already enforces that higher layers do not import `nomarr.persistence.database` or `nomarr.persistence.aql` directly, with one narrow bootstrap allowlist for `nomarr/components/platform/arango_bootstrap_comp.py`.
5. **Some persistence choreography still lives in Tier 3.** `LibraryDb` and `MlDb` still contain Python-side storage choreography such as file cleanup, tag-edge replacement, stream/vector replacement, and model-output edge maintenance. Those are concrete candidates for Tier 2 consolidation if they remain necessary after the Tier 3 cleanup gate.

---

## Non-Goals

This refactor does **not**:

- make Tier 2 importable by components, workflows, or services
- promote `*_aql.py` classes to a supported public API
- flatten all custom AQL into Tier 1 primitives
- require every Tier 2 method to map one-to-one to one collection
- change collection names, edge collections, `_id`, or `_key`
- redesign the three Tier 3 sub-facades or maintenance surfaces beyond the Tier 2 support they require

---

## Architecture

## Core Decision

Tier 2 is the **private persistence capability layer**.

Its job is to own storage-native operations that are too domain-specific for Tier 1 but too mechanical for Tier 3 to expose directly. Tier 2 is where persistence knows collection names, edge collections, AQL traversals, document-key normalization, and cross-collection write choreography details.

Tier 2 is therefore both:

- **more specific than Tier 1**, because it binds actual Nomarr domains and collections
- **less public than Tier 3**, because higher layers never depend on its names or storage mechanics

The practical rule is simple:

- **Tier 3 says what the application is trying to do**
- **Tier 2 says how Nomarr storage makes that true**
- **Tier 1 says what reusable AQL shapes exist**

### Tier 2 contract rules

1. **Tier 2 classes are private implementation details of persistence.**
2. **Each Tier 2 class owns one persistence domain, not one caller-facing API.**
3. **Tier 2 may touch multiple collections or edges when that is the storage-native definition of one domain capability.**
4. **Tier 2 methods may be storage-shaped; Tier 3 methods may not be.**
5. **Tier 2 should reuse Tier 1 primitives by default, but may use handwritten AQL when the shape is genuinely domain-specific.**
6. **Higher layers must never import Tier 2 modules directly.**
7. **Tier 2 does not decide business policy. It implements persistence-native semantics only.**

### What counts as a Tier 2 responsibility

Tier 2 owns:

- collection names and edge collection names
- `_id` / `_key` normalization needed for persistence-local correctness
- AQL traversals and graph-native write patterns
- cross-collection delete choreography that is the canonical storage definition of removing one logical entity
- collection-specific filtering, sorting, and projection queries
- runtime collection mechanics such as vector collection registration and collection-level search
- maintenance/reset operations that are later exposed only through explicit maintenance surfaces

Tier 2 does **not** own:

- deciding when the app should perform an action
- choosing between domain alternatives based on business meaning
- caller-facing naming stability
- policy validation that belongs in components/workflows/services

### Complete-internal contract

Tier 2 does not need to be caller-facing, but it does need to be internally complete.

If a Tier 3 method routinely needs awkward multi-step Python choreography over several low-level Tier 2 methods just to perform one storage-native operation, that is a Tier 2 smell. The correct fix may be:

- a new richer Tier 2 method
- consolidation of several thin Tier 2 methods into one canonical storage-native method
- or moving the custom AQL into a single Tier 2 method where atomicity and cleanup are easier to reason about

Tier 3 should compose intent, not reconstruct graph mechanics line by line.

---

## Method Taxonomy

Every Tier 2 method should fall into one of four buckets:

| Bucket | Meaning | Target state |
| --- | --- | --- |
| **Capability binding** | Stable storage-native operation used by Tier 3 or persistence internals | Keep as Tier 2 public-to-persistence surface |
| **Custom domain AQL** | Capability that cannot be expressed cleanly via Tier 1 primitives | Keep, but document why handwritten AQL is justified |
| **Private helper** | Internal method only useful inside one `*_aql.py` class | Internalize with leading `_` or local function |
| **Maintenance binding** | Destructive/reset/diagnostic operation | Keep in Tier 2, but expose only via Tier 3 `.maintenance` surfaces |

### Naming rules

Tier 2 names are allowed to reflect storage-native semantics more directly than Tier 3, but they still need discipline.

Preferred verbs:

- `get_*`
- `list_*`
- `find_*`
- `count_*`
- `insert_*`
- `add_*`
- `update_*`
- `upsert_*`
- `delete_*`
- `remove_*`
- `replace_*`
- `truncate_*` for maintenance only

Allowed in Tier 2 but not Tier 3 when the storage shape matters:

- `*_edge`
- `link_*`
- `unlink_*`
- `bulk_*`
- collection-specific names like `vector_search`

Disallowed:

- vague verbs with no storage meaning (`process_*`, `handle_*`, `do_*`)
- method names that encode caller workflow policy rather than persistence capability
- duplicative aliases that exist only because the migration has not yet deleted one of them

---

## Target Shape by Module Family

## Library-domain bindings

### `LibrariesAqlOperations`

This module should own library-document capabilities and library-root destructive cleanup.

**Keep as Tier 2 capabilities:**

- `add_library`
- `get_library`
- `get_library_by_name`
- `list_libraries`
- `list_library_keys`
- `update_library`
- `remove_library`

**Rules:**

- `remove_library` is valid as Tier 2 because library deletion is canonically storage-defined and touches multiple collections.
- Generic one-step delete helpers that are weaker than `remove_library` should not become the preferred internal contract unless a Tier 3 path explicitly needs the narrower semantics.

### `LibraryFilesAqlOperations`

This module owns file and folder persistence plus direct ownership/link mechanics where that is the storage truth.

**Keep as Tier 2 capabilities:**

- document CRUD/query helpers for files and folders
- canonical storage cleanup helpers such as `remove_files`
- library↔file and library↔folder relationship operations needed internally by Tier 3 file and folder intents
- lookup helpers such as `list_existing_file_paths`, `list_library_file_ids`, and path/file resolution queries

**Internalize or demote:**

- helper methods that exist only to support one richer Tier 2 operation
- duplicate low-level link helpers once richer bulk/canonical variants exist

**Notes:**

- It is acceptable for this module to know about ownership edges because that is part of file persistence.
- It is not acceptable for callers above persistence to know those details.

### `TagsAqlOperations`

This module owns tag documents and tag-edge graph operations.

**Keep as Tier 2 capabilities:**

- tag lookup/list/count/search functions
- file↔tag edge retrieval and replacement primitives used by Tier 3 tag lifecycle methods
- canonical orphan detection and cleanup helpers used by library-domain tag intents
- tag-value aggregation/frequency queries that are truly storage-native

**Rules:**

- Tier 2 may expose storage-native edge operations because they are useful implementation tools.
- Tier 3 must not simply mirror them as public routines.

---

## App-domain bindings

### `FileStatesAqlOperations`

This module owns file-state graph storage, including graph-target replacement and edge cleanup.

**Keep as Tier 2 capabilities:**

- `get_file_state`
- `list_files_in_state`
- `count_files_in_state`
- `transition_file_states`
- `add_file_state_edge`
- `delete_file_state_edges`
- storage-level edge inspection helpers if needed by app maintenance/diagnostics

**Rule:** state graph mutation is storage-native here, even if Tier 3 later wraps it in cleaner intent verbs.

### `ScanAqlOperations` and `AppAqlOperations`

The scan/app split should remain explicit but disciplined.

- `ScanAqlOperations` owns scan record documents.
- `AppAqlOperations` owns app-scoped coordination collections and cross-domain graph edges like library→scan and library→pipeline-state.

**Keep as Tier 2 capabilities:**

- lock, claim, health, migration, vram promise, config/meta, and pipeline-state persistence
- scan-edge and pipeline-state-edge maintenance where those are storage-native relationships
- diagnostics/maintenance operations that back `db.app.maintenance`

**Rules:**

- Tier 2 may still include legacy-only Navidrome support while the Tier 3 cleanup is incomplete, but it should remain clearly isolated and non-authoritative.
- generic `meta` helpers may remain in Tier 2 as implementation machinery even if Tier 3 splits them into more explicit public contracts

### `NavidromeAqlOperations`

This module owns the remaining legacy-only Navidrome track mapping and playcount storage mechanics.

**Keep as Tier 2 capabilities:**

- track mapping document and edge maintenance
- bulk mapping resolution helpers used only by legacy sync paths
- playcount/play-edge storage and cleanup helpers

**Rules:**

- `NavidromeAqlOperations` is not part of the routine app-domain public contract.
- Its sanctioned Tier 3 exposure, if any remains, stays isolated under `db.app.legacy_navidrome` rather than the routine `AppDb` method surface.
- No new higher-layer callers should be introduced against these legacy storage-shaped methods.

---

## ML-domain bindings

### `MlStreamsAqlOperations`

This module owns output-stream documents plus the file/output stream association logic that is intrinsic to stream storage.

### `VectorsAqlOperations`

This module owns runtime vector collections, file↔vector edges, ANN search, and collection registration.

**Keep as Tier 2 capabilities:**

- vector collection registration and registry inspection
- vector document upsert/delete/query operations
- file↔vector edge maintenance
- collection truncation/reset operations
- `vector_search`

**Rule:** runtime vector collection knowledge belongs here, not in Tier 1 or Tier 3.

### `MlModelsAqlOperations`

This module owns model documents, model outputs, calibration documents, and graph edges that bind those artifacts together.

**Keep as Tier 2 capabilities:**

- model CRUD/list/count helpers
- model output and calibration graph maintenance
- tag-model-output edge maintenance
- calibration history storage

**Internalize:**

- purely local helper routines for output-id normalization or edge-key derivation that do not need to be part of the class-level method surface

---

## Wiring and Visibility Rules

### `Database` wiring contract

`nomarr/persistence/db.py` may instantiate and retain Tier 2 bindings directly, but those attributes are implementation-only.

Accepted patterns:

- private storage on `Database` or immediate handoff into Tier 3 constructors
- temporary alias exposure during migrations when required for compatibility with already-merged code

Target state:

- Tier 3 sub-facades remain the only supported caller entrypoints
- direct `db.libraries`, `db.library_files`, `db.tags`, `db.scan`, `db.file_states`, `db.ml_streams`, `db.ml_models`, etc. are compatibility debt, not precedent

### Import rule

Only persistence-layer modules may import from `nomarr.persistence.database`.

That includes:

- `nomarr/persistence/db.py`
- `nomarr/persistence/api/**`
- tests that explicitly target Tier 2 modules
- persistence-local tooling/docs

That excludes:

- `nomarr/components/**`
- `nomarr/workflows/**`
- `nomarr/services/**`
- `nomarr/interfaces/**`

One narrow exception already exists in the live codebase: `nomarr/components/platform/arango_bootstrap_comp.py` is allowlisted to work below the normal caller boundary for schema/bootstrap tasks. This exception is intentional, architecture-tested, and must remain narrow; it is not precedent for routine component imports of Tier 1 or Tier 2 internals.

---

## Atomicity and Semantics

Tier 2 is the first layer allowed to encode all-or-nothing storage semantics directly.

When a Tier 3 method promises a single logical write contract, Tier 2 is responsible for implementing the backing operation with one of:

- one handwritten AQL statement
- one explicit transaction
- one persistence-local delete/update choreography that preserves the intended logical semantics

Guidelines:

- Prefer one canonical Tier 2 method over several loosely ordered ones when side effects must travel together.
- Prefer handwritten AQL in Tier 2 over pushing multi-step graph mechanics up into Tier 3.
- When true atomicity is not possible, document the limitation at the Tier 3 contract and keep the failure surface as small as possible in Tier 2.

---

## Migration Strategy

### Phase 1 — Classify the current Tier 2 surface

For each `*_aql.py` module, classify methods into:

- capability binding
- custom domain AQL
- private helper
- maintenance binding

This inventory becomes the living implementation contract for the refactor.

### Phase 2 — Consolidate where Tier 3 composition is too mechanical

Add richer Tier 2 methods when current Tier 3 implementation has to reconstruct storage choreography manually.

Examples to look for:

- write sequences that always require several edge/document mutations together
- delete flows with repeated cleanup logic across Tier 3 methods
- repeated identifier normalization that belongs closer to storage

Current concrete examples include the file-removal and tag-replacement choreography in `nomarr/persistence/api/library.py` and the stream/vector/model-output replacement choreography in `nomarr/persistence/api/ml.py`. These are useful starting points for deciding whether a richer Tier 2 canonical capability is warranted.

### Phase 3 — Internalize local helpers

Move purely local support code behind `_` methods or module-local functions so the observable Tier 2 surface reflects real capability boundaries.

### Phase 4 — Tighten visibility

Once Tier 3 and callers no longer rely on legacy aliases, stop treating `Database` collection-oriented attributes as normative architecture.

### Compatibility rule

Do not delete a Tier 2 method that still backs active Tier 3 behavior unless its replacement is already wired and tested. The Tier 3 refactor already demonstrated the cost of premature cleanup.

---

## Validation

This refactor is correct when all of the following are true:

1. Higher layers do not import `nomarr.persistence.database.*`
2. Tier 3 methods no longer require awkward manual graph choreography where one canonical Tier 2 capability would suffice
3. Tier 2 methods that remain visible at class scope correspond to real storage-native capabilities, not one-off implementation crumbs
4. handwritten AQL in Tier 2 exists only where Tier 1 primitives would be too weak or too contorted
5. maintenance/reset operations remain available to persistence, but only surface through explicit Tier 3 maintenance entrypoints
6. the live code still satisfies ADR-031 and ASR-0014 boundary rules

Recommended validation passes:

- targeted grep for imports of `nomarr.persistence.database` or `nomarr.persistence.aql` outside persistence/tests, with the existing bootstrap allowlist called out explicitly
- `tests/test_architecture_qc.py`
- `tests/unit/persistence/test_db.py` and affected `tests/unit/persistence/database/**` suites
- targeted review of Tier 3 implementations that still compose several Tier 2 methods for one logical write
- path-scoped tests affected by persistence wiring changes, such as `tests/unit/workflows/platform/test_prepare_database_wf.py`, when `Database`/facade registration behavior changes
- architecture/lint checks after visibility cleanup

---

## Risks

- **Accidental promotion.** Documenting Tier 2 too explicitly can tempt contributors to treat it like a public API. The DD must repeatedly state that it is private to persistence.
- **Primitive overreach.** Overzealous Tier 2 cleanup can push domain-specific shapes down into Tier 1 and recreate a new generic abstraction swamp.
- **Under-consolidation.** If Tier 2 remains overly granular, Tier 3 will continue to reassemble storage mechanics by hand.
- **Migration drift.** Compatibility aliases can linger indefinitely unless the cleanup phase is explicit.

---

## Open Questions

1. Should `nomarr/persistence/database/` remain one-file-per-domain, or should particularly large modules split into private subpackages after the Tier 2 contract is stabilized?
2. After the Tier 3 cleanup gate finishes, which currently exposed `Database` Tier 2 aliases can be removed immediately, and which must remain temporarily for persistence-internal compatibility?
3. Which current Tier 3 implementations still justify a dedicated Tier 2 transaction/canonical capability helper rather than Python-side composition — especially the file cleanup/tag replacement flows in `LibraryDb` and the output/vector/model-output replacement flows in `MlDb`?

---

## Completion Criteria

This refactor is complete when:

- Tier 2 has an explicit, coherent internal contract
- storage-native capabilities are easy to locate and reason about
- Tier 3 intent methods sit on top of clear Tier 2 owners rather than accidental helper piles
- higher layers still cross the persistence boundary only through `db.library`, `db.app`, and `db.ml`
- the live code and this DD agree on what Tier 2 is for
