# ADR-048: Song application identity is a mutable library-scoped locator; generated songs.id stays persistence-internal

**Status:** Accepted  
**Date:** 2026-09-09  
**Tags:** architecture, persistence, domain-model, identity, song-locator, song-move, intent-facade  
**Source Log:** rnd-manager#L178  
**Supersedes:** ADR-047  

## Context

ADR-041 says Songs are identified by absolute path, while ADR-047's committed amendment adbb053f adopted stable song_id as the application/entity identity for a Song across moves and renames. The current authoritative user decision resolves that conflict differently: generated songs.id is entirely persistence-internal; the application address is the existing locator-shaped value SongIdentity(LibraryIdentity, normalized_path), contractually named SongLocator. The locator may change on move or rename, and no canonical stable application Song identity is introduced now. Persistence must therefore define locator lifecycle and relocation bookkeeping without rewriting ADR-047's historical record. The user explicitly authorizes this ADR and a scoped ADR-047 amendment; this record is the operative decision for Song identity while preserving ADR-047's general generated-ID, non-Song, ML, and persistence-boundary rules.

## Decision

1. SongLocator is the application-facing Song address. It reuses the existing SongIdentity value shape: SongIdentity(library: LibraryIdentity, normalized_path: str). No second locator dataclass or stable Song wrapper is introduced. Library and path normalization follow the existing library-scoped normalized-path contract; absolute physical path alone is not a global Song identity.

2. SongLocator is mutable and request-scoped. A move or rename changes the locator. After successful relocation, the destination locator is the current address and the old locator no longer resolves. No alias, tombstone, stable handle, or locator-history mechanism is introduced now. A future stable application identity requires a separate explicit decision naming its scope, stability, lifecycle, and contract.

3. Generated songs.id and library_id remain persistence-private. Persistence may resolve SongLocator to those generated keys internally, but neither key crosses a public persistence facade as application identity. No integer library_id crosses the facade, and no integer Song row ID is an ordinary Song read/write identity or fallback.

4. SongLocator crosses the public persistence facade; semantic Song values cross it where required. Callers use locator-shaped commands and application values rather than rows, storage dictionaries, generated IDs, persistence mappers, or reconstructed transaction choreography.

5. Relocation is a persistence-owned atomic intent addressed by the source locator. Persistence resolves (LibraryIdentity, source_normalized_path) privately, updates the existing row in place, and returns the destination SongLocator. The update preserves the internal row and existing state and associations, including tags, state assignments, embeddings, claims, playlists, and other references. It is not delete-plus-create merely because the locator changed. A stale or missing source is a None miss; it must not trigger integer fallback or fabricated replacement. A destination conflict raises DuplicateEntityError and leaves the source row and scan metadata unchanged. The old locator stops resolving after success.

6. Locator addressing has an accepted residual race: stale-replay protection is safe only when the old locator has not been re-occupied by another row between resolution and update. Delete/recreate, move/insert, content-changing, unobserved, absent-fingerprint, and cross-library cases may be indistinguishable from delete-plus-create and may lose associations. Re-derivation through later scan/detection is the recovery discipline; these limitations must not be hidden by exposing songs.id.

7. ADR-041's Song identity wording is reconciled from absolute path to the library-scoped normalized locator (LibraryIdentity, normalized_path); its rule that integer PostgreSQL primary keys are persistence-internal remains in force.

8. ADR-047 is superseded only as to its Song-specific stable-identity adoption passages. Its general generated-ID principle in §2 remains operative: generated IDs require intentional adoption and unrelated generated IDs do not become application identities by implication. ADR-047 §1, §3–§7, and §9–§12, including its non-Song, ML, record-preservation, and persistence-boundary clauses, remain in force and are reasserted here. The prior amendment committed as adbb053f and its explicit approval are preserved as historical facts; the current user authorization is the basis for this reversal and does not retroactively erase that record. ADR-047's status/back-pointer amendment and this ADR must land atomically.

## Consequences

Positive: Song application addressing is explicit, library-scoped, and consistent with the existing value object; generated persistence identifiers remain shielded; moves preserve the existing row and associations; stale and conflict outcomes are deterministic; ADR-041 and ADR-047 are reconciled without rewriting history; future stable identity remains an explicit decision rather than an accidental inference.

Negative and accepted risks: Locators change on moves and stale references must be re-derived. A locator reoccupation race can relocate the wrong row if the old locator is re-occupied between resolution and update; the safe-stale-replay guarantee applies only when it is not re-occupied. Delete/recreate or unobserved/content-changing moves can lose associations. Existing integer-keyed callers, move plans, state reads, and documentation require downstream rebasing. Automatic move-detection wiring remains a separate product decision and stays allowlisted by default.

Implementation boundary: The row-mirror contract should receive an append-only annex binding locator addressing, relocation outcomes, no integer fallback, typed list_songs_with_state ordering after row-mirror semantic Song/mapper prerequisites and before C-wave integer-read removal, and correction of stale four-plan wording to the A–P series. This ADR does not implement that contract, production code, tests, plans, or executor waves.

## Plan-gate dispositions

- Focused SongUpsert ownership: the completed TASK-song-upsert-uses-storage-row-contract-A-typed-command.md at commit 9116f176 is canonical; stale unchecked phase2 A/B/C plans must be archive-annotated as superseded and must not reintroduce duplicate ownership.
- ML write-boundary overlap: keep the typed inference write-boundary plan gated until its implementation, discovery_worker incompatibility, and named CI/database checks are resolved. Row-mirror Plan L and embedding Plans B/D consume that boundary and do not reimplement it.
- list_songs_with_state: add typed read coverage after row-mirror Plans A/B semantic Song/mapper/hydration prerequisites and before C-wave integer-read removal. No integer fallback is acceptable.
- Four-plan framing: correct the stale row-mirror contract header to the actual A–P hard-cut set.
- Additional rebase hygiene: annotate the completed-but-pending stable-ID move plan for supersession and rebase stale ADR citations/docstrings, including the ambiguous P3-S7 reference, against ADR-048. These are downstream hygiene obligations, not new identity requirements.

## Scope guard

The typed state read is an ordering interlock only; its complete shape and consumer inventory belong to owning row-mirror plans. Do not create a new locator dataclass. Do not place executor-wave details in this ADR. The currently dead-but-allowlisted apply_detected_moves integration remains subject to a separate product decision.

## References

ADR-032 — Domain-Model Boundary: Persistence Returns Only Domain Objects, Never Storage Shapes
ADR-040 — PostgreSQL + pgvector Migration — Hard-Cut Replacement of ArangoDB
ADR-041 — Domain Dataclasses as the Persistence-Component Contract
ADR-046 — Allow Thin Persistence Intent-Facade Calls from Services and Workflows
ADR-047 — Application Semantics and Persistence Representation Boundary (including committed amendment adbb053f)
artifacts/designs/pending/DD-song-identity-decision-reconciliation.md
artifacts/designs/parts/song-row-mirror-leaks-into-domain/CONTRACTS.md
artifacts/designs/process/ADVERSARIAL-song-identity-decision-reconciliation.md
artifacts/logs/rnd-manager.log.jsonl#L178
