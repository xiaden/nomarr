# Design: Tag Co-Occurrence Grid Fix

**Status:** Planning
**Date:** 2026-03-22

---

## Problem

The Tag Co-Occurrence Grid in the Insights page has two persistent bugs:

### Bug 1: Wrong co-occurrences shown when preset is changed

When the user switches the X or Y axis preset (e.g., Genre → Mood, or Genre → Year), the matrix shows **stale data** from the previous preset rather than the newly selected one. Sometimes it shows all zeros. The matrix does not reliably reflect the current axis configuration.

**Root cause:** `useAxisState` uses two separate `usePresetData` hooks (one per axis) running concurrently. When a preset changes:

1. `SELECT_PRESET` is dispatched — axis state becomes `{ tags: [], loading: true }`.
2. `usePresetData` re-runs with the new `presetId`, triggering a new async fetch.
3. Three `useEffect` hooks run concurrently in `useAxisState` to sync `xPresetData` → state.
4. **Problem A (stale dispatch):** The sync effect says `if (!xPresetData.loading && xPresetData.tags.length > 0) dispatch SET_TAGS`. During the transition, `usePresetData` resets its internal `tags` state to `[]` before the fetch completes. But there is a **React render cycle** where the old `xPresetData.tags` (from the previous preset) may still be non-empty for one render before the new fetch clears it. This can dispatch `SET_TAGS` with the old preset's values.
5. **Problem B (loading state race):** A separate `useEffect` syncs `xPresetData.loading` → axis state. This fires independently from the tags sync, so the matrix `buildMatrix` callback (which gates on `canBuildMatrix = x.tags.length > 0 && y.tags.length > 0`) may fire before or after tags are set, with stale data.
6. **Problem C (mood special-casing):** The mood preset uses `getMoodValues` API, while genre/year use `getUniqueTagValues`. The mood `TagSpec` uses `key: "nom:mood-*"` (a wildcard pattern key) which the backend receives and must handle via `CONTAINS` matching. If the key is not exactly matched to the tier in service logic, or if the frontend sends `key: "nom:mood-*"` but the backend looks for `key.startswith("nom:mood-")`, there's a mismatch.

### Bug 2: Same value cannot be used on both X and Y axes

The `ADD_MANUAL_TAG` reducer in `useAxisState` has this check:

```typescript
const existsOnOther = state[otherAxis].tags.some(
  (t) => t.key === action.tag.key && t.value === action.tag.value
);
if (existsOnOther) return state;
```

This completely prevents the same `{key, value}` from being on both axes in manual mode. This is **wrong**: a diagonal co-occurrence matrix (e.g., a set of moods vs the same set of moods) is a **valid and valuable** use case — it shows how each mood co-occurs with all others. The diagonal itself would show self-co-occurrence (songs that have mood X on both axes — trivially 100%), which is fine and expected.

For the **same preset on both axes** (e.g., Genre vs Genre): the preset path doesn't go through `ADD_MANUAL_TAG`, so same values DO appear. The `SET_TAGS` action doesn't have the exclusion check. This is inconsistent — manual mode and preset mode behave differently.

---

## What Needs to Change

### Frontend-only changes (no backend changes needed)

The backend is correct. The persistence queries are correct. The API interface is correct. All bugs are in the frontend React hook architecture.

#### Fix 1: Rewrite `useAxisState` with a simpler data flow

The current design has 3 separate `useEffect` hooks trying to sync external hook state into a reducer. This creates race conditions. The fix is:

**Option A (preferred): Lift `usePresetData` out of `useAxisState`**

Instead of `useAxisState` running `usePresetData` internally and syncing via effects:

- Move the `usePresetData` calls up into `TagCoOccurrenceGrid.tsx` (or a custom hook at the same level)
- When preset changes, directly await the fetch result and dispatch `SET_TAGS` atomically
- Use a `useEffect` that watches `state.x.preset` and `state.y.preset`, then fetches and sets in one go

