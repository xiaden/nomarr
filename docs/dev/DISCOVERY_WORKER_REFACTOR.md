# Discovery-Based Worker System

**Status:** Implementation Plan  
**Date:** January 2026

---

## Overview

This document describes Nomarr's new discovery-based ML processing system. This is a **complete replacement** of the queue-based worker architecture. The queue system, including `BaseWorker`, `TaggerWorker`, and `tag_queue` persistence, will be **deleted entirely**.

**Removed System:** Queue-based workers polling `tag_queue` collection  
**New System:** Discovery-driven workers querying `library_files` directly with document-based claiming

---

## Scope / End State

This refactor is a **hard replacement**. Nomarr does not support deprecation, legacy code, backwards compatibility, or transition shims.

### What Gets Deleted

The following components are **removed entirely** from the codebase:

**Worker Classes:**
- `BaseWorker` - queue-based worker abstract class
- `TaggerWorker` - queue-polling ML processing worker
- All queue polling, dequeue, and complete logic

**Queue Infrastructure:**
- `tag_queue` collection and all AQL operations
- `QueueOperations` class and queue lifecycle management
- `QueueService` and queue-related workflows
- Queue depth tracking, stats, and monitoring endpoints

**Persistence Layer:**
- `tag_queue_aql.py` and all queue persistence operations
- Queue-specific meta flags and counters
- Enqueue/dequeue/complete/reset workflows

### End State Architecture

**After this refactor:**
- Workers are discovery-driven, not queue-driven
- No queue semantics exist anywhere in the system
- No dequeue/complete/pending/running state machine
- `library_files` is the single authoritative source of work state
- Claim documents are ephemeral leases, not persistent state
- No compatibility layers or legacy code paths remain

---

## Removed System Analysis

This section documents the queue-based system that is being **deleted**.

### Architecture Being Removed

The queue-based ML processing system followed a traditional pattern:

1. **Enqueue Phase:** Library scanning discovers audio files → creates entries in `tag_queue` collection
2. **Worker Polling:** Multiple workers poll `tag_queue` for pending work using atomic `claim_job()`
3. **Processing:** Workers process claimed files → update status to completed/error
4. **State Management:** Processing state tracked in both `tag_queue` (lifecycle status) and `library_files` (ML flags)

### Components Being Deleted

**Queue Infrastructure (DELETED):**
- `tag_queue` collection storing work entries
- `QueueOperations` class managing lifecycle (enqueue/dequeue/complete)
- `QueueService` providing business logic and validation
- Queue-specific workflows for enqueue/cleanup/reset operations

**Worker System (DELETED):**
- `BaseWorker` with queue polling loop
- `TaggerWorker` extending `BaseWorker` for ML processing
- Atomic claiming via ArangoDB `UPDATE...FILTER...LIMIT 1`
- Dequeue/complete/error lifecycle methods

**Library Integration:**
- `library_files` collection with authoritative ML processing state:
  - `needs_tagging` (0/1) - work exists: file requires ML processing
  - `tagged` (0/1) - work completed: ML processing successfully finished
  - `tagged_version` - model version that processed this file (for reprocessing detection)
  - `last_tagged_at` - timestamp of successful processing completion
  - Processing state is determined by: `needs_tagging=1 AND tagged=0`

### Identified Issues

**Complexity:**
- Dual state management between queue and library collections
- Queue depth tracking and cleanup operations
- Complex job lifecycle state machine (pending/running/completed/error)

**Resilience:**
- Queue jobs can become orphaned if workers crash during processing
- Manual intervention required to reset stuck or toxic jobs
- Queue collection grows indefinitely without periodic cleanup

**Scalability:**
- Queue becomes bottleneck for high-throughput scenarios
- Worker conflict resolution limited to single-job atomic claiming
- No natural work distribution or priority handling

---

## Non-Goals

This refactor explicitly **does not** include:

**No Queue Semantics:** 
- No enqueue/dequeue/complete lifecycle anywhere in the system
- No "pending/running/completed/error" state machine
- No work entries beyond `library_files` documents and ephemeral claim leases

