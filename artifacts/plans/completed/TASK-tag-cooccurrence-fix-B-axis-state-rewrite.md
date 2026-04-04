# Task: Rewrite useAxisState Data Flow to Fix Race Conditions on Preset Change

## Problem Statement

`useAxisState.ts` calls `usePresetData(state.x.preset)` and `usePresetData(state.y.preset)` at the top of the hook, then syncs their results into the reducer via 4 separate `useEffect` blocks. This architecture creates a race condition when the user switches presets:

1. `SELECT_PRESET` is dispatched — `axis.tags = []`, `axis.loading = true`.
2. `usePresetData` re-runs with the new `presetId`, starting an async fetch.
3. Before the new fetch completes, there is a React render cycle in which `usePresetData.tags` still holds the **old preset's values** (non-empty). The tag-sync effect fires and dispatches `SET_TAGS` with stale data.
4. `buildMatrix` sees non-empty tags and builds the matrix with the wrong preset's values.

Fix: remove `usePresetData` from `useAxisState` entirely. Convert it to a plain async function `fetchPresetTags`. Move preset fetching into a `useEffect` per axis in `TagCoOccurrenceGrid.tsx`, using a fetch-version counter to discard stale results.

**Prerequisite:** Plan A (`TASK-tag-cooccurrence-fix-A-mood-key-same-axis.md`) must be completed first. That plan corrects the mood key fallback (`"nom:mood-strict"`) and removes the `existsOnOther` uniqueness check from `ADD_MANUAL_TAG`.

**Scope:** frontend-only, all files under `frontend/src/features/analytics/components/TagCoOccurrenceGrid/`. No backend changes. No API contract changes. No `axisReducer` action-type changes. No `GridAxesState` shape changes.

## Phases

### Phase 1: Convert usePresetData to a Plain Async Helper

- [x] Rewrite `usePresetData.ts`: delete the `usePresetData` hook and the `UsePresetDataResult` interface entirely. Replace with a single exported async function `fetchPresetTags(presetId: PresetId): Promise<TagSpec[]>` that contains all the fetch logic from the current `fetchData` callback (mood branch using `getMoodValues`, standard branch using `getUniqueTagValues`, manual branch returns `[]`). The function should throw on fetch error (remove the internal `try/catch`'s `setError` calls — let the caller handle errors). Remove `useState`, `useCallback`, `useEffect` imports since no hook remains.
    **Note:** 4 transient TS errors remain after this step (2x TS2305 from useAxisState.ts and test file still importing deleted usePresetData hook; 2x TS7006 cascading from those). All resolved by Phases 2-4 as planned. The new fetchPresetTags function itself compiles cleanly.

### Phase 2: Remove usePresetData Coupling from useAxisState

- [x] In `useAxisState.ts`, remove the `import { usePresetData } from "./usePresetData"` line and remove the two declarations `const xPresetData = usePresetData(state.x.preset)` and `const yPresetData = usePresetData(state.y.preset)`. Remove all 4 `useEffect` sync blocks (x tags+error, y tags+error, x loading, y loading). Remove `useEffect` from the React import line (only `useReducer` and `useCallback` remain). Add `dispatch: React.Dispatch<AxisAction>` to the `UseAxisStateResult` interface and include `dispatch` in the returned object.

### Phase 3: Wire Preset Fetch Effect in TagCoOccurrenceGrid

- [x] In `TagCoOccurrenceGrid.tsx`, add `useRef` to the React import. Add `import { fetchPresetTags } from "./usePresetData"`. Destructure `dispatch` from the `useAxisState()` call. Add two refs: `const xFetchVersion = useRef(0)` and `const yFetchVersion = useRef(0)`.
- [x] Add a `useEffect` watching `[state.x.preset, dispatch]` that: increments `xFetchVersion.current`, captures the new version; if `state.x.preset === "manual"` returns early (select-preset already cleared tags); otherwise dispatches `{ type: "SET_LOADING", axis: "x", loading: true }`, calls `fetchPresetTags(state.x.preset)`, and on resolution checks `xFetchVersion.current === version` before dispatching `{ type: "SET_TAGS", axis: "x", tags }` or `{ type: "SET_ERROR", axis: "x", error: message }` on rejection. Mark the effect callback as `void` (do not return the promise).
- [x] Add an equivalent `useEffect` watching `[state.y.preset, dispatch]` using `yFetchVersion` for the Y axis, mirroring the X-axis logic exactly.

### Phase 4: Update Tests and Validate

- [x] In `TagCoOccurrenceGrid.test.tsx`, confirm `getMoodValues` is present in the `vi.mock("../../../../shared/api/files", …)` factory (added by Plan A); if not, add `getMoodValues: vi.fn().mockResolvedValue({ tag_keys: ["aggressive", "happy"], count: 2 })`. Add a `describe("preset switching")` block with one test: render `<TagCoOccurrenceGrid />`, wait for initial genre data to settle (`await screen.findByRole("table")`), find and click the X-axis Mood preset button, await re-render, assert `getMoodValues` was called once, assert `getTagCoOccurrence` was called with an `x` array whose entries all have `key: "nom:mood-strict"`.
    **Notes:** Replaced usePresetData hook import with fetchPresetTags function. Rewrote mood preset key test to call fetchPresetTags directly (no renderHook). Added describe("preset switching") block with fireEvent.click on first Mood button, waitFor getMoodValues call, waitFor getTagCoOccurrence call, assertion on lastCall x tags. Added fireEvent, analytics and files imports for vi.mocked usage. Cross-axis manual tags test unchanged — useAxisState initial loading is false so no side-effect issues.
- [x] Run `lint_project_frontend()` and fix all reported TypeScript and ESLint errors until the tool returns zero errors.
    **Notes:** Ran lint_project_frontend after P4-S1 edits. Found 4 ESLint import/order violations: analytics and files imports were placed after test/render within the same relative import group. Fixed by reordering — analytics and files come first (alphabetically by path), then test/render and TagCoOccurrenceGrid, then local ./useAxisState and ./usePresetData. Second lint run returned zero errors for both ESLint and TypeScript.

## Completion Criteria

- `usePresetData.ts` exports only `fetchPresetTags(presetId): Promise<TagSpec[]>`; no hook, no stateful imports
- `useAxisState.ts` has no `usePresetData` import, no `usePresetData()` calls, no effect-sync blocks; exports `dispatch` in `UseAxisStateResult`
- `TagCoOccurrenceGrid.tsx` fetches preset tags via two `useEffect` blocks (one per axis) with version-counter stale-result guards
- `buildMatrix` `useEffect` in `TagCoOccurrenceGrid.tsx` is unchanged
- `axisReducer` and all `AxisAction` types are unchanged
- `GridAxesState` / `AxisState` shape is unchanged
- Switching presets does not dispatch `SET_TAGS` with the previous preset's values
- `TagCoOccurrenceGrid.test.tsx` preset-switching test passes: `getMoodValues` called, `getTagCoOccurrence` receives mood `TagSpec[]` with `key: "nom:mood-strict"`
- `lint_project_frontend()` reports zero errors

## References

- Design doc: `plans/dev/design-tag-cooccurrence-fix.md`
- Plan A (prerequisite): `plans/TASK-tag-cooccurrence-fix-A-mood-key-same-axis.md`
- Contracts ledger: included in task request (2026-03-22, after Plan A)
