# GPU Health Monitor Regression Repair

**Status:** COMPLETE  
**Created:** 2025-01-21  
**Completed:** 2025-01-22  
**Severity:** Architectural violation  

---

## Executive Summary

The GPU health monitoring subsystem conflates two distinct concerns:

1. **Process liveness** (is the GPUHealthMonitor subprocess alive and responsive?)
2. **Resource product** (what are the current GPU/VRAM availability facts?)

The current implementation attempts to infer monitor liveness from DB timestamps, which is architecturally backwards. This document specifies the correct separation and the invariants that must hold.

---

## The Problem

### Current (Broken) Design

```
GPUHealthMonitor (subprocess)
    │
    ├── Writes probe results to DB with timestamps
    │       └── probe_time, last_check_at, etc.
    │
    └── info_svc.get_gpu_health()
            │
            └── Reads DB, computes staleness from timestamps
                    │
                    └── If stale → assumes monitor is dead/hung
```

**Why this is wrong:**

1. **Monotonic timestamps don't survive restarts** — Storing `internal_s()` in DB is meaningless after process restart; the new process has a different monotonic base.

2. **Wall-clock staleness is process supervision, not DB polling** — If you want to know if a subprocess is alive, check `Process.is_alive()` or use IPC heartbeats, not DB timestamp arithmetic.

3. **DB polling creates false coupling** — The API layer now "knows" about health thresholds, probe intervals, and staleness windows. This is process management logic leaking into the data layer.

4. **Recovery is impossible via this path** — If the monitor hangs, reading stale DB data tells you it's dead but provides no mechanism to restart it. The correct mechanism (HealthMonitorService) can actually take recovery action.

5. **Daemon processes die with parent** — `GPUHealthMonitor` is `daemon=True`. If parent survives but monitor dies, parent should restart it. If parent dies, container restarts everything. There is no scenario where "detect stale DB and report error" is the correct response.

---

## Separation of Concerns

### Health (Process Liveness)

**Owner:** HealthMonitorService  
**Mechanism:** Process registration + IPC pipe frames + EOF detection + startup timeout + recovery window  

The GPUHealthMonitor subprocess MUST be registered with HealthMonitorService like any other subprocess or worker. HealthMonitorService is the **sole authority** for determining:

- Is the monitor alive?
- Is the monitor responsive (heartbeat frames arriving)?
- Has the monitor crashed (EOF on pipe)?
- Should the monitor be restarted?

**No code may infer GPU monitor health from database contents.**

### Product (GPU Resource Snapshot)

**Owner:** GPUHealthMonitor subprocess  
**Storage:** Dedicated collection (e.g., `gpu_resources`)  
**Contents:** Pure resource facts with **no timestamps**  

The GPU resource snapshot represents the **current known state** of GPU resources. It is a product, not a health signal.

Example schema:

```python
# CORRECT: No timestamps
{
    "gpu_available": True,
    "vram_total_mb": 24576,
    "vram_free_mb": 20480,
    "gpu_count": 1,
    "driver_version": "535.104.05",
    "error_summary": None,  # Only populated if gpu_available=False
}
```

**Forbidden fields:**

- `probe_time`
- `last_check_at`
- `last_ok_at`
- `updated_at`
- Any timestamp that could be used for staleness inference

---

## Non-Negotiable Invariants

1. **GPUHealthMonitor subprocess IS registered with HealthMonitorService** for liveness/IPC monitoring.

2. **HealthMonitorService is the ONLY authority** for dead/unhealthy/recovering decisions regarding the GPU monitor.

3. **GPU resource data may be persisted**, but ONLY as product in its own collection (not conflated with health).

4. **GPU product persistence must NOT include timestamps** to prevent any code from attempting DB-based staleness inference.

5. **No code or plan may compute GPU monitor "health" from DB** — not staleness checks, not "last update was N seconds ago", nothing.

6. **"Freshness" is a HealthMonitor concept** — If you need to know if GPU data is fresh, ask HealthMonitorService if the GPU monitor subprocess is alive and healthy. The DB is not a freshness signal.

---

