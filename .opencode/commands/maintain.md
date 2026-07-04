---
description: Run iterative code maintenance across 8 skills with QA validation and git rollback safety
agent: maintenance-manager
subtask: true
---

You are the maintenance manager. Coordinate 8 maintenance workers through iterative rounds to clean up the Nomarr codebase. Read your agent instructions carefully — they contain the full workflow, skill list, QA validation process, and Nomarr-specific conventions.

**IMPORTANT — Before spawning any workers:** create a baseline commit so rollbacks are clean. Run:

```bash
git add -A && git commit --no-verify -m "Maintenance: pre-round baseline" || true
```

(The `|| true` handles the case where there's nothing to commit.)

Then record the SHA (`git rev-parse HEAD`) as BASE_SHA, and spawn all 8 workers in parallel.
