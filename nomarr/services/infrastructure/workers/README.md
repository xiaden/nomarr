# Worker Subprocess

Discovery-based ML processing worker that runs as a separate OS process, claiming and processing audio files from the database.

## Responsibilities

- Discover unprocessed files from `library_files` collection
- Claim files atomically via `worker_claims` to prevent duplicate processing
- Execute the full ML pipeline (`process_file_workflow`) per file
- Send health heartbeats to the parent process via pipe
- Handle idle-time vector promotion (hot→cold) when no files pending

## Key Modules

| Module | Purpose |
|--------|---------|
| `discovery_worker.py` | `DiscoveryWorker` (multiprocessing.Process) — main worker loop, health frames, ONNX cache management, deferred DB writes |

## Patterns

- **Discovery loop**: Query → claim → process → mark tagged → release claim → repeat
- **Deferred writes**: DB writes execute on a background thread to overlap with the next file's ML inference
- **Health frames**: Periodic `HEALTH|` prefixed messages sent via pipe to `HealthMonitorService`
- **Crash recovery**: Stale claims auto-expire when worker heartbeat goes missing; files become re-discoverable
- **Memory management**: `malloc_trim()` after each file + on ONNX cache eviction to prevent heap bloat
- **Idle promotion**: When no files are pending, runs `idle_promotion_vectors_workflow` to promote hot vectors

## Architecture Rules

> **Services MUST NOT call persistence directly.** The worker delegates ML processing to `workflows/processing/process_file_wf` and file sync to `workflows/library/sync_file_to_library_wf`. Claim operations use the `Database` handle passed at construction.

## Dependencies

- **Managed by**: `WorkerSystemService` (start/stop, restart on failure)
- **Monitored by**: `HealthMonitorService` (via pipe-based heartbeats)
- **Calls**: `workflows/processing/process_file_wf`, `workflows/library/sync_file_to_library_wf`, `workflows/platform/idle_promotion_vectors_wf`
