# Plan L residual manifest and handoff (tracked clean-checkout fixture)

This tracked fixture carries only the non-sensitive classification vocabulary
that the Plan L static readers require. It contains no credentials, raw rows,
marker tokens, identifiers, commit hashes, absolute paths, or executed-CI claim.

## Classification rules

Every residual is assigned one of the contract categories:
`PERSISTENCE_PRIVATE`, `LOCATOR_BOUNDARY`, `HYDRATE_INBOUND_ONLY`,
`EXACT_ALLOWLIST`, `DEAD_ALLOWLISTED`, `EXTERNAL_OWNER`, or
`RELEASE_BLOCKING_DEFECT`. A resolver name is not an approval. No path-to-ID
conversion, alias, shim, dual path, stable identity, generic mood writer, or
caller transaction is authorized.

The current contract permits only the narrow inbound HydrateSongInput adapter; each other resolver needs owner, boundary, reason, positive test, non-propagation, removal condition. The locator wire is UUID-bearing nom1 and is never integer. No wrapper or alias added by L.

Owner routing: **M** (recovery, concurrency, partial failure), **N** (static
enforcement and CI wiring), **O** (security, redaction, provenance, rollback),
**P** (final adjudication).

## Evidence labels

- LOCAL_PASS: only for a command that actually ran and passed locally.
- LOCAL_UNAVAILABLE: required capability could not execute in this environment.
- CI_DEFERRED: required capability is wired to a named CI job but has not run.
- no local PASS is claimed for unavailable infrastructure.