This eliminates the intermediate loading sync effects and the stale-data window.

**Option B: Add a version/timestamp to each axis state**

Each `SELECT_PRESET` dispatch stamps a `fetchVersion: number` on the axis. The fetch result is only applied if its `fetchVersion` matches the current state. This is a standard "stale closure cancellation" pattern.

Prefer Option A — simpler, less state.

#### Fix 2: Allow same value on both axes

Remove the `existsOnOther` check from `ADD_MANUAL_TAG`. A same tag on both X and Y is valid (diagonal analysis). Keep the duplicate-within-same-axis check (don't add the same tag twice to X).

Update `ManualTagSelector.tsx` accordingly: the "Add to X" button should be disabled only if the tag already exists on X (not if it exists on Y), and vice versa.

#### Fix 3: Fix mood TagSpec key handling

In `usePresetData.ts`, the mood preset sends:

```typescript
const moodTags: TagSpec[] = response.tag_keys.map((moodValue) => ({
  key: fetchStrategy.tagKey ?? "nom:mood-*",  // "nom:mood-*" 
  value: moodValue,
}));
```

In the service (`analytics_svc.py`), the key is checked with:

```python
if key.startswith("nom:mood-"):
    tier = key[4:]  # "mood-strict"
```

But `"nom:mood-*"` does NOT start with `"nom:mood-"` in a real tier sense — wait, actually `"nom:mood-*"` DOES start with `"nom:mood-"`. But `tier = key[4:]` = `"mood-*"` — then `mood_specs["mood-*"] = [values]`. Then the query uses `rel = f"nom:{tier}"` = `"nom:mood-*"` — and AQL queries for `tag.rel == "nom:mood-*"` which would match nothing (tags use `nom:mood-strict`, `nom:mood-regular`, etc., not the wildcard literal).

Actually wait — let me re-read. `fetchStrategy.moodTier` is set to `"mood-strict"` for the mood preset. And in the fetch code:

```typescript
const moodTier = fetchStrategy.moodTier ?? "mood-strict";
const response = await getMoodValues(moodTier, maxValues);
// ...
const moodTags: TagSpec[] = response.tag_keys.map((moodValue) => ({
  key: fetchStrategy.tagKey ?? "nom:mood-*",  // "nom:mood-*"!!
  value: moodValue,
}));
```

The `key` sent to the backend is `"nom:mood-*"`, but the backend service splits on `"nom:mood-"` prefix — so `tier = "mood-*"`, and then it queries with `rel = "nom:mood-*"` which doesn't exist. The correct key to send would be `"nom:mood-strict"` (matching the tier that was actually fetched).

**Fix:** In `usePresetData.ts`, set `key` to the actual tier key (`"nom:mood-strict"`) rather than the wildcard pattern.

---

## Architecture

All changes are **frontend-only**, within the `TagCoOccurrenceGrid` component folder plus `usePresetData.ts`.

No backend, service, workflow, persistence, or DTO changes needed.

---

## Files to Change

 | File | Changes |
 | --- | --- |
 | `frontend/src/features/analytics/components/TagCoOccurrenceGrid/useAxisState.ts` | Rewrite data flow to eliminate race conditions |
 | `frontend/src/features/analytics/components/TagCoOccurrenceGrid/usePresetData.ts` | Fix mood tag key to use actual tier (not wildcard) |
 | `frontend/src/features/analytics/components/TagCoOccurrenceGrid/types.ts` | Minor: possibly update mood preset fetchStrategy tagKey |
 | `frontend/src/features/analytics/components/TagCoOccurrenceGrid/ManualTagSelector.tsx` | Fix cross-axis uniqueness check |
 | `frontend/src/features/analytics/components/TagCoOccurrenceGrid/TagCoOccurrenceGrid.test.tsx` | Update/add tests for the fixed behavior |

---

## Non-Goals

- Backend changes (backend is correct)
- Adding new preset types
- Changing the visual design of the grid
- Performance optimization of the AQL queries
