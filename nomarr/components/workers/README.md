# Worker Components

Work discovery, claiming, and crash recovery for the ML tagging worker fleet.

## Responsibilities

- Discover unprocessed files and claim them for processing
- Prevent duplicate work via deterministic ArangoDB document key uniqueness
- Clean up stale claims from inactive workers
- Decide whether to restart or permanently fail crashed workers
- Calculate exponential backoff delays for restarts

## Key Modules

| Module | Purpose |
|--------|----------|
| `worker_discovery_comp` | File discovery (needs_tagging=1, is_valid=1), atomic claim/release, stale claim cleanup, combined discover-and-claim |
| `worker_crash_comp` | Two-tier restart limiting (short window + lifetime cap), exponential backoff (1s–60s), `RestartDecision` with action/reason |

## Patterns

- **Claim-based work distribution:** Workers discover the next file via deterministic `_key` ordering, then atomically claim it. ArangoDB key uniqueness prevents duplicate claims without distributed locks.
- **Two-tier crash limiting:** Short window (5 restarts in 5 minutes) catches rapid crashes (OOM, bad config). Lifetime cap (20 total restarts) catches slow thrashing (killed every 10 minutes from resource pressure).
- **Stale claim cleanup:** Runs three operations: remove claims from workers with stale heartbeats, claims for already-tagged files, and claims for files no longer needing processing.

## Dependencies

- **Upstream:** Called by `services/` (worker system service)
- **Downstream:** Calls `persistence/` directly for claim and file queries
