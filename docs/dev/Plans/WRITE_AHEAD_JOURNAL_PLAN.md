# Write-Ahead Journal (WAJ) Implementation Plan

**Status:** Draft for Review  
**Created:** 2026-01-25  
**Updated:** 2026-01-25  
**Author:** Copilot + xiaden

---

## Problem Statement

When ArangoDB becomes unavailable during shutdown or crash:

1. Worker subprocesses complete work but cannot persist results → **data loss**
2. File writes complete but DB update fails → **DB/filesystem desync**
3. In-flight operations lose progress → **wasted compute**

**Current behavior:** urllib3 retries with backoff, eventually gives up, data lost silently.

**Root cause:** Docker daemon sends SIGTERM to all containers simultaneously. No shutdown ordering exists between Nomarr and ArangoDB.

---

## Core Decision

Write-ahead journaling is implemented at the **SafeDatabase boundary**.

- Journaling is always available and automatic for DB writes
- Call sites do NOT opt in or out
- SafeDatabase handles journal writes transparently

---

## Why Not Use ArangoDB's Built-in WAL?

ArangoDB has a built-in Write-Ahead Log accessible via `python-arango` (`db.wal`).

**However, ArangoDB's WAL does not solve our problem:**

| Feature | ArangoDB WAL | Our Need |
|---------|--------------|----------|
| **Purpose** | Database internal durability | Application-level resilience |
| **When active** | After data reaches ArangoDB | Before data leaves the app |
| **Solves** | DB crash recovery, replication | DB unavailable during write |
| **Requires** | ArangoDB running | Works when ArangoDB is down |

ArangoDB's WAL only helps after data successfully reaches the database. Our problem occurs when the database is unreachable.

---

## Journaling Scope (Shape-Based)

### What Gets Journaled

A DB write **MUST** be journaled if it satisfies this invariant:

> **The write is required for the database to remain a reliable source of truth after restart, assuming the DB may be torn down before the application finishes shutdown.**

If losing this write would cause the DB to be stale, inconsistent, or missing data that the application believes was persisted, it must be journaled.

### What Does NOT Get Journaled

- Ephemeral state rebuilt on startup (health status, runtime metrics)
- Reads and queries
- Writes that can be safely repeated (idempotent cache refreshes)
- Writes where data loss is acceptable (transient notifications)

### Discovery Requirement

**Before implementation begins:**

1. Enumerate all DB write locations that match the journaling shape
2. Document each location with collection and justification
3. Second-pass review confirms completeness
4. Sign-off before coding begins

