# StateBroker & SSE

**Audience:** Developers working on real-time UI updates, SSE implementation, or event broadcasting.

The StateBroker manages real-time state distribution to web clients via Server-Sent Events (SSE). It polls the database for state changes and broadcasts updates to subscribed clients.

---

## Architecture Overview

### Data Flow

```
Workers → Database (health/queue tables)
            ↓ (polling every 1-2s)
      StateBroker
            ↓ (broadcast)
       SSE Topics
            ↓
     Web UI Clients (EventSource)
```

### Why Database-Based IPC?

Worker processes use **database polling** for inter-process communication because:

1. **Multiprocessing Safety** - ArangoDB handles concurrent access via MVCC (no locking conflicts)
2. **No Shared Memory** - Avoids complexities of `multiprocessing.Queue` or shared state
3. **Crash Resilience** - State persists across worker restarts
4. **Debuggability** - All state visible in database collections
5. **Simplicity** - No message passing protocols or serialization

**Trade-off:** Slight latency (~1-2 seconds) acceptable for monitoring UI.

---

## State DTOs

StateBroker uses four typed DTOs for internal state management (defined in `helpers/dto/events_state_dto.py`):

### 1. QueueState

Represents queue statistics (pending, running, completed jobs).

**Structure:**
```python
@dataclass
class QueueState:
    queue_type: str | None  # None=global, "tag"/"library"/"calibration"=specific
    pending: int
    running: int
    completed: int
    avg_time: float         # Average processing time (seconds)
    eta: float              # Estimated time to completion (seconds)
```

**SSE Topics:**
- `queue:status` - Global aggregate (all queues combined)
- `queue:tag:status` - Tag queue only
- `queue:library:status` - Library scan queue
- `queue:calibration:status` - Calibration queue
- `queue:*:status` - Subscribe to all queue updates (wildcard)

**Example Event:**
```
event: queue:status
data: {"queue_type": null, "pending": 10, "running": 1, "completed": 245, "avg_time": 12.5, "eta": 125.0}
```

---

### 2. JobState

Represents individual job state changes.

**Structure:**
```python
@dataclass
class JobState:
    id: int
    path: str | None
    status: str             # "pending", "running", "done", "error"
    error: str | None
    results: dict[str, Any] | None
```

**SSE Topic:**
- `queue:jobs` - All job state changes

**Example Event:**
```
event: queue:jobs
data: {"id": 123, "path": "/music/Track.mp3", "status": "done", "error": null, "results": {...}}
```

**Use Cases:**
- Real-time job progress updates
- Error notifications
- Job completion detection

---

### 3. WorkerState

Represents worker process health and current activity.

**Structure:**
```python
@dataclass
class WorkerState:
    component: str          # Format: "worker:{queue_type}:{id}"
    id: int | None          # Parsed worker ID (0, 1, 2, etc.)
    queue_type: str | None  # "tag", "library", "calibration"
    status: str             # "starting", "healthy", "stopping", "crashed", "failed"
    pid: int | None         # Process ID
    current_job: int | None # Job ID if processing, None if idle
```

**SSE Topics:**
- `worker:tag:0:status` - Specific tag worker
- `worker:library:0:status` - Specific library worker
- `worker:calibration:0:status` - Specific calibration worker
- `worker:tag:*:status` - All tag workers (wildcard)
- `worker:*:status` - All workers across all types (wildcard)

**Example Event:**
```
event: worker:tag:0:status
data: {"component": "worker:tag:0", "id": 0, "queue_type": "tag", "status": "healthy", "pid": 1234, "current_job": 123}
```

**Use Cases:**
- Worker health monitoring
- Detecting worker crashes/failures
- Displaying current processing activity
- Pause/resume state feedback

---

### 4. SystemHealthState

Represents overall system health.

**Structure:**
```python
@dataclass
class SystemHealthState:
    status: str             # "healthy", "degraded", "error"
    errors: list[str]       # Error messages if status != "healthy"
```

**SSE Topic:**
- `system:health` - System-wide health status

**Example Event:**
```
event: system:health
data: {"status": "healthy", "errors": []}
```

**Use Cases:**
- Dashboard health indicators
- Alert triggers
- System-wide error display

---

## SSE Topic Hierarchy

### Topic Naming Convention