**No Complex Work Distribution:**
- No priority queuing or sophisticated routing
- No worker specialization or capability matching
- No cross-library dependencies or ordering

**No Compatibility Layers:**
- No transition period where old and new systems coexist
- No migration path for in-flight queue entries (queue must be empty before deletion)
- No configuration option to use "old" vs "new" worker mode
- Old code is deleted, not deprecated

---

## Removed Components

The following are **deleted entirely** from the codebase:

| Component | Location | Reason for Deletion |
|-----------|----------|--------------------|
| `BaseWorker` | `services/infrastructure/workers/base.py` | Queue-based polling loop replaced by discovery loop |
| `TaggerWorker` | `services/infrastructure/workers/tagger.py` | Replaced by `DiscoveryWorker` |
| `QueueOperations` | `persistence/database/tag_queue_aql.py` | Entire file deleted |
| `QueueService` | `services/infrastructure/queue_svc.py` | Queue orchestration no longer exists |
| `tag_queue` collection | ArangoDB | No queue entries needed |
| Queue workflows | `workflows/queue/` | Enqueue/reset/cleanup workflows deleted |
| Queue components | `components/queue/` | Queue enqueue/dequeue/status components deleted |

---

## New Discovery-Based Architecture

### Core Concept

Replace queue-mediated work distribution with direct library discovery:

1. **Workers query `library_files`** for unprocessed files (`needs_tagging=1`, `tagged=0`)
2. **Single-file claiming** - workers claim exactly 1 file at a time via `worker_claims` document
3. **ArangoDB uniqueness constraints** handle multi-worker claiming automatically
4. **Atomic completion** updates ML processing flags directly on library files

### New Discovery Worker Runtime

**Worker Loop (replaces queue polling):**
1. Query `library_files` for next unprocessed file
2. Attempt to claim file by inserting document with deterministic key
3. If claim successful, process file using `process_file_workflow`
4. Update `library_files` state (set `tagged=1`) before removing claim document
5. Repeat immediately (no sleep between files)

**No Queue Logic:**
- No dequeue/complete/error state transitions
- No "running" state tracking beyond claim documents
- No queue depth or lifecycle monitoring
- Claims are temporary leases, not authoritative state

### Data Model

**New Document Collection: `worker_claims`**
```javascript
{
  "_key": "claim_12345",      // Deterministic key: "claim_" + file._key
  "file_id": "library_files/12345",    // Claimed file document ID
  "worker_id": "worker:tag:0",         // Worker identifier (matches health.component_id)
  "claimed_at": 1737158400000          // Lease timestamp (milliseconds)
}
```

**Existing Collections (No Changes Required):**
- `library_files` - already contains necessary ML processing flags
- `health` - existing worker health monitoring system
- `file_tags` - existing ML tag storage

### Discovery Algorithm

**Single File Discovery:**
```aql
/* Query for next unprocessed file */
FOR file IN library_files
    FILTER file.needs_tagging == 1
    FILTER file.is_valid == 1
    SORT file._key
    LIMIT 1
    RETURN file._id
```

> **Note:** Only `needs_tagging=1` is checked because `mark_file_tagged()` atomically sets both `tagged: 1` AND `needs_tagging: 0`. The `tagged` field is not needed in the discovery filter.

**ArangoDB-Native Claiming:**
1. Worker discovers next candidate file
2. Worker attempts to insert claim document using deterministic `_key`
3. ArangoDB enforces uniqueness - successful insert claims the file
4. Failed insert indicates another worker already claimed that file (worker immediately retries discovery)

**Claim Document Structure:**
```javascript
{
  "_key": "claim_12345",              // Deterministic: "claim_" + file._key
  "file_id": "library_files/12345",   // Claimed file document ID
  "worker_id": "worker:tag:0",        // Matches health.component_id
  "claimed_at": 1737158400000         // Lease timestamp (ms)
}
```

**Conflict Resolution:**
No explicit conflict resolution needed - ArangoDB document key uniqueness prevents multiple claims per file. First worker to insert wins automatically.

