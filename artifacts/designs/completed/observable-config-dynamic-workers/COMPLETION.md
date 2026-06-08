# Completion — Observable Config and Dynamic Worker Scaling

## Execution Summary

| Plan | Status | Review Rounds | Fix Rounds |
|---|---|---|---|
| A: Worker Lifecycle | DONE | 1 | 1 (QA round 2) |
| B: Config Subscription + Wiring | DONE | 3 | 2 (planning gap + coroutine type) |

## Key Decisions

| Plan | Decision | Rationale |
|---|---|---|
| A | Per-worker `Event()` + `_shutting_down` flag | Workers must be independently stoppable for scale-down |
| A | `remove_workers` uses `stop()` + `join(2.0)` not `terminate()` | Workers drain naturally, preserving the plan's design intent |
| B | `Coroutine` type instead of `Awaitable` | `asyncio.create_task()` requires concrete coroutines |
| B | Added `get_worker_count()` public method | Avoids direct access to private `_workers` list |

## Files Modified

| Layer | Files |
|---|---|
| Helpers | `nomarr/helpers/config_schema.py` |
| Services | `nomarr/services/infrastructure/config_svc.py`, `nomarr/services/infrastructure/worker_system_svc.py` |
| Composition Root | `nomarr/app.py` |
| Tests | `tests/unit/services/infrastructure/test_config_svc.py`, `tests/unit/services/infrastructure/test_worker_system_svc_restart.py` |

## Final Lint Status

All edited files pass `lint_project_backend` with zero errors.
