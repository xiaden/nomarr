---
name: Frontend Layer
description: Auto-applied when working with frontend/ - React + TypeScript UI
applyTo: frontend/**
---

# Frontend Layer

**Location:** `frontend/` (separate from Python backend)

**Stack:** React 19 · TypeScript · Vite · MUI

---

## Terminal Commands

Use `Push-Location`/`Pop-Location` to run npm commands without changing the working directory:

```powershell
Push-Location frontend; npm run lint; Pop-Location
Push-Location frontend; npm run build; Pop-Location
```

**Never use `cd frontend`** - it changes the terminal's working directory permanently.

---

## Required Verification

After ANY frontend change, run:

```powershell
Push-Location frontend; npm run lint; npm run build; Pop-Location
```

The `build` script runs `tsc -b` (type-check) then Vite build.

**Do not complete frontend work until both pass.**

---

## Structure

```
frontend/src/
├── main.tsx           # Entry point
├── App.tsx            # Root component
├── theme.ts           # MUI theme
├── components/        # Shared UI (layout, widgets)
├── features/          # Feature modules (auth, library, analytics, ...)
├── hooks/             # Custom React hooks
├── router/            # Route definitions
└── shared/            # API client, types, utilities
    ├── api/           # Typed backend client (domain-split modules)
    │   ├── index.ts   # Re-exports all domain modules
    │   ├── client.ts  # Base HTTP client, ApiError, helpers
    │   ├── library.ts # Library CRUD, scan, reconcile
    │   ├── files.ts   # File search, tag queries
    │   ├── tags.ts    # Tag operations
    │   ├── ml.ts      # ML model status
    │   ├── processing.ts  # Processing pipeline
    │   ├── calibration.ts # Calibration endpoints
    │   ├── analytics.ts   # Analytics queries
    │   └── ...        # Other domain modules
    ├── types.ts       # TypeScript interfaces
    └── auth.ts        # Session utilities
```

---

## Rules

### TypeScript

- Strict mode - no `any`
- Explicit return types on exports
- Interface for object shapes, type for unions

### React

- Functional components only
- Feature-based folders (not type-based)
- Hooks for state management

### MUI

- Use MUI components, not raw HTML
- Use `sx` prop, not inline styles
- Reference theme tokens, don't hardcode colors

---

## API Client

Backend calls use domain-specific modules in `shared/api/`:

```typescript
// Import from domain module directly
import { getProcessingStatus } from "@/shared/api/processing";
import { list, create } from "@/shared/api/library";

// Or import from the barrel for convenience
import { getProcessingStatus, list } from "@/shared/api";
```

Adding endpoints:

1. Add TypeScript interfaces to `shared/types.ts` (or co-locate in the domain module)
2. Add the fetch function to the appropriate `shared/api/<domain>.ts` module
3. Re-export from `shared/api/index.ts` if not already covered by a wildcard re-export

---

## Completion Checklist

1. ☐ `npm run lint` passes
2. ☐ `npm run build` passes
3. ☐ No `console.log` in committed code
4. ☐ No hardcoded URLs

---

## Validation Tool

**Run after every frontend change:**

```python
lint_project_frontend()
```

Zero errors from ESLint and TypeScript is the only acceptable state.
