# Health AQL Regression Analysis - Worker Crash Handling

## Problem Statement

During the SQLite → ArangoDB migration, the `mark_crashed()` method signature was simplified from:

```python
# SQLite (health_sql.py)
def mark_crashed(self, component: str, exit_code: int, metadata: str | None = None) -> None
```

to:

```python
# ArangoDB (health_aql.py)
def mark_crashed(self, component_id: str, error: str | None = None) -> None
```

This represents a **functional regression** that loses critical diagnostic data needed for worker crash debugging and job recovery.

## What Was Lost

### 1. Exit Code (Critical)
**SQLite version stored:**
- `exit_code: INTEGER` - The exact exit code from the crashed process
- Custom exit codes defined in worker_system_svc.py:
  - `EXIT_CODE_UNKNOWN_CRASH = -1`
  - `EXIT_CODE_HEARTBEAT_TIMEOUT = -2`
  - `EXIT_CODE_INVALID_HEARTBEAT = -3`
  - Worker's actual `exitcode` from multiprocessing.Process

**Impact:**
- Cannot distinguish between different crash types
- Cannot detect patterns (e.g., "all crashes are exit code 137 = OOM killer")
- Diagnostic information is reduced to a string concatenation: `"Process terminated unexpectedly with exit code {exit_code}"`

### 2. Metadata Field (Critical for Job Recovery)
**SQLite version stored:**
- `metadata: TEXT` - JSON string with crash context
- Used for storing interrupted job information
- Example: `{"current_job": 12345, "crash_reason": "heartbeat_timeout"}`

**Impact:**
- Job recovery relies on parsing `current_job` from health record
- `_schedule_restart()` in worker_system_svc.py calls `health.get("current_job")` to requeue interrupted jobs
- The metadata field provided structured storage for this critical information

## Current Schema Comparison

### SQLite Health Table (health_sql.py)
```sql
CREATE TABLE health (
    component TEXT PRIMARY KEY,
    last_heartbeat INTEGER NOT NULL,
    status TEXT NOT NULL,
    restart_count INTEGER DEFAULT 0,
    last_restart INTEGER,
    pid INTEGER,
    current_job INTEGER,        -- Used for job recovery
    exit_code INTEGER,           -- Stores actual exit code
    metadata TEXT                -- JSON string for extra context
)
```

### ArangoDB Health Collection (health_aql.py)
Current schema (inferred from operations):
```javascript
{
    _key: string,              // Auto-generated
    component_id: string,      // PRIMARY KEY equivalent
    component_type: string,
    status: string,
    last_heartbeat: number,
    restart_count: number,
    last_restart: number,
    pid: number,
    current_job: string,       // EXISTS - used by _schedule_restart
    error: string,             // Replaces both exit_code and metadata
    // MISSING: exit_code (integer)
    // MISSING: metadata (structured JSON)
}
```

## Impact on Worker System

### Current Call Sites
From worker_system_svc.py lines 370-430:

```python
# Line 373: Invalid heartbeat
self.db.health.mark_crashed(
    component_id=component_id,
    error="Invalid heartbeat timestamp",  # Lost: EXIT_CODE_INVALID_HEARTBEAT
)

# Line 406: Stale heartbeat
self.db.health.mark_crashed(
    component_id=component_id,
    error=f"Heartbeat stale for {heartbeat_age}ms...",  # Lost: EXIT_CODE_HEARTBEAT_TIMEOUT
)

# Line 429: Process died
exit_code = worker.exitcode if worker.exitcode is not None else EXIT_CODE_UNKNOWN_CRASH
self.db.health.mark_crashed(
    component_id=component_id,
    error=f"Process terminated unexpectedly with exit code {exit_code}",  # Lost: actual exit_code as integer
)
```

### Job Recovery Impact
From worker_system_svc.py `_schedule_restart()` line 479:
```python
current_job_raw = health.get("current_job") if health else None
# ...
if current_job is not None:
    requeued = requeue_crashed_job(self.db, queue_type, current_job)
```

The `current_job` field **exists** in the schema and is populated by `update_heartbeat()`, so job recovery is NOT broken. However, the metadata field would have provided structured storage for additional crash context.

## Recommended Fix

### Option 1: Add Missing Fields (Recommended)

Update `mark_crashed()` to restore full functionality:

