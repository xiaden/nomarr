````markdown
# Feature Archival Protocol

How to close out a completed feature execution: generate a completion manifest, move all artifacts to `plans/completed/`, and verify clean state.

---

## Completion Manifest

After all plans pass review and the ledger is updated, generate `COMPLETION.md` in the `{feature}-parts/` directory. This is the audit trail — anyone reopening this feature later starts here.

### Template

```markdown
# {Feature} — Completion Manifest

**Completed:** {YYYY-MM-DD}
**Design doc:** `design-{feature}.md`
**Parts README:** `{feature}-parts/README.md`
**Contracts ledger:** `{feature}-parts/CONTRACTS.md`

---

## Execution Summary

| Plan | Title | Rounds | Fix Plans | Status |
|---|---|---|---|---|
| A | {title} | {review rounds} | {fix plan names or "—"} | PASS |
| B | {title} | {review rounds} | {fix plan names or "—"} | PASS |
...

## Design Deviations

{Extract from CONTRACTS.md Decisions table. List only deviations from the original
design doc — things that changed during implementation.
If none: "Implementation matched design. No deviations."}

## Key Decisions

{Architectural decisions made during execution that aren't in the design doc.
Examples: "Used TypedDict instead of dataclass for X because...",
"Merged Phase 2 and 3 of Plan B due to trivial step count."
If none: "No significant decisions beyond what the design doc specified."}

## Files Created/Modified

{Deduplicated list of files touched across all plans. Group by layer.
Pull from review reports and plan annotations.

Example:
### Persistence
- `nomarr/persistence/database/play_history_aql.py` (new)

### Workflows  
- `nomarr/workflows/scrobble_ingest_wf.py` (new)

### Services
- `nomarr/services/domain/scrobble_svc.py` (new)

### Interfaces
- `nomarr/interfaces/api/v1/scrobble_if.py` (new)

### Helpers
- `nomarr/helpers/dto/scrobble_dto.py` (new)

### Frontend
- `frontend/src/features/scrobble/ScrobblePage.tsx` (new)
}

## Final Lint Status

- Backend: PASS (zero errors)
- Frontend: {PASS | N/A}
```

### Populating the Manifest

| Field | Source |
|---|---|
| Execution Summary | `plan_read` on each plan — check all steps complete. Review round count from review dispatch history |
| Design Deviations | CONTRACTS.md Decisions table — filter to deviation-type entries |
| Key Decisions | Plan step annotations (`plan_complete_step` annotations) + review findings that led to changes |
| Files Created/Modified | Review reports' "Files Reviewed" sections, deduplicated |
| Final Lint Status | Run `lint_project_backend()` (and `lint_project_frontend()` if applicable) one final time |

---

## Move Protocol

Move artifacts from active directories to `plans/completed/` using `edit_file_move`.

### Artifacts to Move

| Source | Destination | Notes |
|---|---|---|
| `plans/TASK-{feature}-*.md` | `plans/completed/TASK-{feature}-*.md` | All plan files — includes fix plans |
| `plans/dev/{feature}-parts/` | `plans/completed/{feature}-parts/` | README, CONTRACTS, COMPLETION manifest |
| `plans/dev/design-{feature}.md` | `plans/completed/design-{feature}.md` | Original design doc |

### Move Order

1. **Plans first** — move all `TASK-{feature}-*.md` files
2. **Design doc** — move `design-{feature}.md`
3. **Parts directory** — move `{feature}-parts/` (contains README, CONTRACTS, COMPLETION)

Parts directory goes last because it contains the completion manifest — you want it written and committed before the move.

### Verification

After moving, confirm clean state:

```
# These should return no results:
plans/TASK-{feature}-*.md          → none remain
plans/dev/{feature}-parts/         → directory gone
plans/dev/design-{feature}.md      → file gone

# These should exist:
plans/completed/TASK-{feature}-*.md              → all plans present
plans/completed/{feature}-parts/COMPLETION.md    → manifest exists
plans/completed/{feature}-parts/CONTRACTS.md     → ledger preserved
plans/completed/{feature}-parts/README.md        → decomposition preserved  
plans/completed/design-{feature}.md              → design doc preserved
```

---

## Standalone Plan Archival

Not all plans are part of multi-part features. Single plans (`plans/TASK-{name}.md` without letter suffixes) also need archival.

**For standalone plans:**
1. No COMPLETION.md needed — the plan's own checkboxes and annotations are the audit trail
2. Move: `plans/TASK-{name}.md` → `plans/completed/TASK-{name}.md`
3. No parts directory or design doc to move

---

## Auditability Guide

When revisiting a completed feature, read artifacts in this order:

1. **`COMPLETION.md`** — What happened, what deviated, what was decided
2. **`design-{feature}.md`** — Original intent
3. **`{feature}-parts/README.md`** — How it was decomposed
4. **`{feature}-parts/CONTRACTS.md`** — What was actually built (signatures, schemas)
5. **Individual `TASK-*.md` plans** — Step-by-step implementation details with annotations
````
