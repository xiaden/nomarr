# Observable Config and Dynamic Worker Scaling

## Execution Rounds

| Round | Plan | Description | Depends On |
|---|---|---|---|
| 1 | A | Worker lifecycle — per-worker stop events, add_workers/remove_workers | — |
| 2 | B | Config subscription mechanism + wiring tagger_worker_count | Round 1 |

## Execution Order

Round 1 → Round 2 (strict sequential — Plan B requires add/remove methods from Plan A)

## Files

| Plan | Primary Files |
|---|---|
| A | `nomarr/services/infrastructure/worker_system_svc.py`, `nomarr/services/infrastructure/workers/discovery_worker.py` |
| B | `nomarr/helpers/config_schema.py`, `nomarr/services/infrastructure/config_svc.py`, `nomarr/app.py` |
