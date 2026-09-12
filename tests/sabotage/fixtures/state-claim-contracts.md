# Song state/claim contracts (tracked clean-checkout fixture)

This tracked fixture carries only the non-sensitive contract vocabulary that the
Plan H contract reader requires. It contains no credentials, raw rows, marker
tokens, identifiers, commit hashes, absolute paths, or executed-CI claim.

## Broad resolver boundary

Hydration is locator-addressed and payload-only: `HydrateSongInput` carries no
`song_id` integer, so no inbound integer adapter is retained.

Retaining `resolve_song_identity`/`resolve_song_identities` or any other integer
identity crossing requires an exact L/N/P allowlist naming owner, boundary,
reason, positive test, non-propagation assertion, and removal condition; a
symbol name alone is never approval.