### Processing Workflow

1. **Discovery Phase:** Worker queries for unprocessed files and attempts claiming
2. **Processing Phase:** Worker processes claimed file using `process_file_workflow`
3. **Completion Phase:** Worker sets `tagged=1` flag BEFORE removing claim document
4. **Error Handling:** On failure, document removed but `tagged` flag unchanged (file rediscoverable)

### Lease Semantics

**Claim Documents as Ephemeral Leases:**
- Worker claim documents represent temporary work leases, not authoritative job state
- Claims automatically expire when workers become inactive (heartbeat timeout)
- Files with expired claims become available for rediscovery
- Library files remain the single source of truth for processing state

**Lease Expiry Strategy:**
```aql
/* Remove claims from workers with stale heartbeats */
LET active_workers = (
    FOR h IN health
        FILTER h.component_type == "worker"
        FILTER h.last_heartbeat > @heartbeat_cutoff
        RETURN h.component_id
)
FOR claim IN worker_claims
    FILTER claim.worker_id NOT IN active_workers
    REMOVE claim IN worker_claims
```

**Active Worker Definition:**
A worker is considered "active" if its health record shows `last_heartbeat` within the heartbeat timeout window (30 seconds). This integrates with existing health monitoring without additional infrastructure.

---

## Implementation Approach

### Clean Replacement Strategy

This is a **hard replacement** with no transition period:

1. **Delete Queue System:** Remove all queue-related components, collections, and workflows
2. **Implement Discovery System:** Create new discovery workers and claim management
3. **Update Dependencies:** Modify any code that referenced queue workers or operations
4. **Validate System:** Test discovery workers against real library data

### Core Implementation Tasks

**Database Changes:**
- Delete `tag_queue` collection (see Schema and Bootstrap Changes)
- Add `worker_claims` document collection (see Schema and Bootstrap Changes)
- Add discovery query indexes (see Schema and Bootstrap Changes)

**Component Development:**
- `worker_discovery_comp.py` - Core discovery and claiming logic
- `worker_claims_aql.py` - Persistence operations for claim documents
- `discovery_worker.py` - New worker implementation (no inheritance from `BaseWorker`)
- Delete all modules listed in "Deletions (No Replacement)" section

**System Integration:**
- Update `WorkerSystemService` to manage discovery workers only
- Integrate claim cleanup into health monitor cycle
- Remove queue config options (see Configuration Changes)
- Delete queue API endpoints and CLI commands (see API and Frontend Impact)

### Validation Requirements

**Functional Testing:**
- Multi-worker claiming scenarios (3+ workers claiming overlapping file sets)
- Large library processing (10,000+ file discovery performance)
- Worker crash recovery and claim cleanup verification
- End-to-end processing validation

**Performance Benchmarking:**
- Discovery query performance baselines
- Bulk claiming efficiency measurement
- Overall system throughput validation

---

## API and Frontend Impact

### Deleted API Endpoints (No Replacement)

**Web UI Queue Endpoints (`/api/web/queue/*`):**
- `GET /api/web/queue/list` - Job listing with pagination/filtering
- `GET /api/web/queue/queue-depth` - Queue status summary
- `GET /api/web/queue/status/{job_id}` - Individual job status
- `POST /api/web/queue/admin/remove` - Remove jobs by ID/status
- `POST /api/web/queue/admin/clear-all` - Clear all jobs
- `POST /api/web/queue/admin/clear-completed` - Clear completed jobs
- `POST /api/web/queue/admin/clear-errors` - Clear error jobs
- `POST /api/web/queue/admin/cleanup` - Remove old jobs
- `POST /api/web/queue/admin/reset` - Reset stuck/error jobs

**V1 API Queue Endpoints (`/api/v1/admin/queue/*`):**
- `POST /api/v1/admin/queue/remove` - Remove job by ID
- `POST /api/v1/admin/queue/flush` - Flush jobs by status
- `POST /api/v1/admin/queue/cleanup` - Remove old jobs

