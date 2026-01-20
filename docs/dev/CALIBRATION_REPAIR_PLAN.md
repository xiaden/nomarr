# Calibration System Regression Repair Plan

**Status:** Repair Plan  
**Created:** 2025-01-18  
**Updated:** 2025-01-20  
**Purpose:** Complete CALIBRATION_REFACTOR.md implementation, remove legacy code

---

## Nomarr Pre-Alpha Policy

Per `copilot-instructions.md`:

> Nomarr is **pre-alpha**. It is okay to break schemas, change APIs, require users to rebuild their database.
> It is **not** okay to build migration frameworks, introduce versioned compatibility layers, or pile up legacy code paths.

**This plan follows that policy:** DELETE legacy code, do not deprecate or archive.

---

## Summary

The calibration refactor is **~90% complete**. Core workflows function correctly. Remaining work:

1. **Phase 5 (Remove Old Code)** is incomplete - legacy endpoint and doc references remain
2. **Documentation drift** - old `calibration.md` references removed collections (must be deleted)
3. **Design doc naming** - `recalibrate_library_direct_wf` was renamed to `write_calibrated_tags_wf` during implementation

---

## Current State Assessment

### ✅ Completed (Working)

| Component | Status | Notes |
|-----------|--------|-------|
| `calibration_state` collection | ✅ | Histogram-based calibration storage |
| `calibration_history` collection | ✅ | Drift tracking with APD/SRD/JSD |
| `CalibrationStateOperations` | ✅ | Full histogram query + upsert API |
| `CalibrationHistoryOperations` | ✅ | Snapshot creation + drift analysis |
| `generate_calibration_wf.py` | ✅ | 427 lines, histogram-based generation |
| `write_calibrated_tags_wf.py` | ✅ | 480 lines, canonical recalibration workflow |
| `calibration_loader_wf.py` | ✅ | Loads calibrations from DB |
| `export_calibration_bundle_wf.py` | ✅ | Export to JSON bundle |
| `import_calibration_bundle_wf.py` | ✅ | Import from JSON bundle |
| `backfill_calibration_hash_wf.py` | ✅ | Migration helper |
| `CalibrationService` | ✅ | Thin orchestration wrapper |
| API endpoints (`/calibration/*`) | ✅ | Histogram-based endpoints work |
| Bootstrap legacy cleanup | ✅ | Marks `calibration_queue`, `calibration_runs` as legacy |

### ⚠️ Incomplete (Needs Removal)

| Component | Issue | Action |
|-----------|-------|--------|
| `clear_calibration_queue` endpoint | No-op endpoint, legacy cruft | **DELETE** |
| `generate_minmax` docstring reference | Line 32 in `ml_calibration_comp.py` | **FIX** |
| `calibration.md` doc | References removed `calibration_runs` table | **DELETE** |

---

## Clarification: `recalibrate_library_direct_wf` → `write_calibrated_tags_wf`

The design doc (line 731) specified:

```python
def recalibrate_library_direct_wf(
    db: Database,
    library_id: str,
    expected_hash: str,
    ...
) -> dict[str, Any]:
    """Recalibrate all files needing recalibration in library."""
```

**Implementation:** This workflow was implemented as `write_calibrated_tags_wf`:

- Loads calibrations from `calibration_state`
- Reads files from library
- Applies normalization to raw predictions
- Writes updated tier/mood tags

**Design doc naming was a proposal, not a requirement.** The implemented name `write_calibrated_tags_wf` is clearer and is the **canonical recalibration workflow**.

**`expected_hash` selective filtering:** This is an optional future optimization, not a missing feature. When libraries grow large enough that full recalibration becomes slow, add hash-based filtering to `write_calibrated_tags_wf`. No separate workflow needed.

**Action:** Update CALIBRATION_REFACTOR.md to reflect that `write_calibrated_tags_wf` IS the implementation of the recalibration concept.

---

## Repair Tasks

### Task 1: Update Design Doc Status (DOCUMENTATION)

Update `CALIBRATION_REFACTOR.md` to reflect actual implementation state:

**File:** [docs/dev/CALIBRATION_REFACTOR.md](docs/dev/CALIBRATION_REFACTOR.md)

