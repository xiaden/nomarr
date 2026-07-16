# Platform

Database bootstrap, GPU monitoring, migration execution, and resource tracking.

## Responsibilities

- Wait for PostgreSQL availability and provision database/user on first run
- Ensure baseline schema (tables, indexes) exists on startup
- Discover, validate, and apply forward-only database migrations in semver order
- Probe GPU availability and monitor VRAM/RAM resource headroom
- Run continuous GPU health monitoring in an isolated process

## Key Modules

 | Module | Purpose |
 | -------- | ---------- |
 | `migration_runner_comp` | Discover migration modules, validate version chains, apply pending migrations with two-phase recording, detect schema version mismatches |
 | `gpu_probe_comp` | Single-shot `nvidia-smi` subprocess check — fail-fast GPU availability detection without importing CUDA libraries |
 | `gpu_monitor_comp` | `GPUHealthMonitor` (multiprocessing.Process) — continuous GPU probing with heartbeat frames sent to HealthMonitorService |
 | `resource_monitor_comp` | VRAM/RAM telemetry with TTL caching, budget-based headroom checks, cgroup-aware RAM detection for Docker containers |

## Patterns

- **Frozen baseline + migrations:** `ensure_schema` is never edited directly. New schema changes go in migration files only; the baseline is updated only during consolidation.
- **Process isolation for GPU:** `GPUHealthMonitor` runs in a separate process so kernel-level driver deadlocks cannot propagate to the main application.
- **Two-phase migration recording:** Migrations are recorded as `in_progress` before execution and `applied` after — interrupted migrations are automatically retried on next startup.

## Dependencies

- **Upstream:** Called by startup sequence and ML resource management
- **Downstream:** Calls persistence directly (PostgreSQL for provisioning, app DB for schema/migrations)
- **External:** `psutil` (RAM), `nvidia-smi` subprocess (GPU)