**Replacement:**
No direct replacement. Processing state visible through:
- Library stats endpoints (`/api/web/libraries/stats`) show unprocessed file counts
- Worker health endpoints show active processing
- File-level tags endpoint shows individual file processing state

### Deleted CLI Commands (No Replacement)

- `nom admin-reset --stuck` - Reset stuck jobs
- `nom admin-reset --errors` - Reset error jobs
- `nom remove --status <status>` - Remove jobs by status
- `nom remove --all` - Remove all jobs
- `nom remove <job_id>` - Remove specific job

**Replacement:**
None. Discovery system is self-healing - no manual queue intervention needed.

### Deleted Frontend Components

**Queue Monitoring Dashboard:**
- Job list table with status filtering
- Queue depth summary cards
- Job status detail view
- Queue management actions (clear/remove/reset)

**Replacement:**
Remove queue monitoring UI entirely. Replace with:
- Library processing status view (unprocessed file count from stats endpoint)
- Worker activity indicators (from health system)
- Per-file processing state (from tags endpoint)

---

## Claim Semantics

### Document Collection Contract

**Collection Name:** `worker_claims`

**Collection Type:** Regular document collection (NOT edge collection)

**Document Structure:**
```javascript
{
  "_key": "claim_12345",              // Deterministic: "claim_" + file._key
  "file_id": "library_files/12345",   // Claimed file document ID
  "worker_id": "worker:tag:0",        // Matches health.component_id
  "claimed_at": 1737158400000         // Claim timestamp (ms)
}
```

> **Why not an edge collection?** The health collection uses auto-generated `_key` values with `component_id` as a regular field. Since we can't reliably reference `health/<component_id>` for `_from`, a regular document collection with `worker_id` matching is simpler and equally effective.

### Claim Lifecycle Rules

**1. File Eligibility (Discovery Phase):**
File is discoverable if ALL conditions met:
- `needs_tagging == 1` (file requires ML processing)
- `is_valid == 1` (file passed validation)
- NO claim document with matching `file_id` exists

**2. Claiming (Atomicity):**
- Worker attempts `INSERT` with deterministic `_key`
- ArangoDB uniqueness constraint enforces one claim per file
- First worker to insert wins; others fail silently
- Failed inserts indicate file already claimed by another worker

**3. Processing:**
- Worker processes claimed file
- On success: sets `tagged=1` BEFORE removing claim document
- On error: removes claim document, leaves `tagged=0` (file becomes rediscoverable)

**4. Completion Marking:**
Worker MUST atomically:
1. Update `library_files` document: `tagged=1`, `needs_tagging=0`, `last_tagged_at=<timestamp>`
2. Remove claim document

If crash occurs between steps, cleanup handles stale claim (see below).

### Claim Cleanup Rules

**Cleanup runs on 30-second interval, removes claims matching ANY condition:**

**1. Inactive Worker Claims:**
```aql
/* Remove claims from workers with stale heartbeats */
LET active_workers = (
    FOR h IN health
        FILTER h.component_type == "worker"
        FILTER h.last_heartbeat > @heartbeat_cutoff
        RETURN h.component_id
)
FOR claim IN worker_claims
    FILTER claim.worker_id NOT IN active_workers
    REMOVE claim IN worker_claims
```

**2. Stale Claims (Completed Files):**
```aql
/* Remove claims for files that are already tagged */
FOR claim IN worker_claims
    LET file = DOCUMENT(claim.file_id)
    FILTER file.tagged == 1 OR file.needs_tagging == 0
    REMOVE claim IN worker_claims
```

**3. Stale Claims (Ineligible Files):**
```aql
/* Remove claims for files that no longer need processing */
FOR claim IN worker_claims
    LET file = DOCUMENT(claim.file_id)
    FILTER file == null OR file.needs_tagging == 0 OR file.is_valid == 0
    REMOVE claim IN worker_claims
```

**Cleanup Integration:**
Cleanup runs in existing health monitor cycle - no new scheduler needed.

---

## Schema and Bootstrap Changes

### Collection Creation

**Add to `components/platform/arango_bootstrap_comp.py` in `_create_collections()`:**

