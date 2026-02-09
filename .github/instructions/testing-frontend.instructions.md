---
name: Frontend Testing
description: Guidelines for writing and running frontend tests with Vitest and React Testing Library
applyTo: "frontend/**/*.test.ts,frontend/**/*.test.tsx"
---

# Frontend Testing

**Purpose:** Define how to write, organize, and run frontend tests for the Nomarr React UI.

**Stack:** Vitest · React Testing Library · jsdom

---

## Quick Reference

```powershell
# Run all frontend tests
Push-Location frontend; npm test; Pop-Location

# Watch mode (re-runs on file change)
Push-Location frontend; npm run test:watch; Pop-Location

# Run a specific test file
Push-Location frontend; npx vitest run src/features/calibration/CalibrationPage.test.tsx; Pop-Location

# Run tests matching a name pattern
Push-Location frontend; npx vitest run --reporter=verbose -t "progress bar"; Pop-Location
```

**Never use `cd frontend`** — it changes the terminal's working directory permanently.

---

## Directory Structure

Test files live **next to the code they test** (co-located):

```
frontend/src/
├── features/
│   ├── calibration/
│   │   ├── CalibrationPage.tsx
│   │   └── CalibrationPage.test.tsx      # Component test
│   └── library/
│       ├── LibraryPage.tsx
│       └── LibraryPage.test.tsx
├── hooks/
│   ├── usePolling.ts
│   └── usePolling.test.ts                # Hook test
├── shared/
│   ├── api/
│   │   ├── calibration.ts
│   │   └── calibration.test.ts           # API client test
│   └── utils/
│       ├── formatters.ts
│       └── formatters.test.ts            # Utility test
└── test/
    └── setup.ts                          # Global test setup
```

### Naming Conventions

- **Files:** `<ModuleName>.test.ts` or `<ComponentName>.test.tsx`
- **describe blocks:** Match the module/component name
- **it/test blocks:** Describe expected behavior from the user's perspective

---

## Configuration

### vitest.config.ts

```typescript
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
});
```

### package.json scripts

```json
"test": "vitest run",
"test:watch": "vitest"
```

### src/test/setup.ts

```typescript
import '@testing-library/jest-dom/vitest';
```

---

## Test Categories

### 1. Utility / Pure Function Tests

Highest value per test. No rendering, no async, no mocking.

```typescript
import { describe, it, expect } from 'vitest';
import { formatDuration, formatPercentage } from './formatters';

describe('formatDuration', () => {
  it('formats seconds to mm:ss', () => {
    expect(formatDuration(125)).toBe('2:05');
  });

  it('handles zero', () => {
    expect(formatDuration(0)).toBe('0:00');
  });
});
```

### 2. Hook Tests

Test custom hooks in isolation using `renderHook`.

```typescript
import { renderHook, act } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { usePolling } from './usePolling';

describe('usePolling', () => {
  it('calls the callback at the specified interval', () => {
    vi.useFakeTimers();
    const callback = vi.fn().mockResolvedValue(undefined);

    renderHook(() => usePolling(callback, 5000));

    act(() => vi.advanceTimersByTime(5000));
    expect(callback).toHaveBeenCalledTimes(1);

    vi.useRealTimers();
  });
});
```

### 3. Component Tests

Test what the user sees and does, not internal state.

```typescript
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi } from 'vitest';
import { CalibrationStatus } from './CalibrationStatus';

describe('CalibrationStatus', () => {
  it('shows progress bar when generation is running', () => {
    render(
      <CalibrationStatus
        progress={{
          is_running: true,
          iteration: 2,
          total_iterations: 5,
          current_head: 'mood_happy',
          current_head_index: 3,
          total_heads: 12,
          sample_pct: 0.4,
          completed_heads: 0,
          remaining_heads: 0,
          last_updated: null,
        }}
      />,
    );

    expect(screen.getByText(/Iteration 2 of 5/)).toBeInTheDocument();
    expect(screen.getByText(/mood_happy/)).toBeInTheDocument();
  });

  it('shows completed state when not running', () => {
    render(
      <CalibrationStatus
        progress={{
          is_running: false,
          total_heads: 12,
          completed_heads: 12,
          remaining_heads: 0,
          last_updated: 1700000000000,
          iteration: null,
          total_iterations: null,
          current_head: null,
          current_head_index: null,
          sample_pct: null,
        }}
      />,
    );

    expect(screen.getByText(/12.*of.*12/)).toBeInTheDocument();
  });
});
```

### 4. API Client Tests

Test request construction and response shaping. Mock `fetch`, not the entire module.

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest';

describe('calibration API', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('fetches calibration progress', async () => {
    const mockResponse = { is_running: false, total_heads: 12 };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(mockResponse),
    });

    const { getGenerationProgress } = await import('./calibration');
    const result = await getGenerationProgress();

    expect(result.total_heads).toBe(12);
  });
});
```

---

## Mocking Patterns

### Mocking API responses for components

```typescript
vi.mock('../shared/api', () => ({
  api: {
    calibration: {
      getProgress: vi.fn().mockResolvedValue({ is_running: false }),
    },
  },
}));
```

### Mocking React Router

```typescript
import { MemoryRouter } from 'react-router-dom';

render(
  <MemoryRouter initialEntries={['/calibration']}>
    <CalibrationPage />
  </MemoryRouter>,
);
```

### Mocking MUI Theme

MUI components need a theme provider:

```typescript
import { ThemeProvider } from '@mui/material/styles';
import { theme } from '../../theme';

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}
```

Consider adding this as a shared test utility in `frontend/src/test/render.tsx`.

---

## What to Test

| Category | Priority | Examples |
|----------|----------|----------|
| **Shared utilities** | High | Formatters, parsers, transformers |
| **Custom hooks** | High | Polling, debounce, API state management |
| **API client functions** | Medium | Request construction, response parsing |
| **Display components** | Medium | Conditional rendering, data formatting |
| **Interactive components** | Medium | Form validation, button states |
| **Page-level components** | Low | Better covered by E2E tests |
| **Layout/styling** | Skip | Visual regression (not worth unit testing) |

### What NOT to Test

- MUI component internals (they have their own tests)
- Router navigation mechanics
- CSS property values
- Third-party library behavior

---

## Anti-Patterns

```typescript
// ❌ Testing implementation details
expect(component.state.isLoading).toBe(true);

// ✅ Testing user-visible behavior
expect(screen.getByRole('progressbar')).toBeInTheDocument();

// ❌ Snapshot testing everything
expect(container).toMatchSnapshot();

// ✅ Targeted assertions on what matters
expect(screen.getByText('12 of 12 heads')).toBeInTheDocument();

// ❌ Using getByTestId when better queries exist
screen.getByTestId('submit-button');

// ✅ Using accessible queries
screen.getByRole('button', { name: 'Submit' });
```

### Query Priority (React Testing Library)

1. `getByRole` — accessible name (best)
2. `getByLabelText` — form fields
3. `getByPlaceholderText` — input placeholders
4. `getByText` — visible text
5. `getByDisplayValue` — current input value
6. `getByTestId` — last resort

---

## Validation Checklist

Before committing frontend test code:

- [ ] Tests are co-located next to the source file
- [ ] Tests describe user-visible behavior, not implementation
- [ ] No `console.log` in test code
- [ ] Mocks are cleaned up in `beforeEach`/`afterEach`
- [ ] `npm test` passes
- [ ] `npm run lint` still passes
- [ ] `npm run build` still passes
