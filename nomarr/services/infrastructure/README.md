# Infrastructure Services

Platform-level services that manage configuration, workers, health monitoring, ML model discovery, file watching, background tasks, authentication, and system information.

## Responsibilities

- Application configuration lifecycle (bootstrap → cache → DB persistence)
- Worker process management with GPU-adaptive admission control
- Component health monitoring via pipe-based heartbeats
- ML model and backbone discovery
- Filesystem watching (event-based and polling modes)
- Background task execution and tracking
- API key, password, and session management
- System info, health status, and GPU monitoring
- Calibration bundle download and verification

## Key Modules

| Module | Purpose |
|--------|---------|
| `config_svc.py` | `ConfigService` — defaults→YAML→ENV→DB bootstrap, write-through cache, web-editable subset |
| `worker_system_svc.py` | `WorkerSystemService` — discovery worker pool, GPU admission control, tier selection, auto-restart |
| `health_monitor_svc.py` | `HealthMonitorService` — pipe-based health frames, startup/staleness/recovery deadlines, status callbacks |
| `ml_svc.py` | `MLService` — backbone listing, head discovery, ONNX model registry, VRAM measurement management |
| `file_watcher_svc.py` | `FileWatcherService` — per-library watchers (event/poll modes), debounced scan triggers |
| `background_tasks_svc.py` | `BackgroundTaskService` — thread-based task execution with status tracking and eviction |
| `cli_bootstrap_svc.py` | CLI factory functions — `get_database()`, `get_keys_service()`, `get_config_service()`, `get_metadata_service()` |
| `keys_svc.py` | `KeyManagementService` — API keys, bcrypt passwords, session tokens, write-through session cache |
| `info_svc.py` | `InfoService` — system info, health status, public info, GPU monitor subprocess lifecycle |
| `calibration_download_svc.py` | Calibration bundle download, missing-check, and availability verification (stub) |
| `workers/` | Worker subprocess implementations — see subfolder README |

## Patterns

- **Config bootstrap**: defaults → YAML overlay → ENV overrides → seed to DB → cache from DB
- **Admission control**: GPU gating → capacity probe → tier selection → worker count calculation
- **Health monitoring**: Pipes for heartbeat transport, consolidated monitor thread, handler callbacks for domain restart decisions
- **Session caching**: Write-through (memory + DB), lazy load on startup, periodic cleanup

## Architecture Rules

> **Services MUST NOT call persistence directly.** Database access flows through workflows and components. The `cli_bootstrap_svc` factory functions are the only exception — they construct service instances for CLI entry points.

## Dependencies

- **Called by**: `app.py` (startup wiring), `interfaces/` endpoints, domain services
- **Calls**: `workflows/platform/*`, `workflows/processing/*`, `components/platform/*`
- **Receives**: `Database`, config dataclasses, peer infrastructure services
