# API Restructure — Implementation Plans

**Design Document:** [DD-api-restructure](../../pending/DD-api-restructure.md)

## Plans

 | Plan | Title | Steps | Dependencies |
 | ------ | ------- | ------- | -------------- |
 | A | Delete Dead Code | 7 | None |
 | B | Bug Fixes | — | None (independent of A) |
 | C | Merge Calibration Endpoints | 18 | A |
 | D1 | Rename Infrastructure + Simple Routers | 10 | A, B, C |
 | D2 | Rename Library Router | 9 | D1 |
 | E | Rename Domain Routers + Endpoint Moves | 10 | D2 |
 | F | Cleanup & Verification | — | D1, D2, E |

## Dependency Graph

```
A (delete dead code) ──┐
                       ├─→ C (merge calibration) ─┐
B (bug fixes) ─────────┘                         │
                                                 └─→ D1 (infra + simple routers)
                                                      └─→ D2 (library router)
                                                           └─→ E (domain routers + moves)
                                                                └─→ F (cleanup & verification)
```

## Notes

- Plan A is the safest first step — pure deletion of confirmed dead code
- Plans A and B are independent and can execute in parallel
- Plans D1, D2, E implement combined DD Phases 4+5 (backend URL restructure + frontend migration)
- Each D/E plan pairs backend renames with frontend URL updates in lockstep
- Plan C handles ALL calibration restructuring; D1/D2/E skip calibration
- Endpoint moves (work-status, recent-activity) happen in Plan E
- Plan F is the final verification pass (Phase 6 from the DD)