## Correct Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     HealthMonitorService                        │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐ │
│  │ Worker A        │  │ Worker B        │  │ GPUHealthMonitor│ │
│  │ (registered)    │  │ (registered)    │  │ (registered)    │ │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘ │
│           │                    │                    │          │
│           └────────────────────┴────────────────────┘          │
│                         IPC pipes + heartbeats                  │
│                                                                 │
│  Responsibilities:                                              │
│  - Detect subprocess death (EOF)                                │
│  - Detect unresponsive subprocess (heartbeat timeout)           │
│  - Trigger restart/recovery                                     │
│  - Report component health to API                               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ (health queries go here)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        info_svc                                 │
│                                                                 │
│  get_gpu_monitor_health() → asks HealthMonitorService           │
│  get_gpu_resources()      → reads gpu_resources from DB         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ (product writes go here)
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Database                                   │
│                                                                 │
│  gpu_resources collection:                                      │
│  {                                                              │
│      "gpu_available": true,                                     │
│      "vram_total_mb": 24576,                                    │
│      "vram_free_mb": 20480,                                     │
│      "gpu_count": 1,                                            │
│      "driver_version": "535.104.05",                            │
│      "error_summary": null                                      │
│  }                                                              │
│                                                                 │
│  NO TIMESTAMPS. Product only.                                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Required Code Changes

### 1. Remove DB-based staleness checking

Delete or deprecate:
- `check_gpu_health_staleness()` in `gpu_monitor_comp.py`
- `should_run_gpu_probe()` staleness logic in `gpu_probe_comp.py`
- All staleness threshold constants (`GPU_HEALTH_STALENESS_THRESHOLD_SECONDS`)
- All timestamp fields from GPU health/resource DB writes

### 2. Register GPUHealthMonitor with HealthMonitorService

The monitor must:
- Register on startup with a unique component ID
- Send periodic heartbeat frames via IPC pipe
- Be restartable by HealthMonitorService on failure

### 3. Split info_svc GPU methods

- `get_gpu_monitor_health()` → Queries HealthMonitorService for subprocess liveness
- `get_gpu_resources()` → Reads GPU resource snapshot from DB (no staleness check)

### 4. Update GPU resource snapshot schema

Remove all timestamp fields. The snapshot is a point-in-time product. If you need to know when it was captured, ask HealthMonitorService when the monitor last reported healthy.

### 5. Update API response models

- `GPUHealthResponse.last_check_at` → Remove or repurpose
- Add `gpu_monitor_healthy: bool` from HealthMonitorService
- Keep resource fields (`available`, `vram_free_mb`, etc.) from DB snapshot

---

## Migration Notes

This is a breaking change to the GPU health API response. Acceptable per pre-alpha policy.

Clients that previously relied on `last_check_at` for freshness must instead check `gpu_monitor_healthy` to determine if the data source is alive.

---

## Terminology Corrections

| Old (Wrong)                  | New (Correct)                          |
|------------------------------|----------------------------------------|
| GPU health DB                | GPU resource snapshot                  |
| Staleness check              | HealthMonitor liveness query           |
| `probe_time`                 | (removed - no timestamps in snapshot)  |
| `last_check_at`              | (removed - no timestamps in snapshot)  |
| "Data is stale"              | "GPU monitor is unhealthy/dead"        |
| "Freshness threshold"        | "HealthMonitor heartbeat timeout"      |

---

## Acceptance Criteria

- [x] `GPUHealthMonitor` registered with `HealthMonitorService`
- [x] `check_gpu_health_staleness()` deleted
- [x] `GPU_HEALTH_STALENESS_THRESHOLD_SECONDS` deleted
- [x] GPU resource snapshot schema contains zero timestamp fields
- [x] `info_svc.get_gpu_health()` does NOT read timestamps from DB
- [x] `info_svc.get_gpu_health()` queries HealthMonitorService for monitor liveness
- [x] API `GPUHealthResponse` exposes `monitor_healthy` from HealthMonitorService
- [x] No code path computes "is GPU data fresh" from DB timestamps

---

## References

- [HealthMonitorService architecture](./health.md)
- [Worker lifecycle and registration](./workers.md)
- [StateBroker design](./statebroker.md)