This enumeration is captured in [Pre-Implementation: Enumerate Write Locations](#pre-implementation-enumerate-write-locations).

---

## SafeDatabase Behavior

SafeDatabase wraps all DB writes with journaling logic.

### When DB is Available

1. Append journal entry (intent record)
2. Attempt DB write
3. On success: append commit marker

### When DB is Unavailable

1. Append journal entry (intent record)
2. Skip DB write (do not retry indefinitely)
3. No commit marker appended

**SafeDatabase does NOT decide:**
- Replay logic
- Compaction policy
- Reprocessing strategy

These are handled by the replay/startup layer.

---

## Multi-Worker Model

**Decision:** One journal per process/worker.

| Property | Value |
|----------|-------|
| Journal files | Per-process (not shared) |
| Cross-process locking | Not required |
| Startup replay | Reads all journal files, merges, sorts by composite key |

**Rationale:** Workers run as separate processes. Per-process journals eliminate cross-process locking during writes. Each process appends to its own journal file without contention.

**Alternative (not v1):** A single shared journal with file locking is an option if replay ordering ever proves problematic. Deferred unless per-worker journals demonstrate issues in practice.

### Journal Directory Structure

```
/app/config/journal/
├── main.jsonl           # Main process journal
├── worker_0.jsonl       # Worker process journals
├── worker_1.jsonl
└── archive/             # Rotated journals (optional)
```

---

## Replay Semantics

### Replay Ordering

Replay merges all per-worker journals and applies entries in deterministic order.

**Sort key:** `(mono_ts_ns, journal_id, seq)`

| Field | Purpose |
|-------|---------||
| `mono_ts_ns` | Monotonic timestamp (nanoseconds) - primary ordering |
| `journal_id` | Stable journal identifier (e.g., filename) - tie-breaker |
| `seq` | Per-journal sequence number - final tie-breaker |

**Why this ordering:**
- Monotonic timestamps may collide or be too close across processes to totally order events
- `journal_id` + `seq` provide deterministic tie-breaking when timestamps collide
- Ordering is reproducible across replays

**Replay process:**
1. Load all journal files in directory
2. Prune committed entries (match intents to commit markers)
3. Sort remaining pending entries by `(mono_ts_ns, journal_id, seq)`
4. Apply in sorted order

### Startup Behavior

1. Replay is **attempted** on startup
2. Replay failure does **NOT** block startup
3. Failed entries mark affected entities as `needs_reprocess`

### Replay Policy

| Condition | Behavior |
|-----------|----------|
| DB available, no pending entries | Normal startup |
| DB available, pending entries exist | Replay entries, then start workers |
| DB unavailable, pending entries exist | Log warning, start in degraded mode, workers will journal new writes |
| Replay fails: corrupt entry | Log error, skip entry, continue |
| Replay fails: DB rejects entry | Mark entity as `needs_reprocess`, continue |

**Rationale:** Blocking startup on replay failure creates a hard dependency on perfect journal state. Marking entities for reprocessing allows recovery without manual intervention.

---

## Retention and Compaction

### Append-Only Journal

- Journal files are strictly append-only during operation
- Commit markers are appended as new records (existing lines never modified)
- Partial writes corrupt only the incomplete line

### Compaction Triggers

1. After successful startup replay (all pending entries committed)
2. When journal file exceeds size threshold (configurable, default 10MB)

### Compaction Process

1. Read entire journal
2. Match intents to commit markers
3. Write only uncommitted intents to new file
4. Atomic rename new file over old

### Retention Options

- **Default:** Committed entries removed after compaction
- **Optional:** Retain recent committed entries for debugging (configurable count/age)
- **Archive:** Optionally rotate old journals to archive directory

---

## Entry Schema

Each journal line is a self-contained JSON record.

**Timestamps:** All timestamps use system monotonic time (`time.monotonic_ns()` or `time.perf_counter_ns()`) to avoid wall clock issues (clock skew, NTP adjustments, daylight saving). Monotonic time is only meaningful within a single system boot; this is acceptable since journals are ephemeral and compacted on startup.

**Intent record (pending work):**
```
type: "intent"
id: UUID
mono_ts_ns: monotonic timestamp (int, nanoseconds)
journal_id: stable identifier for this journal (string)
seq: per-journal sequence number (int, monotonically increasing)
op: "upsert" | "delete" | "update"
collection: target collection name
key: document _key
data: full document or update payload
```

**Commit marker (completion confirmation):**
```
type: "commit"
intent_id: UUID of the intent
mono_ts_ns: monotonic timestamp (int, nanoseconds)
```

**Required fields for deterministic ordering:**
- `mono_ts_ns`: Primary sort key
- `journal_id`: Tie-breaker (stable across process lifetime)
- `seq`: Final tie-breaker (unique within journal)

---

## Error Handling

### Journal Write Failure

If journal write fails (disk full, permissions), the operation fails. Do NOT proceed with DB write if journal fails.

### Corrupt Journal Entry

Skip corrupt entries during replay. Log error. Preserve original journal for debugging.

### DB Rejects Entry on Replay

Mark affected entity as `needs_reprocess`. Continue replay. Do not block startup.

---

## Implementation Phases

### Pre-Implementation: Enumerate Write Locations

**Scope:** Discover all DB write locations matching the journaling shape.

**Process:**

1. Use MCP `discover_api` on `nomarr.persistence.db` and `nomarr.persistence.arango_client`
2. Use `grep_search` for write method patterns across codebase
3. For each location, evaluate against shape invariant
4. Document in tables below

**Acceptance Criteria:**

- [x] Complete enumeration list exists below
- [x] Each location verified against shape invariant
- [ ] Second-pass review confirms completeness
- [ ] Sign-off before Phase 1 begins

**Enumerated Write Locations:**

| Module | Collection | Operation | Shape Match | Justification |
|--------|------------|-----------|-------------|---------------|
| `library_files_aql.py` | `library_files` | UPSERT (upsert_library_file) | **YES** | File discovery from scan; if lost, DB missing files that exist on disk |
| `library_files_aql.py` | `library_files` | UPDATE (mark_ml_complete) | **YES** | ML completion status; if lost, file reprocessed (wasted compute) but not data loss |
| `library_files_aql.py` | `library_files` | UPDATE (update_file_path) | **YES** | File moved; if lost, DB points to old path |
| `library_files_aql.py` | `library_files` | UPDATE (update_calibration_hash) | **YES** | Tracks which calibration was applied; if lost, recalibration may be skipped |
| `library_files_aql.py` | `library_files` | REMOVE (remove_file) | **YES** | File deleted; if lost, DB references nonexistent file |
| `library_folders_aql.py` | `library_folders` | UPSERT (upsert_folder) | **YES** | Folder discovery from scan; if lost, DB missing folder structure |
| `library_folders_aql.py` | `library_folders` | REMOVE (remove_missing_folders) | **YES** | Folder deleted; if lost, DB references nonexistent folder |
| `song_tag_edges_aql.py` | `song_tag_edges` | INSERT/REMOVE (set_song_tags) | **YES** | ML tagging result edges; if lost, tags computed but not persisted |
| `song_tag_edges_aql.py` | `song_tag_edges` | REMOVE (delete_edges_for_song) | **YES** | Song removed; if lost, orphan edges remain |
| `file_tags_aql.py` | `file_tags` | INSERT (set_file_tag, upsert_file_tags) | **YES** | Tag key-value edges; if lost, file metadata missing |
| `file_tags_aql.py` | `file_tags` | REMOVE (clear_file_tags) | **YES** | Clearing tags before rewrite; if lost, stale tags remain |
| `library_tags_aql.py` | `library_tags` | INSERT (create_tag) | **YES** | Tag definition; if lost, tag references break |
| `library_tags_aql.py` | `library_tags` | REMOVE (delete_orphan_tags) | **YES** | Cleanup orphan tags; acceptable to replay |
| `entities_aql.py` | `entities_*` | UPSERT (upsert_entity) | **YES** | ML entity (artist, genre, etc); if lost, entity references break |
| `entities_aql.py` | `entities_*` | REMOVE (cleanup_orphan_entities) | **YES** | Cleanup orphans; acceptable to replay |
| `calibration_state_aql.py` | `calibration_state` | INSERT/UPDATE (upsert_calibration_state) | **YES** | Current calibration state per head; if lost, recalibration logic incorrect |
| `calibration_state_aql.py` | `calibration_state` | DELETE (delete_calibration_state) | **YES** | Cleanup obsolete state; acceptable to replay |
| `calibration_history_aql.py` | `calibration_history` | INSERT (add_history_entry) | **YES** | Calibration run history; if lost, history gaps |
| `calibration_history_aql.py` | `calibration_history` | REMOVE (cleanup_old_history) | **YES** | Cleanup old entries; acceptable to replay |
| `libraries_aql.py` | `libraries` | INSERT (create_library) | **YES** | Library creation; if lost, library definition missing |
| `libraries_aql.py` | `libraries` | UPDATE (update_library, update_scan_status) | **YES** | Library config changes; if lost, config reverted |
| `libraries_aql.py` | `libraries` | REMOVE (delete_library) | **YES** | Library deletion; if lost, deleted library reappears |

**Exclusions:**

| Module | Collection | Justification for Exclusion |
|--------|------------|----------------------------|
| `health_aql.py` | `health` | Ephemeral status rebuilt on startup; heartbeats are transient |
| `worker_claims_aql.py` | `worker_claims` | Transient claim locks; cleaned up on startup; stale claims expire automatically |
| `worker_restart_policy_aql.py` | `worker_restart_policy` | Ephemeral restart tracking; rebuilt from scratch on startup |
| `sessions_aql.py` | `sessions` | Transient auth sessions; users re-authenticate on startup |
| `ml_capacity_aql.py` | `ml_capacity_*` | Cache of capacity probe results; rebuilt by re-probing on demand |
| `meta_aql.py` | `meta` | Schema version (set once), other meta is ephemeral or recalculated |

### Phase 1: Journal Infrastructure

**Scope:** Create journal module.

**Deliverables:**

- Journal class with append-only semantics
- Per-process journal file management
- Intent and commit record handling
- Read pending entries (intents without matching commits)

### Phase 2: SafeDatabase Integration

**Scope:** Integrate journaling into SafeDatabase.

**Deliverables:**

- All DB writes automatically journaled
- Commit marker on successful write
- No commit marker on failed write
- Call sites unchanged (transparent)

### Phase 3: Startup Replay

**Scope:** Implement replay on application startup.

**Deliverables:**

- Read all journal files in directory
- Replay pending entries
- Mark failed replays as `needs_reprocess`
- Compact journals after successful replay
- Log replay statistics

### Phase 4: Verification

**Scope:** Validate implementation.

**Deliverables:**

- Unit tests for journal operations
- Integration tests for replay
- Manual chaos test: kill DB during processing, verify recovery

---

## Implementation Checklist

### Pre-Implementation

- [ ] Read skill: `.github/skills/layer-persistence/SKILL.md`
- [ ] Use MCP `discover_api` on `nomarr.persistence.db`
- [ ] Use MCP `discover_api` on `nomarr.persistence.arango_client`
- [ ] Enumerate write locations (populate tables above)
- [ ] Second-pass review of enumeration
- [ ] Sign-off on enumeration

### Phase 1

- [ ] Create journal module
- [ ] Implement append-only semantics
- [ ] Implement per-process journal paths
- [ ] Write unit tests
- [ ] Run layer validation scripts

### Phase 2

- [ ] Modify SafeDatabase to journal all writes
- [ ] Verify call sites unchanged
- [ ] Run layer validation scripts

### Phase 3

- [ ] Implement startup replay
- [ ] Implement `needs_reprocess` marking
- [ ] Implement compaction
- [ ] Run integration tests

### Phase 4

- [ ] Run full QC
- [ ] Manual chaos test
- [ ] Update architecture documentation

---

## References

### ArangoDB (python-arango)

- [ArangoDB WAL API](https://docs.python-arango.com/en/main/wal.html) - Database-internal WAL (not applicable, see above)
- [ArangoDB Transactions](https://docs.python-arango.com/en/main/transaction.html) - Atomic multi-document writes

### Write-Ahead Logging (Industry Standard)

- [PostgreSQL WAL Documentation](https://www.postgresql.org/docs/current/wal-intro.html)
- [SQLite WAL Mode](https://www.sqlite.org/wal.html)
- [Redis Persistence (AOF)](https://redis.io/docs/management/persistence/)
- [Write-Ahead Logging (Wikipedia)](https://en.wikipedia.org/wiki/Write-ahead_logging)

---

*End of plan document.*