```markdown
## Implementation Status (Added Section)

### Phase 1: Data Model ✅
- calibration_state collection: DONE
- calibration_history collection: DONE
- Indexes: DONE (created in bootstrap)
- Legacy collections marked for cleanup: DONE

### Phase 2: Persistence Layer ✅
- calibration_state_aql.py: DONE (203 lines)
- calibration_history_aql.py: DONE (208 lines)

### Phase 3: Component Layer ✅
- generate_histogram_calibration: DONE (in generate_calibration_wf.py)
- derive_percentiles_from_histogram: DONE
- apply_minmax_calibration: DONE (uses p5/p95 from DB)

### Phase 4: Service Layer ✅
- CalibrationService: DONE (227 lines)
- Background generation thread: DONE
- Progress tracking: DONE

### Phase 5: Remove Old Code ✅
- calibration_queue_aql.py: DELETED
- calibration_runs_aql.py: DELETED
- clear_calibration_queue endpoint: DELETED
- Old calibration.md doc: DELETED

### Phase 6: Export/Import ✅
- export_calibration_bundle_wf.py: DONE (177 lines)
- import_calibration_bundle_wf.py: DONE (251 lines)

### Recalibration Workflow
- Design doc name: `recalibrate_library_direct_wf`
- Implementation name: `write_calibrated_tags_wf` (canonical)
- Status: COMPLETE
- Future optimization: Add `expected_hash` filter for selective recalibration
```

---

### Task 2: Clean Up Legacy Docstring References (CODE)