```
{domain}:{scope}:{detail}:{event}
```

Examples:
- `queue:status` - Queue domain, status event
- `queue:tag:status` - Queue domain, tag scope, status event
- `worker:tag:0:status` - Worker domain, tag scope, worker 0, status event

### Wildcard Support

Subscribe to multiple topics with wildcards (`*`):

```javascript
// All queue types
eventSource.addEventListener('queue:*:status', handler);

// All workers
eventSource.addEventListener('worker:*:status', handler);

// All tag workers
eventSource.addEventListener('worker:tag:*:status', handler);
```

### Topic Hierarchy

```
queue:status                    # Global aggregate
├─ queue:tag:status            # Tag queue
├─ queue:library:status        # Library queue
└─ queue:calibration:status    # Calibration queue

queue:jobs                      # Job state changes

worker:tag:0:status            # Tag worker 0
worker:library:0:status        # Library worker 0
worker:calibration:0:status    # Calibration worker 0

worker:*:status                # All workers (wildcard)

system:health                  # System health
```

---

## StateBroker Implementation

### Polling Loop

StateBroker runs a background task that:

1. Polls database tables every **1-2 seconds**:
   - `health` table for worker states
   - Queue tables for job counts and statistics
   - `meta` table for system configuration
2. Compares new state to previous snapshot
3. Broadcasts changes to SSE clients on relevant topics
4. Updates internal snapshot

**Why Polling?**
- Simple, predictable behavior
- No complex pub/sub infrastructure
- State persists in database (survives restarts)
- 1-2s latency acceptable for monitoring UI

### State Snapshot

StateBroker maintains an internal snapshot to detect changes:

```python
{
    "queue:status": QueueState(...),
    "queue:tag:status": QueueState(queue_type="tag", ...),
    "worker:tag:0:status": WorkerState(component="worker:tag:0", ...),
    "system:health": SystemHealthState(...)
}
```

**Change Detection:**
- Compare new state to snapshot
- Broadcast only if values changed
- Update snapshot with new state

This reduces unnecessary SSE traffic.

---

## SSE Client Implementation

### JavaScript Example

```javascript
// Initialize SSE connection with authentication
const token = localStorage.getItem('session_token');
const eventSource = new EventSource('/api/web/events/status', {
  headers: { 'Authorization': `Bearer ${token}` }
});

// Handle connection events
eventSource.onopen = () => {
  console.log('SSE connected');
};

eventSource.onerror = (error) => {
  console.error('SSE error:', error);
  // Auto-reconnect handled by EventSource
};

// Subscribe to queue status updates
eventSource.addEventListener('queue:status', (event) => {
  const state = JSON.parse(event.data);
  updateQueueUI(state);
});

// Subscribe to worker status updates (wildcard)
eventSource.addEventListener('worker:*:status', (event) => {
  const worker = JSON.parse(event.data);
  updateWorkerUI(worker);
});

// Subscribe to job updates
eventSource.addEventListener('queue:jobs', (event) => {
  const job = JSON.parse(event.data);
  updateJobUI(job);
});

// Subscribe to system health
eventSource.addEventListener('system:health', (event) => {
  const health = JSON.parse(event.data);
  updateHealthIndicator(health);
});

// Cleanup on page unload
window.addEventListener('beforeunload', () => {
  eventSource.close();
});
```

### React Hook Example

```typescript
import { useEffect, useState } from 'react';

interface QueueState {
  queue_type: string | null;
  pending: number;
  running: number;
  completed: number;
  avg_time: number;
  eta: number;
}

export function useQueueStatus() {
  const [queueState, setQueueState] = useState<QueueState | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('session_token');
    const eventSource = new EventSource('/api/web/events/status', {
      headers: { 'Authorization': `Bearer ${token}` }
    });

    eventSource.addEventListener('queue:status', (event) => {
      const state = JSON.parse(event.data) as QueueState;
      setQueueState(state);
    });

    eventSource.onerror = () => {
      console.error('SSE connection error');
    };

    return () => {
      eventSource.close();
    };
  }, []);

  return queueState;
}
```

---

## Broadcasting Semantics

### Snapshot + Incremental Updates

StateBroker sends:

1. **Initial Snapshot** - On client connection, send current state for all topics
2. **Incremental Updates** - On state changes, send only changed values

