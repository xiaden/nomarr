---
applyTo: vscode-ext/**/src/outcome/**
---

# Outcomes (Deterministic Status)

This folder contains deterministic outcome types for subagent operations.

## Status Meaning
- SUCCESS: work completed and validated
- FAILED: attempted but invalid (schema, lint, parse, etc.)
- BLOCKED: cannot proceed (missing workspace/model/file, external dependency)

## Rules
- No retries in this module.
- No silent conversion between statuses.
- Preserve debugging details (category, message, details).
- Keep module pure (types/helpers only; no VS Code / Node deps).

---

## Reference (non-prescriptive)

### Helpers
```typescript
import { success, failed, blocked, wrapOutcome } from '../outcome';
return success(data);
return failed('SCHEMA_INVALID', 'Missing field', { details });
return blocked('MODEL_UNAVAILABLE', 'No Copilot model');
const outcome = await wrapOutcome(() => riskyOp(), 'PYTHON_ERROR');
```

### FailureCategory
`SCHEMA_INVALID`, `LINT_FAILED`, `MODEL_UNAVAILABLE`, `PYTHON_ERROR`, `FILE_NOT_FOUND`, `PARSE_ERROR`, `TIMEOUT`, `CANCELLED`, `UNKNOWN`
