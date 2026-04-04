# Task: Dashboard Setup Pipeline

## Problem Statement

New Nomarr users land on the Dashboard after login with no guidance on what to do next. The app has a sequential setup pipeline (add library → scan → tag → calibrate → browse insights) but nothing surfaces this flow. Users must discover Admin, Config, and Calibration pages through trial and error.

This task adds a vertical stepper pipeline widget to the Dashboard that:

- Shows the full setup pipeline as an accordion with MUI `Stepper`
- Completed steps collapse with checkmarks and summary stats
- The current/next step expands with the relevant action button or inline component
- Future steps are collapsed and dimmed
- Pipeline state is derived from existing API data — no new backend work

**Pipeline steps and their state detection:**

| Step | Detect Complete | Detect In-Progress | Action Component |
|------|----------------|-------------------|------------------|
| Add Library | `list()` returns ≥1 library | — | Inline `ServerFilePicker` + create API call |
| Scan Library | Library has `scannedAt` set | `workStatus.is_scanning` | "Scan" button → `scan(libraryId)` |
| Tag Files | `pending_files === 0 && processed_files > 0` | `workStatus.is_processing` | Progress bar (already fetched by Dashboard) |
| Calibrate | `calibrationStatus.last_run > 0` | `histogramStatus.running` | "Run Calibration" button → `startHistogramCalibration()` |
| Browse Insights | Always last, never "complete" | — | "Explore" nav link to /insights |

**Existing APIs already fetched by DashboardPage:** `getWorkStatus()`, `getStats()`, `getRecentActivity()`. Additional calls needed: `list()` (libraries), `getStatus()` (calibration). Both are lightweight.

**Frontend stack:** React 19, MUI 7 (`Stepper`, `Step`, `StepLabel`, `StepContent`, `Accordion`), dark theme.

**Existing components to reuse:**

- `ServerFilePicker` — directory browser for library path selection
- `ProgressBar` — shared UI component
- `Panel` / `SectionHeader` — consistent styling
- `ActionCard` — card with title, description, and action button
- API functions: `library.list()`, `library.create()`, `library.scan()`, `calibration.startHistogramCalibration()`, `calibration.getStatus()`

## Phases

### Phase 1: Pipeline State Hook

- [ ] Create `usePipelineState` hook in `frontend/src/features/dashboard/hooks/` that fetches libraries, work status, and calibration status, then derives the active step index and per-step state (complete/active/pending)
- [ ] Define `PipelineStep` type with fields: id, label, status (complete/active/pending), summary text, and action config
- [ ] Handle loading and error states, poll work status when pipeline has an active in-progress step
- [ ] Verify lint and TypeScript pass

### Phase 2: Pipeline Component and Integration

- [ ] Create `SetupPipeline` component in `frontend/src/features/dashboard/components/` using MUI vertical `Stepper` wrapped in an `Accordion`
- [ ] Implement step content for each pipeline stage: Add Library (ServerFilePicker + create), Scan (scan button), Tag (progress bar), Calibrate (run button), Browse (nav link)
- [ ] Integrate `SetupPipeline` into `DashboardPage` above existing content, share fetched data between pipeline and existing dashboard sections to avoid duplicate API calls
- [ ] Build frontend and verify pipeline renders correctly across all states

## Completion Criteria

- Pipeline widget visible on Dashboard, wrapped in collapsible accordion
- Correctly detects current pipeline stage from live API data
- Each step shows contextual action (button, picker, progress, or link)
- Completed steps show checkmark + summary, future steps are dimmed
- No duplicate API calls — data shared with existing Dashboard fetches
- All lint and TypeScript checks pass, frontend builds without errors

## References

- Dashboard page: `frontend/src/features/dashboard/DashboardPage.tsx`
- Library APIs: `frontend/src/shared/api/library.ts` — `list()`, `create()`, `scan()`
- Calibration APIs: `frontend/src/shared/api/calibration.ts` — `getStatus()`, `startHistogramCalibration()`
- Processing API: `frontend/src/shared/api/processing.ts` — `getWorkStatus()`
- ServerFilePicker: `frontend/src/shared/components/ServerFilePicker.tsx`
- Shared UI: `frontend/src/shared/components/ui/` (Panel, ProgressBar, ActionCard)
- MUI Stepper: `@mui/material` — Stepper, Step, StepLabel, StepContent
