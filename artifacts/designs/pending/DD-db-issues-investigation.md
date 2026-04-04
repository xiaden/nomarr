# Database Issues Investigation

**Status:** Active Investigation  
**Author:** Discussion synthesis  
**Created:** 2026-03-28

---

## Purpose

This document tracks database issues discovered through inspection, separate from schema design work.

---

## Issue 1: Sessions TTL Index Malfunction

**Status:** 🔴 Confirmed Bug

### Symptoms
- TTL index exists on `sessions.expiry_timestamp` with `expireAfter=0`
- Documents with `expiry_timestamp` from 2026-03-23 still present on 2026-03-27 (4 days past expiry)
- TTL should evict within ~30 seconds of timestamp passing

### Evidence
```
expiry_timestamp: 1774251549000  // Stored value
```

### Hypothesis
**Milliseconds vs Seconds mismatch:**
- ArangoDB TTL index interprets the field value as **Unix seconds**
- Code stores **Unix milliseconds** (e.g., `1774251549000`)
- `1774251549000` as seconds = year 58199 → never expires
- `1774251549000 / 1000 = 1774251549` as seconds = 2026-03-23 → should expire

### Additional Issue
- Redundant datetime fields: both `expiry_timestamp` AND `created_at` exist
- Single-user system has `user_id` field (unnecessary)

### Investigation Steps
- [ ] Verify server timezone configuration
- [ ] Check if ArangoDB TTL expects seconds (documented behavior)
- [ ] Test with manually inserted document using seconds
- [ ] Verify TTL index is active (not just defined)

### Fix (pending schema refactor)
See [design-schema-refactor-v1.md](design-schema-refactor-v1.md) Section 3: Sessions TTL Fix

---

## Issue 2: navidrome_tracks Empty Documents

**Status:** 🟡 Needs Investigation

### Symptoms
- `navidrome_tracks` collection contains empty documents (no fields except `_key`, `_id`, `_rev`)

### Hypothesis A: Intentional Design
- **Thin vertices** for graph topology
- Actual data lives in linked collections via edges
- Empty document = existence marker in graph

### Hypothesis B: Bug
- Write path failing to populate fields
- Data lost during sync

### Investigation Steps
- [ ] Check if edges exist TO these documents
- [ ] Examine `sync_navidrome_wf.py` write path
- [ ] Check if documents were ever populated (look for UPDATE operations)
- [ ] Determine if this is graph topology pattern or data loss

---

## Issue 3: has_nd_id Edge Collection Empty

**Status:** 🟡 Needs Investigation

### Symptoms
- `has_nd_id` edge collection is empty
- Navidrome sync is enabled and Navidrome has tracks
- Expected: edges linking `library_files` to `navidrome_tracks`

### Hypothesis
**Path resolution mismatch:**
- Navidrome reports paths in one format
- `library_files.normalized_path` uses different format
- Matching fails → no edges created

### Investigation Steps
- [ ] Compare Navidrome path format vs `normalized_path` format
- [ ] Check case sensitivity (Windows paths vs Navidrome paths)
- [ ] Check path separator normalization (`/` vs `\\`)
- [ ] Look for error logs in sync workflow

### Code Location
- `nomarr/workflows/navidrome/sync_navidrome_wf.py`

---

## Issue 4: calibration_history Collection Unused

**Status:** 🟢 Confirmed — Delete

### Finding
- Collection exists but no code writes to it
- No read operations found
- Appears to be abandoned feature

### Action
- Add to cleanup migration in schema refactor
- `db.delete_collection('calibration_history')`

---

## Issue 5: ml_capacity_estimates Empty

**Status:** 🟡 Needs Investigation

### Symptoms
- Collection empty despite ML workers running

### Hypothesis
- Estimates expire/clear after use
- Only populated during active probing
- May be transient state collection

### Investigation Steps
- [ ] Check when estimates are written
- [ ] Check if estimates are cleared after consumption
- [ ] Determine if empty is expected idle state

---

## Issue 6: Health Collection Missing component_type

**Status:** 🟡 Needs Investigation

### Symptoms
- Some documents in `health` collection missing `component_type` field

### Hypothesis
- Code path writing health without required field
- Different workers using different write patterns

### Investigation Steps
- [ ] Find all code paths that write to health collection
- [ ] Identify which ones omit `component_type`
- [ ] Fix write paths (not schema issue)

---

## Issue 7: library_folders Orphaning

**Status:** 🟡 Needs Investigation

### Symptoms
- `library_folders.library_id` has no cascade delete
- When library deleted, folder records orphaned

### Fix
- Will be resolved by edge-ification + cascade delete
- See [design-cascade-delete.md](design-cascade-delete.md)

---

## Issue 8: Tag rel Field Broken Format

**Status:** 🟢 Confirmed Data Issue

### Symptoms
```
rel: "nom:sad_v1_musicnnunknown_sadunknown"  // Broken
rel: "nom:musicnn_sad_score"                  // Expected
```

### Cause
- String concatenation bug in tag creation
- "unknown" placeholder not replaced

### Fix
- Migration to fix existing data
- Fix code path that creates broken rel values

### Investigation Steps
- [ ] Find code that creates `rel` field
- [ ] Identify why "unknown" appears
- [ ] Write data migration to fix existing tags

---

## Issue 9: Calibration State model_key Useless

**Status:** 🟢 Confirmed

### Symptoms
```
model_key: "backbone_unknown"  // Always this value
```

### Finding
- Field exists but always contains placeholder
- Not used in any queries
- Should be removed or fixed

### Fix
- Part of schema refactor Calibration State Cleanup

---

## Investigation Priority

| Issue | Severity | Blocking? | Priority |
|-------|----------|-----------|----------|
| Sessions TTL | High | No (manual cleanup works) | P1 |
| has_nd_id empty | Medium | Yes (Navidrome sync broken) | P1 |
| navidrome_tracks empty | Medium | Related to above | P1 |
| Tag rel broken | Low | Cosmetic | P2 |
| Health missing field | Low | Monitoring incomplete | P2 |
| calibration_history | Low | Just cleanup | P3 |
| ml_capacity_estimates | Low | May be expected | P3 |

---

## Notes

- Issues 1, 6, 7, 8, 9 will be addressed by schema refactor
- Issues 2, 3 require code investigation before fix
- Issue 4, 5 may be non-issues (expected state)