**File:** [nomarr/components/ml/ml_calibration_comp.py](nomarr/components/ml/ml_calibration_comp.py#L32)

**Current (line 32):**
```python
calibration_data: Output from generate_minmax_calibration() (DTO or legacy dict)
```

**Fixed:**
```python
calibration_data: Calibration data dict with "calibrations" key mapping labels to {p5, p95}
```

---

### Task 3: Delete Outdated Documentation (DOCUMENTATION)

**File:** [docs/dev/calibration.md](docs/dev/calibration.md)

This file references the OLD system (`calibration_runs` table, versioned sidecar files, etc.).

**Action:** DELETE this file. Do not archive, do not deprecate.

The current system is documented in `CALIBRATION_REFACTOR.md`. Keeping old docs creates confusion and documentation drift.

---

### Task 4: Delete Legacy Endpoint (CODE)

**File:** [nomarr/interfaces/api/web/calibration_if.py](nomarr/interfaces/api/web/calibration_if.py#L100)

The `clear_calibration_queue` endpoint is a no-op that references a removed system.

**Action:** DELETE the endpoint function entirely. Pre-alpha means no backward compatibility shims.

```python
# DELETE THIS ENTIRE BLOCK (lines ~100-108):
@router.post("/clear", dependencies=[Depends(verify_session)])
async def clear_calibration_queue(
    tagging_service: Any = Depends(get_tagging_service),
) -> dict[str, str]:
    """DEPRECATED: Tagging no longer uses queues..."""
    return {"status": "ok", "message": "Tagging no longer uses queues (no-op)"}
```

---

## Execution Checklist

```
[x] 1. Update CALIBRATION_REFACTOR.md with implementation status section
[x] 2. Fix docstring in ml_calibration_comp.py line 32
[x] 3. DELETE docs/dev/calibration.md (git rm)
[x] 4. DELETE clear_calibration_queue endpoint from calibration_if.py
    - Also removed: frontend components, types, DTOs
[ ] 5. Run tests: pytest tests/unit/workflows/calibration/
[ ] 6. Run mypy: mypy nomarr/workflows/calibration/
[ ] 7. Commit: "chore(calibration): complete refactor, remove legacy code and docs"
```

---

## Verification

After repairs, verify:

1. **Histogram generation works:**
   ```bash
   curl -X POST http://localhost:8000/api/web/calibration/generate-histogram
   ```

2. **Calibration status returns data:**
   ```bash
   curl http://localhost:8000/api/web/calibration/status
   ```

3. **Apply calibration works:**
   ```bash
   curl -X POST http://localhost:8000/api/web/calibration/apply
   ```

4. **No import errors:**
   ```bash
   python -c "from nomarr.workflows.calibration import *; print('OK')"
   ```

5. **Tests pass:**
   ```bash
   pytest tests/unit/workflows/calibration/ -v
   ```

6. **Deleted endpoint returns 404:**
   ```bash
   curl -X POST http://localhost:8000/api/web/calibration/clear
   # Should return 404, not 200
   ```

---

## Future Work (Optional Optimizations)

These are NOT blockers but would improve performance for large libraries:

1. **Selective recalibration** - Add `expected_hash` filter to `write_calibrated_tags_wf` to only recalibrate files where `calibration_hash != expected_hash`
2. **Calibration bundler CLI** - Export bundles for nom-cal repository
3. **Online calibration sharing** - Import calibrations from community
4. **Incremental histogram updates** - Update histograms without full scan

---

## Design Analysis: Discovery-Based Auto-Recalibration

### Problem Statement

Currently, calibrated tag application requires manual API calls:
1. User generates calibration (`POST /calibration/generate-histogram`)
2. User applies calibration (`POST /calibration/apply`)

**Question:** Should we move to a discovery-based approach where a background thread polls for ML tagging work completion and applies calibrated tags automatically?

### Current Flow (Manual)

```
User Request → CalibrationService → write_calibrated_tags_wf → Done
                    ↓
              (blocking, synchronous)
```

### Proposed Flow (Discovery-Based)

```
DiscoveryWorker completes file processing
        ↓
    Emits event / updates file state
        ↓
CalibrationDiscoveryThread (polling)
        ↓
    Detects files with raw tags but no calibrated tags
        ↓
    Applies write_calibrated_tags_wf in batches
```

### Analysis: Potential Gains

| Aspect | Manual (Current) | Discovery (Proposed) |
|--------|------------------|----------------------|
| **User Experience** | Must remember to apply calibration | Automatic, seamless |
| **Latency** | Immediate when triggered | Delayed (poll interval) |
| **Complexity** | Simple request-response | New polling thread, state tracking |
| **Resource Usage** | On-demand | Continuous background overhead |
| **Failure Handling** | User retries | Must implement retry logic |
| **Batch Efficiency** | User-controlled batch size | Must tune poll interval + batch size |
| **Progress Visibility** | Clear start/end | Harder to track "when done" |

### Key Considerations

1. **When to trigger auto-recalibration?**
   - After each file? (too granular, inefficient)
   - After N files? (arbitrary threshold)
   - After library scan completes? (natural boundary)
   - When user navigates to library? (JIT, delays UX)

2. **Calibration freshness:**
   - Auto-recalibration makes sense AFTER calibration generation
   - If calibrations don't exist yet, nothing to apply
   - Need to detect "calibration version changed" → re-apply

3. **Race conditions:**
   - What if user triggers manual apply while discovery is running?
   - What if calibration regeneration runs while apply is in progress?

4. **Already have a natural trigger:**
   - Library scan completion is a clear event
   - Could hook auto-apply to scan completion rather than polling

### Recommendation

**DEFER discovery-based approach.** Here's why:

1. **Complexity cost is high:** Adds polling loop, state tracking, race condition handling, retry logic.

2. **Natural trigger exists:** Library scan completion already emits telemetry. Hook recalibration there instead of polling.

3. **Calibration is infrequent:** Users don't regenerate calibrations often (maybe after adding significant new content). Manual apply is acceptable.

4. **Alternative: Event-driven (not polling):**
   ```python
   # In scan completion handler:
   if scan_result.new_files > 0 and calibrations_exist():
       queue_recalibration_job(library_id)
   ```
   This is simpler than continuous polling and achieves the same goal.

### If Implemented: Sketch

```python
# services/domain/calibration_discovery_svc.py

class CalibrationDiscoveryService:
    """
    Background service that monitors for files needing recalibration
    and applies calibrated tags automatically.
    """
    
    def __init__(self, db: Database, poll_interval_s: int = 60):
        self._db = db
        self._poll_interval = poll_interval_s
        self._running = False
        self._thread: threading.Thread | None = None
    
    def start(self) -> None:
        """Start discovery polling loop."""
        self._running = True
        self._thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
    
    def stop(self) -> None:
        """Stop discovery polling."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
    
    def _poll_loop(self) -> None:
        while self._running:
            try:
                self._check_and_apply()
            except Exception as e:
                logger.error(f"[CalibrationDiscovery] Poll error: {e}")
            time.sleep(self._poll_interval)
    
    def _check_and_apply(self) -> None:
        # Get current calibration version
        version = self._db.meta.get_calibration_version()
        if not version:
            return  # No calibrations exist
        
        # Count files needing recalibration
        count = self._db.library_files.count_files_needing_recalibration(version)
        if count == 0:
            return
        
        logger.info(f"[CalibrationDiscovery] Found {count} files needing recalibration")
        
        # Apply in batches
        write_calibrated_tags_wf(db=self._db, params=...)
```

**Estimated effort:** 2-3 hours for basic implementation, plus testing.

**Estimated gain:** Removes one manual step for users, but adds operational complexity.

**Verdict:** Not worth it for alpha. Revisit when user feedback indicates this is a pain point.

---

## Summary

The calibration refactor is **functionally complete**. Remaining work:

| Task | Type | Action |
|------|------|--------|
| CALIBRATION_REFACTOR.md | Doc | Add status section |
| ml_calibration_comp.py | Code | Fix docstring |
| calibration.md | Doc | **DELETE** |
| clear_calibration_queue endpoint | Code | **DELETE** |

No new workflows required. `write_calibrated_tags_wf` is the canonical recalibration implementation.

Discovery-based auto-recalibration is **deferred** - event-driven approach on scan completion would be simpler if automatic application is desired.
