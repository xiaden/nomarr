# Song row mirror contracts (tracked clean-checkout fixture)

This tracked fixture carries only the non-sensitive contract vocabulary that the
Plan L contract reader requires. It contains no credentials, raw rows, marker
tokens, identifiers, commit hashes, absolute paths, or executed-CI claim.

## Identity crossings and adapters

Hydration is locator-addressed end-to-end: the public hydration intent accepts
`SongIdentity` and its payload separately, while persistence resolves the
locator to its private row key. No generated integer identity crosses the
hydration boundary or appears in carriers, logs, retries, or wires.
All other integer identity crossings are prohibited, including
`resolve_song_identity` and `resolve_song_identities`, unless an
exact L/N/P allowlist names owner, boundary, reason, test evidence,
non-propagation assertion, and removal condition.

The opaque SongLocator wire representation is nom1 plus unpadded URL-safe base64
of canonical compact {library_uuid, path}. The library_uuid value is the
concrete `libraries.library_uuid` value, never a generated integer id, and the
path is library-relative normalized.
