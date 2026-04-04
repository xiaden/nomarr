# Task: Fix Mood TagSpec Key + Remove Cross-Axis Uniqueness Restriction

## Problem Statement

The Tag Co-Occurrence Grid has two bugs in its frontend code (no backend changes needed):

**Bug 1 — Wrong mood key fallback in `usePresetData.ts`:**
The mood preset `TagSpec` is built with `key: fetchStrategy.tagKey ?? "nom:mood-*"` (line 61).
`PRESET_METADATA.mood.fetchStrategy.tagKey` is already `"nom:mood-strict"` in `types.ts`, so the
`?? "nom:mood-*"` branch is dead code — but it contains the wrong value and a misleading comment
claiming "Backend will use CONTAINS matching on the mood tag tuple strings" (which is not how the
backend works). The comment and fallback must be corrected so the code is not misleading and no
future regression can re-introduce `"nom:mood-*"`.

**Bug 2 — Cross-axis uniqueness blocks valid diagonal analysis:**
`ADD_MANUAL_TAG` in `useAxisState.ts` (lines 88–94) prevents the same `{key, value}` from
appearing on both X and Y axes. This incorrectly blocks diagonal co-occurrence analysis
(e.g., moods-vs-moods), which is a valid and valuable use case. The same tag on both axes
produces a self-co-occurrence diagonal that is expected and correct.
`ManualTagSelector.tsx` enforces the same restriction visually via `isTagInEitherAxis`
(lines 115–119) used in `canAddToX` / `canAddToY` (lines 122–125).

Scope is limited to: `usePresetData.ts`, `useAxisState.ts`, `ManualTagSelector.tsx`,
`TagCoOccurrenceGrid.test.tsx`. No backend Python changes. No API contract changes.
No rewrite of `useAxisState` data flow (that is Part B).

## Phases

### Phase 1: Fix Mood Key Fallback

- [x] In `usePresetData.ts` lines 58–62, remove the two-line comment "Build TagSpecs: key = `nom:mood-*` pattern…Backend will use CONTAINS matching…" and replace the fallback in the `key` expression from `fetchStrategy.tagKey ?? "nom:mood-*"` to `fetchStrategy.tagKey ?? "nom:mood-strict"`, keeping the logic identical. Confirm `fetchStrategy.tagKey` is already `"nom:mood-strict"` from `PRESET_METADATA` so the fallback is unreachable.
    **Note:** Removed misleading 2-line comment and replaced `?? "nom:mood-*"` with `?? "nom:mood-strict"`. Confirmed `PRESET_METADATA.mood.fetchStrategy.tagKey` is already `"nom:mood-strict"` in types.ts (line 61), so the fallback remains unreachable but no longer contains the incorrect wildcard value.

### Phase 2: Remove Cross-Axis Uniqueness Restriction

- [x] In `useAxisState.ts` `ADD_MANUAL_TAG` case, delete the 5-line `existsOnOther` block: `const otherAxis = action.axis === "x" ? "y" : "x";`, `const existsOnOther = state[otherAxis].tags.some(…);`, and `if (existsOnOther) return state;` (lines 88–94). Leave the within-axis `isDuplicate` check untouched.
    **Impl:** Removed the 6-line existsOnOther block (lines 91–96 in original). Also fixed a double blank line that appeared after removal.
- [x] In `ManualTagSelector.tsx`, replace the `isTagInEitherAxis` function (lines 115–119) with two single-axis helpers: `const isTagOnX = (key: string, value: string): boolean => xTags.some((t) => t.key === key && t.value === value);` and `const isTagOnY = (key: string, value: string): boolean => yTags.some((t) => t.key === key && t.value === value);`.
- [x] In `ManualTagSelector.tsx`, update `canAddToX` (line 122) to replace `!isTagInEitherAxis(selectedKey, selectedValue)` with `!isTagOnX(selectedKey, selectedValue)`, and update `canAddToY` (line 124) to replace `!isTagInEitherAxis(selectedKey, selectedValue)` with `!isTagOnY(selectedKey, selectedValue)`.
    **Impl:** S2 and S3 applied in a single atomic replacement. isTagInEitherAxis removed; isTagOnX and isTagOnY added as inline arrow functions. canAddToX and canAddToY updated accordingly.

### Phase 3: Test Coverage and Lint Validation

- [x] In `TagCoOccurrenceGrid.test.tsx`, add `getMoodValues: vi.fn().mockResolvedValue({ tag_keys: ["aggressive", "happy"], count: 2 })` to the `vi.mock("../../../../shared/api/files", …)` factory alongside the existing `getUniqueTagKeys` and `getUniqueTagValues` entries.
- [x] Add a `describe("mood preset key")` block in `TagCoOccurrenceGrid.test.tsx` using `renderHook(() => usePresetData("mood"))` from `@testing-library/react`. Import `usePresetData` from `./usePresetData` and `getMoodValues` from the mocked module. Assert that after the hook resolves, every tag in the result has `key === "nom:mood-strict"` and no tag has `key === "nom:mood-*"`.
- [x] Add a `describe("cross-axis manual tags")` block in `TagCoOccurrenceGrid.test.tsx` using `renderHook(() => useAxisState())` (import `useAxisState` from `./useAxisState`). Dispatch `ADD_MANUAL_TAG` for `{ axis: "x", tag: { key: "genre", value: "Rock" } }` then `ADD_MANUAL_TAG` for `{ axis: "y", tag: { key: "genre", value: "Rock" } }`. Assert `result.current.state.x.tags` contains `{ key: "genre", value: "Rock" }` and `result.current.state.y.tags` also contains `{ key: "genre", value: "Rock" }`.
- [x] Run `lint_project_frontend()` and fix all reported TypeScript and ESLint errors until the tool returns zero errors.
    **LintResult:** Final lint run: status=clean, zero ESLint and TypeScript errors. ConfigSettings.tsx TS2304 (PP_TYPE_KEYS undefined) was a stale/pre-existing error in a git-modified file — the code that used PP_TYPE_KEYS had already been removed by a prior refactor, so the fix was confirming no change was needed.

## Completion Criteria

- `usePresetData.ts` mood branch: `key` expression uses `fetchStrategy.tagKey ?? "nom:mood-strict"` with no reference to `"nom:mood-*"` anywhere in the file
- `useAxisState.ts` `ADD_MANUAL_TAG` case: no `existsOnOther` variable, no cross-axis lookup; only the within-axis `isDuplicate` guard remains
- `ManualTagSelector.tsx`: `isTagInEitherAxis` is gone; `canAddToX` gates only on `xTags`; `canAddToY` gates only on `yTags`
- `TagCoOccurrenceGrid.test.tsx`: mood key test passes asserting `key: "nom:mood-strict"`; cross-axis test passes asserting same tag exists on both axes
- `lint_project_frontend()` reports zero errors

## References

- Design doc: `plans/dev/design-tag-cooccurrence-fix.md`
- Contracts ledger: included in task request (2026-03-22 initial)
- Part B (useAxisState data flow rewrite): separate plan
