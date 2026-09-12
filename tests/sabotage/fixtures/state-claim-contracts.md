# Song state/claim contracts (tracked clean-checkout fixture)

This tracked fixture carries only the non-sensitive contract vocabulary that the
Plan H contract reader requires. It contains no credentials, raw rows, marker
tokens, identifiers, commit hashes, absolute paths, or executed-CI claim.

## Broad resolver boundary

The only retained provisional inbound integer adapter is the narrow
`HydrateSongInput(song_id: int, ...)` hydration adapter.

Retaining `resolve_song_identity`/`resolve_song_identities` or any other broad
resolver requires an exact L/N/P allowlist naming owner, boundary, reason,
positive test, non-propagation assertion, and removal condition; a symbol name
alone is never approval.