```python
# Add to document_collections list (NOT edge_collections)
document_collections = [
    # ... existing collections ...
    "worker_claims",  # worker→file claim leases (NEW)
]

for collection_name in document_collections:
    if not db.has_collection(collection_name):
        try:
            db.create_collection(collection_name)  # edge=False is default
        except CollectionCreateError:
            pass  # Collection already exists (race condition)
```

### Required Indexes

**worker_claims Collection:**
```python
# No additional indexes required
# _key uniqueness enforced automatically by ArangoDB
```

**library_files Collection:**
```python
# Add composite index for discovery query in _create_indexes()
# in components/platform/arango_bootstrap_comp.py

_ensure_index(
    db,
    "library_files",
    "persistent",
    ["needs_tagging", "is_valid"],
    name="discovery_query"
)
```

---

## Configuration Changes

### Removed Configuration

No queue-specific configuration exists in current `config.yaml`.

### Retained Configuration

**Keep in `config.yaml`:**
```yaml
tagger_worker_count: 1      # Number of discovery workers (unchanged from current)
```

### Configuration Migration

No migration needed - `tagger_worker_count` already exists and controls worker count.

---

## Deletions (No Replacement)

This section enumerates all components deleted with **no functional replacement**.

### Python Modules (Entire Files Deleted)

**Services:**
- `services/infrastructure/queue_svc.py` - QueueService class

**Workers:**
- `services/infrastructure/workers/base.py` - BaseWorker abstract class
- `services/infrastructure/workers/tagger.py` - TaggerWorker class

**Components:**
- `components/queue/` - Entire directory deleted:
  - `queue_cleanup_comp.py`
  - `queue_dequeue_comp.py`
  - `queue_enqueue_comp.py`
  - `queue_status_comp.py`
  - `__init__.py`

**Workflows:**
- `workflows/queue/` - Entire directory deleted:
  - `clear_queue_wf.py`
  - `remove_jobs_wf.py`
  - `reset_jobs_wf.py`
  - `enqueue_files_wf.py`
  - `__init__.py`

**Persistence:**
- `persistence/database/tag_queue_aql.py` - QueueOperations class

**CLI Commands:**
- `interfaces/cli/commands/admin_reset_cli.py` - Reset stuck/error jobs
- `interfaces/cli/commands/remove_cli.py` - Remove jobs from queue

**Interfaces:**
- `interfaces/api/web/queue_if.py` - Entire file deleted (all web queue endpoints)
- `interfaces/api/v1/admin_if.py` - Remove queue endpoints only (keep cache/worker endpoints):
  - Remove `POST /v1/admin/queue/remove`
  - Remove `POST /v1/admin/queue/flush`
  - Remove `POST /v1/admin/queue/cleanup`
- `interfaces/api/types/queue_types.py` - Entire file deleted (queue request/response models)

### ArangoDB Collections (Dropped)

- `tag_queue` - Job queue collection (all documents deleted)

### Frontend Components (Removed)

**Feature Directory:**
- `frontend/src/features/tagger-status/` - Entire directory deleted

**Files Deleted:**
- `frontend/src/features/tagger-status/TaggerStatusPage.tsx` - Main queue monitoring page
- `frontend/src/features/tagger-status/components/QueueJobsTable.tsx` - Job listing table
- `frontend/src/features/tagger-status/components/QueueSummary.tsx` - Queue status cards
- `frontend/src/features/tagger-status/components/QueueFilters.tsx` - Status filtering controls
- `frontend/src/features/tagger-status/hooks/useQueueData.ts` - Queue data fetching hook
- `frontend/src/features/tagger-status/index.ts` - Feature exports
- `frontend/src/features/tagger-status/README.md` - Feature documentation

**API Client Functions:**
- `frontend/src/shared/api/queue.ts` - All queue API functions deleted

**Routes:**
- Remove tagger-status route from `frontend/src/router/index.tsx`

### Documentation (Delete or Rewrite)

**Delete Entirely:**
- `docs/dev/queues.md` - Queue system documentation