```python
def mark_crashed(
    self, 
    component_id: str, 
    exit_code: int | None = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None
) -> None:
    """Mark component as crashed with full diagnostic context.
    
    Args:
        component_id: Component identifier
        exit_code: Process exit code (custom codes: -1=unknown, -2=heartbeat_timeout, -3=invalid_heartbeat)
        error: Human-readable error message
        metadata: Structured crash context (e.g., {"crash_type": "oom", "job_id": "123"})
    """
    import json
    
    update_data: dict[str, Any] = {
        "status": "crashed",
        "last_heartbeat": now_ms(),
    }
    
    if exit_code is not None:
        update_data["exit_code"] = exit_code
    if error is not None:
        update_data["error"] = error
    if metadata is not None:
        update_data["metadata"] = json.dumps(metadata)
    
    self.db.aql.execute(
        """
        FOR health IN health
            FILTER health.component_id == @component_id
            UPDATE health WITH @update_data IN health
        """,
        bind_vars=cast(dict[str, Any], {
            "component_id": component_id,
            "update_data": update_data,
        }),
    )
```

**Update call sites in worker_system_svc.py:**

```python
# Invalid heartbeat (line 373)
self.db.health.mark_crashed(
    component_id=component_id,
    exit_code=EXIT_CODE_INVALID_HEARTBEAT,
    error="Invalid heartbeat timestamp",
)

# Stale heartbeat (line 406)
self.db.health.mark_crashed(
    component_id=component_id,
    exit_code=EXIT_CODE_HEARTBEAT_TIMEOUT,
    error=f"Heartbeat stale for {heartbeat_age}ms (threshold={stale_threshold}ms, cache_loaded={cache_loaded})",
)

# Process died (line 429)
self.db.health.mark_crashed(
    component_id=component_id,
    exit_code=exit_code,
    error=f"Process terminated unexpectedly with exit code {exit_code}",
)
```

### Option 2: Use Metadata Only (Alternative)

Store all diagnostic data in a structured metadata field:

```python
def mark_crashed(
    self, 
    component_id: str, 
    metadata: dict[str, Any]
) -> None:
    """Mark component as crashed.
    
    Args:
        component_id: Component identifier
        metadata: Crash context including exit_code, error, crash_type, etc.
    """
    import json
    
    self.db.aql.execute(
        """
        FOR health IN health
            FILTER health.component_id == @component_id
            UPDATE health WITH {
                status: 'crashed',
                last_heartbeat: @timestamp,
                metadata: @metadata
            } IN health
        """,
        bind_vars=cast(dict[str, Any], {
            "component_id": component_id,
            "timestamp": now_ms(),
            "metadata": json.dumps(metadata),
        }),
    )
```

This approach is more flexible but makes querying by exit_code harder (would require JSON parsing in AQL).

## mark_failed() Regression

Similar issue exists with `mark_failed()`:

**SQLite:**
```python
def mark_failed(self, component: str, metadata: str) -> None
```

**ArangoDB:**
```python
def mark_failed(self, component_id: str, error: str | None = None) -> None
```

The metadata field was used to store failure reasons like "restart limit exceeded" with structured context. Should be similarly restored.

## Timeline for Fix

1. **Phase 1 (Immediate):** Add `exit_code` and `metadata` fields to `mark_crashed()` and `mark_failed()`
2. **Phase 2:** Update all call sites in worker_system_svc.py to pass structured data
3. **Phase 3:** Verify health monitoring dashboard/API uses exit_code for crash analytics
4. **Phase 4:** Add integration test to verify exit codes are persisted and queryable

## Validation

After fix, verify:
1. Custom exit codes (-1, -2, -3) are stored correctly
2. Worker `exitcode` from multiprocessing is captured
3. `current_job` recovery still works (already working)
4. Health API returns exit_code and metadata for debugging
5. Can query crashes by exit_code: `FOR h IN health FILTER h.exit_code == -2 RETURN h`

## Risk Assessment

**Current Impact:** Medium
- Job recovery still works (current_job field exists)
- Crash detection still works (status='crashed' is set)
- **Lost:** Exit code analytics (cannot detect OOM patterns, signal kills, etc.)
- **Lost:** Structured crash metadata (reduces debugging capability)

**Fix Complexity:** Low
- Simple field additions to AQL update
- Call site updates are mechanical
- No schema migration needed (ArangoDB is schemaless, fields can be added on write)

## Recommendation

**Implement Option 1 immediately.** The regression reduces observability and makes it harder to diagnose production crashes. Since ArangoDB is schemaless, we can add these fields without a migration by simply updating the code.