**Example Connection Flow:**
```
Client connects
  → Server sends: queue:status (current state)
  → Server sends: worker:tag:0:status (current state)
  → Server sends: system:health (current state)

[30 seconds later, job completes]
  → Server sends: queue:status (updated completed count)
  → Server sends: queue:jobs (job state change)
  → Server sends: worker:tag:0:status (current_job now null)
```

### Event Ordering

Events are broadcast in order of detection:
1. Database polled
2. Changes detected
3. Events broadcast in topic order (queue → worker → system)

**No guaranteed ordering across topics** - clients should handle out-of-order updates gracefully.

---

## Performance Characteristics

### Polling Overhead

- **Database Queries:** ~5-10ms per poll cycle
- **Poll Interval:** 1-2 seconds (configurable)
- **CPU Impact:** Negligible (<1% CPU on typical hardware)
- **Network:** ~100-500 bytes per event (JSON-encoded)

### Scalability

- **Client Limit:** ~100 concurrent SSE connections per instance
- **Memory:** ~1KB per client connection
- **Bandwidth:** ~1-5 KB/s per client (depends on update frequency)

**For large deployments:**
- Consider rate limiting SSE connections
- Implement connection pooling
- Cache state snapshots in memory

---

## Debugging SSE

### View SSE Stream

```bash
# Terminal
curl -N http://localhost:8356/api/web/events/status \
  -H "Authorization: Bearer <token>"

# Browser DevTools
# Network tab → EventStream → Messages
```

### Common Issues

**No events received:**
- Check authentication (session token valid?)
- Verify `/api/web/events/status` endpoint accessible
- Check browser console for connection errors
- Ensure workers are running (`worker_enabled=true`)

**Delayed updates:**
- Poll interval is 1-2 seconds (expected latency)
- Check database query performance (slow queries?)
- Verify workers are heartbeating (check `health` table)

**Connection drops:**
- Browser limits: EventSource auto-reconnects
- Load balancer timeout: Increase SSE timeout settings
- Proxy buffering: Disable for SSE endpoints

---

## State Consistency

### Eventual Consistency

StateBroker provides **eventually consistent** state:

- Workers write to database asynchronously
- StateBroker polls every 1-2 seconds
- Clients receive updates with ~1-2s lag

**Acceptable for monitoring UI**, not suitable for:
- Critical real-time control (use direct API calls)
- Transactional consistency requirements
- Sub-second response needs

### Race Conditions

**Scenario:** Client calls API, then receives SSE update from old state.

**Solution:** Clients should:
1. Call API for immediate state changes
2. Wait for SSE confirmation (1-2s)
3. Show optimistic UI updates during wait

**Example:**
```javascript
// Pause workers
async function pauseWorkers() {
  // Optimistic UI update
  setWorkersPaused(true);
  
  // Call API
  await api.admin.pauseWorker();
  
  // SSE will confirm within 1-2s
  // (no need to refresh manually)
}
```

---

## Wire Format

### SSE Message Format

```
event: <topic>
data: <json>

```

**Example:**
```
event: queue:status
data: {"queue_type": null, "pending": 10, "running": 1, "completed": 245, "avg_time": 12.5, "eta": 125.0}

event: worker:tag:0:status
data: {"component": "worker:tag:0", "id": 0, "queue_type": "tag", "status": "healthy", "pid": 1234, "current_job": 123}

```

**Notes:**
- Each message ends with blank line (`\n\n`)
- `event:` line specifies topic name
- `data:` line contains JSON payload
- EventSource API automatically parses this format

---

## Future Enhancements

### Potential Improvements

1. **WebSocket Support** - Lower latency, bidirectional communication
2. **Topic Filtering** - Server-side filtering to reduce bandwidth
3. **Batch Updates** - Combine multiple events into single message
4. **Compression** - Gzip SSE stream for bandwidth savings
5. **Redis Pub/Sub** - Replace database polling with message queue

**Current Status:** Database polling is sufficient for pre-alpha. Evaluate alternatives if scalability issues arise.

---

## Related Documentation

- [Workers & Lifecycle](workers.md) - Worker process model and health system
- [Health System](health.md) - Health table structure and invariants
- [Queue System](queues.md) - Queue DTOs and processing
- [API Reference](../user/api_reference.md) - SSE endpoint documentation
