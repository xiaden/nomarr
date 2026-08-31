# Worker Components

Work discovery, claiming, and crash recovery for the ML tagging worker fleet.

## Responsibilities

- Discover unprocessed files and claim them for processing
- Prevent duplicate work via single-active-claim-per-song enforcement (persistence-internal unique claim key)
- Clean up stale claims from inactive workers
- Decide whether to restart or permanently fail crashed workers
- Calculate exponential backoff delays for restarts

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `worker_discovery_comp` | File discovery (needs_tagging=1, is_valid=1), atomic claim/release, stale claim cleanup, combined discover-and-claim |
 | `worker_crash_comp` | Two-tier restart limiting (short window + lifetime cap), exponential backoff (1s–60s), `RestartDecision` with action/reason |

## Patterns

- **Claim-based work distribution:** Workers discover the next song via domain intent, then atomically claim it with a `WorkerClaim` value through `db.app.add_claim`. A single-active-claim-per-song policy (enforced by a persistence-internal unique claim key on song-identity-encoded keys) prevents duplicate claims without distributed locks.
- **Two-tier crash limiting:** Short window (5 restarts in 5 minutes) catches rapid crashes (OOM, bad config). Lifetime cap (20 total restarts) catches slow thrashing (killed every 10 minutes from resource pressure).
- **Stale claim cleanup:** One `db.app.remove_claims(ClaimRemovalRequest(...))` intent selects inactive workers (stale heartbeat) plus missing/completed/errored songs, and preserves active pending reconcile claims.

## Dependencies

- **Upstream:** Called by `services/` (worker system service)
- **Downstream:** Access via `db.app` / `db.library` intent namespaces only (never Tier 1/Tier 2 persistence internals)