**Update (Remove Queue References):**
- `docs/user/getting_started.md` - Remove queue CLI examples
- `docs/user/api_reference.md` - Remove queue API endpoints
- `readme.md` - Remove queue management examples

---

## Benefits Analysis

### Eliminated Complexity

**Queue Infrastructure Removal:**
- No queue depth tracking, lifecycle management, or cleanup operations
- Eliminates duplicate state between work entries and library files
- Removes queue-specific APIs, workflows, and persistence operations
- Simplified monitoring with single source of truth in library files

**Worker Simplification:**
- No dequeue/complete state machine logic
- No "running" state management beyond ephemeral claim leases
- Automatic system recovery from any failure state through rediscovery
- Reduced configuration complexity (no queue tuning parameters)

### Enhanced Resilience

**Crash-Proof Design:**
- Worker crashes leave only ephemeral claim documents that are automatically cleaned
- File processing state preserved in persistent library files
- No lost work - unprocessed files automatically rediscovered after restart
- Self-healing system requires no manual intervention

**Atomic Operations:**
- File claiming prevents duplicate processing across workers
- Completion marking ensures processed files not rediscovered
- Conflict resolution handled automatically by ArangoDB uniqueness

### Improved Scalability

**Direct Library Access:**
- Workers bypass queue bottleneck for improved throughput
- Document-key claiming scales to many concurrent workers
- Discovery queries optimizable for specific use cases (priority, album grouping)

**Load Distribution:**
- Natural work distribution through discovery query ordering
- Future capability for complexity-based load balancing
- Library-aware processing for organized batch operations

### Better Observability

**Simplified Monitoring:**
- Single metric: count of files with `needs_tagging=1`
- Real-time worker activity visible through `worker_claims` documents
- Clear processing state without complex lifecycle tracking
- Direct library file processing history

---

## Risk Assessment

### Implementation Risks

**Low Risk - Discovery Query Performance:**
- Single file query with composite index is fast (< 1ms typical)
- **Mitigation:** Composite index on (needs_tagging, is_valid)
- **Monitoring:** None needed (query is trivial)

**Low Risk - Claim Competition:**
- Workers claim 1 file at a time, retry immediately on conflict
- **Mitigation:** ArangoDB document key uniqueness handles conflicts automatically
- **Monitoring:** None needed (conflict is normal, immediate retry)

**Low Risk - Implementation Complexity:**
- New worker runtime is simpler than queue-based (less code)
- **Validation:** Process test library, verify completion

### Operational Risks

**Low Risk - Health System Dependency:**
- Orphaned claim cleanup relies on existing health monitoring
- **Current State:** Health system already proven reliable
- **Mitigation:** Health system has no single points of failure

**Low Risk - Database Load:**
- Single file queries are cheaper than queue polling
- **Mitigation:** Composite index ensures fast queries
---

## Success Metrics

### Performance Metrics
- Discovery query < 1ms (single file query with composite index)
- Processing throughput unchanged (same ML pipeline, different work distribution)
- No performance impact from claim conflicts (immediate retry, negligible cost)

### Reliability Metrics
- Zero orphaned claims after worker crashes (30s cleanup window)
- 100% file rediscovery after system restart (query-based discovery)
- No duplicate processing (enforced by claim uniqueness and atomic completion)

### Operational Metrics
- Code deletion: ~2000 lines removed (queue infrastructure)
- API deletion: 12 endpoints removed
- Frontend deletion: 1 feature module removed
- No new monitoring infrastructure needed

---

## Conclusion

The discovery-based worker system eliminates queue infrastructure by letting workers query `library_files` directly. This is a **hard replacement** with no backward compatibility.

**Key Changes:**
- Delete: `tag_queue` collection, `QueueService`, `BaseWorker`, queue endpoints, queue UI
- Add: `worker_claims` document collection, discovery component, claim cleanup in health monitor
- Workers claim 1 file at a time, process immediately, repeat

---

## System Invariants

The new system maintains these core invariants:

**Single Source of Truth:**
- `library_files` collection is the authoritative source of all processing state
- `needs_tagging=1` defines unprocessed files (mark_file_tagged sets both `tagged=1` AND `needs_tagging=0` atomically)
- No work state exists outside of library files and ephemeral claim leases

**Claim Document Semantics:**
- Claim documents are temporary leases only, not authoritative state
- Claims automatically expire when workers become inactive
- Files with expired claims become available for rediscovery

**Atomic Completion:**
- Workers MUST update `library_files.tagged=1, needs_tagging=0` BEFORE removing claim documents
- Failure to complete leaves file in rediscoverable state
- No partial completion or "running" state persistence

---

## Appendix A: Implementation Checklist

### Database Changes
- [ ] Delete `tag_queue` collection (DROP COLLECTION tag_queue)
- [ ] Add "worker_claims" to document collections in `components/platform/arango_bootstrap_comp.py`
- [ ] Add discovery query composite index in `_create_indexes()` (see Schema and Bootstrap Changes)
- [ ] Remove `tag_queue` indexes from `_create_indexes()` function

### Component Deletion (See "Deletions (No Replacement)" section)
- [ ] Delete services: `queue_svc.py`
- [ ] Delete workers: `base.py`, `tagger.py`
- [ ] Delete components: All files in `components/queue/`
- [ ] Delete workflows: All files in `workflows/queue/`
- [ ] Delete persistence: `tag_queue_aql.py`
- [ ] Delete CLI commands: `admin_reset_cli.py`, `remove_cli.py`
- [ ] Delete API interfaces: `queue_if.py`, queue routes from `admin_if.py`
- [ ] Delete API types: `queue_types.py`

### New Component Development
- [ ] `worker_discovery_comp.py` - Discovery query, claiming, and cleanup logic
- [ ] `worker_claims_aql.py` - Persistence operations for claim documents
- [ ] `discovery_worker.py` - New worker implementation (no BaseWorker inheritance)
- [ ] Update `WorkerSystemService` to instantiate discovery workers

### Integration Points
- [ ] Add claim cleanup to health monitor cycle
- [ ] Remove queue config from `config.yaml` schema validation
- [ ] Update `db.py` to remove `tag_queue` operations accessor
- [ ] Remove queue service from `app.py` service registration

### Frontend Changes
- [ ] Delete queue monitoring components (see "Deletions (No Replacement)")
- [ ] Delete queue API client functions (`api/queue.ts`)
- [ ] Remove queue route from router
- [ ] Update library stats view to show unprocessed file count

### Documentation Updates
- [ ] Delete `docs/dev/queues.md` entirely
- [ ] Remove queue CLI examples from `docs/user/getting_started.md`
- [ ] Remove queue API endpoints from `docs/user/api_reference.md`
- [ ] Remove queue management examples from `readme.md`

---

## Appendix B: Technical Reference

### Key Data Structures

- `ProcessFileResult` from `helpers/dto/processing_dto.py` (unchanged)
- Claim documents are raw ArangoDB documents (no Python DTO needed)
- Queue DTOs (`helpers/dto/queue_dto.py`) are deleted with queue infrastructure

### Discovery Component Interface

```python
# components/workers/worker_discovery_comp.py

def discover_next_file(db: Database) -> str | None:
    """Discover next unprocessed file.
    
    Returns:
        File _id or None if no work available
    """

def claim_file(db: Database, file_id: str, worker_id: str) -> bool:
    """Attempt to claim file for processing.
    
    Returns:
        True if claim successful, False if already claimed
    """

def release_claim(db: Database, file_id: str) -> None:
    """Release claim on file (after processing or error)."""

def cleanup_stale_claims(db: Database, heartbeat_timeout_ms: int) -> int:
    """Remove claims from inactive workers and completed/ineligible files.
    
    Returns:
        Number of claims removed
    """
```

### Configuration Schema
```yaml
tagger_worker_count: 1           # Number of discovery worker processes (default: 1)
# No discovery-specific config - workers claim 1 file at a time
# Cleanup runs in existing health monitor cycle (30s interval)
# Heartbeat timeout: 30s (existing health system)
```