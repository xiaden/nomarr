# Plan O security, provenance, and rollback evidence (tracked clean-checkout fixture)

This tracked fixture carries only the non-sensitive contract vocabulary that the
Plan O static readers require. It contains no credentials, raw rows, marker
tokens, identifiers, commit hashes, absolute paths, or executed-CI claim.

## Provenance and protected-file baseline

The execution record states that the worktree was **not** clean during
execution, that the protected set was preserved without destructive change, and
that No commit was created. Real execution HEAD values are checked only through
the guarded optional path when the original ignored document is present; they
are intentionally absent from this tracked fixture.

## Security and redaction disposition

The outward Song address is the opaque nom1 locator token encoding canonical
compact {library_uuid, path}. The library_uuid component is immutable; songs.id,
integer libraries.id, library_id, SQL, sessions, constraints, and raw rows
remain persistence-private. Natural library-name routes remain deliberate
library CRUD identity and are not SongLocator payloads.

Authorized missing, stale, unauthorized, and unknown-commit outcomes are coarse
and typed. MISSING_LOCATOR does not disclose an ID or prove existence to an
unauthorized caller. Presentation responses, exception text, status/body/headers,
metrics, and logs must not disclose normalized or absolute paths, UUIDs,
generated IDs, SQL/session/constraint details, raw rows, tag payloads,
credentials, or sensitive metadata.

Hydration is locator-addressed and payload-only: HydrateSongInput carries no
song_id integer, so no inbound integer adapter is retained.
Every other integer identity crossing is prohibited, including
resolve_song_identity and resolve_song_identities.
No broad resolver allowlist is invented here.

## Rollback and recovery runbook (non-destructive)

1. Quiesce callers and workers.
2. Capture the exact HEAD, worktree status, and protected-file list.
3. Validate liveness and classify each retained claim.
4. Restore the complete A–P wave coherently.
5. Resume supported recovery: a row-committed/state-init-failed add is
   recorded-recoverable; an ambiguous commit requires authorized readback and
   never blind completion.
6. Record partial operations honestly: if DB mood committed and filesystem writeback failed, retain the typed partial outcome and schedule reconciliation; do not claim full completion from readback.

Forbidden during rollback: git reset, git checkout, git restore, git stash,
git clean, destructive overwrite of unrelated changes, caller-managed
transactions, row aliases, integer bridges, or any operation that erases
provenance.

## Evidence labels and handoff to P

- LOCAL_PASS: only for a command that actually ran and passed locally.
- LOCAL_UNAVAILABLE: local capability could not execute after feasible setup.
- CI_DEFERRED: wired to the named database-tests job but not run here.
- CI_PASS: reserved for an actual workflow run; none is claimed here.

### Exact handoff to P

Missing mood owner evidence remains BLOCKED for P rather than downgraded.
