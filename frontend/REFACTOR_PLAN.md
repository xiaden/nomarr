# Frontend Refactor Plan

**Created:** January 17, 2026  
**Updated:** January 17, 2026  
**Scope:** Address styling inconsistencies, code organization, and UX improvements  
**Priority:** High → Medium → Low

---

## Phase 1: Consistency & Quick Wins (High Priority)

### 1.1 Migrate Pages to MUI + PageContainer

**Goal:** All pages should use `PageContainer`, MUI components, and consistent styling patterns.

**Files to update:**

| File | Current | Target |
|------|---------|--------|
| `features/admin/AdminPage.tsx` | Raw `<div>`, `<h1>`, inline styles | `PageContainer`, MUI `Typography`, `Stack` |
| `features/analytics/AnalyticsPage.tsx` | Raw `<div>`, inline styles | `PageContainer`, MUI components |
| `features/calibration/CalibrationPage.tsx` | Raw `<div>`, inline styles | `PageContainer`, MUI components |
| `features/config/ConfigPage.tsx` | Raw `<div>`, inline styles | `PageContainer`, MUI components |

**Pattern to follow (from DashboardPage/TaggerStatusPage):**
```tsx
import { Stack, Typography } from "@mui/material";
import { PageContainer, Panel, SectionHeader } from "@shared/components/ui";

export function ExamplePage() {
  return (
    <PageContainer title="Page Title">
      <Stack spacing={2.5}>
        <Panel>
          <SectionHeader title="Section" />
          {/* content */}
        </Panel>
      </Stack>
    </PageContainer>
  );
}
```

**Checklist:**
- [ ] AdminPage.tsx - Replace div/h1 with PageContainer/Typography
- [ ] AnalyticsPage.tsx - Replace div with PageContainer, wrap sections in Panel
- [ ] CalibrationPage.tsx - Replace div with PageContainer
- [ ] ConfigPage.tsx - Replace div with PageContainer

---

### 1.2 Split api.ts into Domain Modules

**Goal:** Break the 1169-line api.ts into manageable domain-specific modules. Delete old api.ts immediately—TypeScript errors guide remaining updates.

**Current:** `shared/api.ts` (1169 lines, all endpoints)

**Target structure:**
```
shared/api/
├── index.ts           # Re-exports all domain modules
├── client.ts          # All request concerns (see 1.2.1)
├── auth.ts            # login(), logout()
├── queue.ts           # listJobs(), getQueueStatus(), etc.
├── library.ts         # getStats(), list(), create(), etc.
├── analytics.ts       # getTagFrequencies(), etc.
├── calibration.ts     # getStatus(), generate(), apply(), etc.
├── navidrome.ts       # preview(), generateConfig(), etc.
├── metadata.ts        # listEntities(), etc.
├── tags.ts            # showTags(), removeTags(), etc.
├── config.ts          # get(), update(), etc.
├── processing.ts      # process(), batchProcess(), etc.
├── filesystem.ts      # browse(), etc.
└── worker.ts          # pause(), resume(), restart()
```

#### 1.2.1 client.ts - All Request Concerns

**File:** `shared/api/client.ts`

Contains all cross-cutting request logic:
- Base URL resolution
- Auth header injection (Bearer token)
- Consistent error normalization
- JSON parsing
- Optional `snakeToCamel` transform (opt-in initially via parameter)

```typescript
/**
 * API client utilities.
 * 
 * All request concerns centralized here:
 * - Base URL resolution
 * - Auth header injection
 * - Error normalization
 * - JSON parsing
 * - Optional case conversion
 */

import { clearSessionToken, getSessionToken } from "../auth";

/**
 * API base URL.
 * Empty string for production (same-origin).
 * Vite dev server proxies to backend.
 */
export const API_BASE_URL = "";

/**
 * Convert snake_case keys to camelCase recursively.
 */
export function snakeToCamel<T>(obj: unknown): T {
  if (Array.isArray(obj)) {
    return obj.map(snakeToCamel) as T;
  }
  if (obj !== null && typeof obj === "object") {
    return Object.entries(obj as Record<string, unknown>).reduce(
      (acc, [key, value]) => {
        const camelKey = key.replace(/_([a-z])/g, (_, letter) =>
          letter.toUpperCase()
        );
        acc[camelKey] = snakeToCamel(value);
        return acc;
      },
      {} as Record<string, unknown>
    ) as T;
  }
  return obj as T;
}

/**
 * Normalized API error with status code and message.
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: unknown
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export interface RequestOptions extends Omit<RequestInit, "body"> {
  body?: unknown;
  /** Convert response keys from snake_case to camelCase. Default: false */
  transformCase?: boolean;
}

/**
 * Generic request helper.
 * 
 * Handles:
 * - JSON serialization of body
 * - Auth header injection
 * - Error normalization (ApiError)
 * - 401/403 session clearing
 * - Optional snake_case → camelCase transform
 */
export async function request<T>(
  path: string,
  options: RequestOptions = {}
): Promise<T> {
  const { body, transformCase = false, ...fetchOptions } = options;
  const url = `${API_BASE_URL}${path}`;

  // Build headers
  const headers: Record<string, string> = {};

  if (fetchOptions.headers) {
    Object.assign(headers, fetchOptions.headers);
  }

  // JSON body handling
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
  }

  // Auth header injection
  const token = getSessionToken();
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  try {
    const response = await fetch(url, {
      ...fetchOptions,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });

    // Handle auth errors - clear session
    if (response.status === 401 || response.status === 403) {
      clearSessionToken();
      throw new ApiError(response.status, "Unauthorized");
    }

    // Handle other errors
    if (!response.ok) {
      let message = `HTTP ${response.status}: ${response.statusText}`;
      let detail: unknown;
      try {
        const errorData = await response.json();
        if (errorData.detail) {
          message = String(errorData.detail);
          detail = errorData;
        }
      } catch {
        // Response wasn't JSON
      }
      throw new ApiError(response.status, message, detail);
    }

    // Parse JSON response
    const json = await response.json();

    // Optional case transformation
    if (transformCase) {
      return snakeToCamel<T>(json);
    }

    return json as T;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    if (error instanceof Error) {
      throw new ApiError(0, error.message);
    }
    throw new ApiError(0, "Unknown error occurred");
  }
}

/**
 * Helper for GET requests.
 */
export function get<T>(path: string, options?: Omit<RequestOptions, "method">): Promise<T> {
  return request<T>(path, { ...options, method: "GET" });
}

/**
 * Helper for POST requests.
 */
export function post<T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">): Promise<T> {
  return request<T>(path, { ...options, method: "POST", body });
}

/**
 * Helper for PUT requests.
 */
export function put<T>(path: string, body?: unknown, options?: Omit<RequestOptions, "method" | "body">): Promise<T> {
  return request<T>(path, { ...options, method: "PUT", body });
}

/**
 * Helper for DELETE requests.
 */
export function del<T>(path: string, options?: Omit<RequestOptions, "method">): Promise<T> {
  return request<T>(path, { ...options, method: "DELETE" });
}
```

#### 1.2.2 Domain Module Pattern

Each domain module exports named functions directly:

**Example - shared/api/queue.ts:**
```typescript
/**
 * Queue API functions.
 * 
 * Import:
 *   import { listJobs, getQueueStatus } from "@shared/api/queue";
 */

import { get, post } from "./client";
import type { QueueJob, QueueSummary } from "../types";

export interface ListJobsParams {
  status?: "pending" | "running" | "done" | "error";
  limit?: number;
  offset?: number;
}

export interface ListJobsResponse {
  jobs: QueueJob[];
  total: number;
  limit: number;
  offset: number;
}

export async function listJobs(params?: ListJobsParams): Promise<ListJobsResponse> {
  const queryParams = new URLSearchParams();
  if (params?.status) queryParams.append("status", params.status);
  if (params?.limit) queryParams.append("limit", params.limit.toString());
  if (params?.offset) queryParams.append("offset", params.offset.toString());

  const query = queryParams.toString();
  const path = query ? `/api/web/queue/list?${query}` : "/api/web/queue/list";
  return get(path);
}

export async function getQueueStatus(): Promise<QueueSummary> {
  return get("/api/web/queue/queue-depth");
}

export async function getJob(jobId: string): Promise<QueueJob> {
  return get(`/api/web/queue/status/${jobId}`);
}

// ... etc
```

#### 1.2.3 Index Re-exports

**File:** `shared/api/index.ts`

```typescript
/**
 * API module exports.
 * 
 * Import domain functions directly:
 *   import { listJobs, getQueueStatus } from "@shared/api/queue";
 *   import { getLibraries, createLibrary } from "@shared/api/library";
 * 
 * Or import from index for convenience:
 *   import { listJobs, getLibraries } from "@shared/api";
 */

// Re-export all domain modules
export * from "./auth";
export * from "./queue";
export * from "./library";
export * from "./analytics";
export * from "./calibration";
export * from "./navidrome";
export * from "./metadata";
export * from "./tags";
export * from "./config";
export * from "./processing";
export * from "./filesystem";
export * from "./worker";

// Re-export client utilities
export { ApiError, snakeToCamel, API_BASE_URL } from "./client";
```

**Migration approach:**
1. Create `shared/api/` directory with all domain modules
2. Delete `shared/api.ts` immediately
3. Run `npm run build` — TypeScript errors show every broken import
4. Fix each error by updating imports to new domain functions
5. Commit when build passes

**Checklist:**
- [ ] Create shared/api/ directory
- [ ] Create client.ts with request, get, post, put, del, ApiError, snakeToCamel
- [ ] Create auth.ts (login, logout)
- [ ] Create queue.ts
- [ ] Create library.ts
- [ ] Create analytics.ts
- [ ] Create calibration.ts
- [ ] Create navidrome.ts
- [ ] Create metadata.ts
- [ ] Create tags.ts
- [ ] Create config.ts
- [ ] Create processing.ts
- [ ] Create filesystem.ts
- [ ] Create worker.ts
- [ ] Create index.ts with re-exports
- [ ] Delete old shared/api.ts
- [ ] Run build, fix all import errors
- [ ] Verify app works in browser
- [ ] Commit

---

### 1.3 Move Documentation Out of Components

**Goal:** Component folders should only contain code.

**Action:** Move `shared/components/ServerFilePicker.README.md` to `docs/dev/server-file-picker.md`

**Checklist:**
- [ ] Move file
- [ ] Update any references

---

## Phase 2: Error Handling & UX (Medium Priority)

### 2.1 Add Error Boundary (Router Level)

**Goal:** Graceful error handling when components throw.

**Create:** `shared/components/ErrorBoundary.tsx`

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Box, Button, Typography } from "@mui/material";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  /** 
   * Called when error is caught. Use for logging/reporting.
   */
  onError?: (error: Error, errorInfo: ErrorInfo) => void;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

/**
 * Error boundary for catching render errors.
 * 
 * Currently used at router level to catch page-level errors.
 * 
 * TODO (future): Add panel-level error boundaries for isolated failures.
 * For panel-level use, create a wrapper like:
 * 
 * ```tsx
 * function PanelErrorBoundary({ children, title }: { children: ReactNode; title: string }) {
 *   return (
 *     <ErrorBoundary
 *       fallback={
 *         <Panel>
 *           <Typography color="error">{title} failed to load</Typography>
 *           <Button onClick={() => window.location.reload()}>Reload</Button>
 *         </Panel>
 *       }
 *     >
 *       {children}
 *     </ErrorBoundary>
 *   );
 * }
 * ```
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("[ErrorBoundary] Caught error:", error, errorInfo);
    this.props.onError?.(error, errorInfo);
  }

  handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      return (
        <Box sx={{ p: 4, textAlign: "center" }}>
          <Typography variant="h5" color="error" gutterBottom>
            Something went wrong
          </Typography>
          <Typography color="text.secondary" sx={{ mb: 2 }}>
            {this.state.error?.message || "An unexpected error occurred"}
          </Typography>
          <Button variant="contained" onClick={this.handleRetry}>
            Try Again
          </Button>
        </Box>
      );
    }

    return this.props.children;
  }
}

/**
 * Helper for creating panel-level error boundaries (future use).
 * 
 * Usage:
 * ```tsx
 * <PanelBoundary title="Analytics">
 *   <AnalyticsChart />
 * </PanelBoundary>
 * ```
 */
export function createPanelBoundary(PanelComponent: React.ComponentType<{ children: ReactNode }>) {
  return function PanelBoundary({ 
    children, 
    title 
  }: { 
    children: ReactNode; 
    title: string;
  }) {
    return (
      <ErrorBoundary
        fallback={
          <PanelComponent>
            <Box sx={{ p: 2, textAlign: "center" }}>
              <Typography color="error" gutterBottom>
                {title} failed to load
              </Typography>
              <Button size="small" onClick={() => window.location.reload()}>
                Reload Page
              </Button>
            </Box>
          </PanelComponent>
        }
      >
        {children}
      </ErrorBoundary>
    );
  };
}
```

**Usage in AppRouter.tsx:**
```tsx
<ProtectedRoute>
  <ErrorBoundary>
    <AppShell>
      <Routes>...</Routes>
    </AppShell>
  </ErrorBoundary>
</ProtectedRoute>
```

**Checklist:**
- [ ] Create ErrorBoundary.tsx with createPanelBoundary helper
- [ ] Export from shared/components/ui/index.ts
- [ ] Wrap routes in AppRouter.tsx
- [ ] Test by throwing from a component

---

### 2.2 Hardened ConfirmProvider

**Goal:** Prevent double-resolve and support pending/busy state so confirm/cancel can't be clicked twice.

**Create:** `shared/components/ui/ConfirmProvider.tsx`

```tsx
/**
 * Global confirmation dialog provider.
 * 
 * Features:
 * - Promise-based API for async/await usage
 * - Prevents double-resolve (busy state blocks additional clicks)
 * - Automatic cleanup on unmount
 */

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  type ReactNode,
} from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  CircularProgress,
} from "@mui/material";

export interface ConfirmOptions {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  severity?: "info" | "warning" | "error";
}

interface ConfirmContextType {
  /**
   * Show confirmation dialog and wait for user response.
   * Returns true if confirmed, false if cancelled.
   */
  confirm: (options: ConfirmOptions) => Promise<boolean>;
}

const ConfirmContext = createContext<ConfirmContextType | undefined>(undefined);

interface DialogState {
  open: boolean;
  options: ConfirmOptions;
  busy: boolean;
}

const initialState: DialogState = {
  open: false,
  options: { title: "", message: "" },
  busy: false,
};

export function ConfirmProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DialogState>(initialState);
  
  // Store resolve function in ref to prevent stale closures
  const resolveRef = useRef<((value: boolean) => void) | null>(null);
  
  // Track if component is mounted to prevent state updates after unmount
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      // Reject any pending promise on unmount
      if (resolveRef.current) {
        resolveRef.current(false);
        resolveRef.current = null;
      }
    };
  }, []);

  const confirm = useCallback((options: ConfirmOptions): Promise<boolean> => {
    // If already showing a dialog, reject immediately
    if (state.open) {
      console.warn("[ConfirmProvider] Dialog already open, ignoring new request");
      return Promise.resolve(false);
    }

    return new Promise((resolve) => {
      resolveRef.current = resolve;
      setState({
        open: true,
        options,
        busy: false,
      });
    });
  }, [state.open]);

  const handleResponse = useCallback((value: boolean) => {
    // Prevent double-click
    if (state.busy || !resolveRef.current) {
      return;
    }

    // Set busy state to disable buttons
    setState((s) => ({ ...s, busy: true }));

    // Resolve the promise
    const resolve = resolveRef.current;
    resolveRef.current = null;
    resolve(value);

    // Close dialog after short delay (allows button feedback)
    setTimeout(() => {
      if (mountedRef.current) {
        setState(initialState);
      }
    }, 100);
  }, [state.busy]);

  const handleConfirm = useCallback(() => handleResponse(true), [handleResponse]);
  const handleCancel = useCallback(() => handleResponse(false), [handleResponse]);

  // Handle dialog close (backdrop click, escape key)
  const handleClose = useCallback((_event: object, reason: string) => {
    // Don't close if busy
    if (state.busy) return;
    
    // Treat backdrop/escape as cancel
    if (reason === "backdropClick" || reason === "escapeKeyDown") {
      handleCancel();
    }
  }, [state.busy, handleCancel]);

  const getSeverityColor = (severity?: string) => {
    switch (severity) {
      case "error":
        return "error";
      case "warning":
        return "warning";
      default:
        return "primary";
    }
  };

  return (
    <ConfirmContext.Provider value={{ confirm }}>
      {children}
      <Dialog
        open={state.open}
        onClose={handleClose}
        aria-labelledby="confirm-dialog-title"
        aria-describedby="confirm-dialog-description"
        disableEscapeKeyDown={state.busy}
      >
        <DialogTitle id="confirm-dialog-title">{state.options.title}</DialogTitle>
        <DialogContent>
          <DialogContentText id="confirm-dialog-description" sx={{ whiteSpace: "pre-line" }}>
            {state.options.message}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={handleCancel}
            disabled={state.busy}
            color="inherit"
          >
            {state.options.cancelLabel || "Cancel"}
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={state.busy}
            color={getSeverityColor(state.options.severity)}
            variant="contained"
            startIcon={state.busy ? <CircularProgress size={16} color="inherit" /> : undefined}
          >
            {state.options.confirmLabel || "Confirm"}
          </Button>
        </DialogActions>
      </Dialog>
    </ConfirmContext.Provider>
  );
}

/**
 * Hook to access confirmation dialog.
 * 
 * @example
 * ```tsx
 * const { confirm } = useConfirm();
 * 
 * const handleDelete = async () => {
 *   const ok = await confirm({
 *     title: "Delete Item?",
 *     message: "This cannot be undone.",
 *     severity: "warning",
 *   });
 *   if (ok) {
 *     await deleteItem();
 *   }
 * };
 * ```
 */
export function useConfirm(): ConfirmContextType {
  const context = useContext(ConfirmContext);
  if (!context) {
    throw new Error("useConfirm must be used within ConfirmProvider");
  }
  return context;
}
```

**Update App.tsx:**
```tsx
import { ConfirmProvider } from "@shared/components/ui";

function App() {
  return (
    <NotificationProvider>
      <ConfirmProvider>
        <AppRouter />
      </ConfirmProvider>
    </NotificationProvider>
  );
}
```

**New usage in components (preferred):**
```tsx
import { useConfirm } from "@shared/components/ui";

function LibraryManagement() {
  const { confirm } = useConfirm();

  const handleDelete = async (id: string, name: string) => {
    const ok = await confirm({
      title: "Delete Library?",
      message: `Delete library "${name}"?\n\nThis will remove the library entry but will NOT delete files on disk.`,
      severity: "warning",
    });
    
    if (ok) {
      await api.library.delete(id);
      await loadLibraries();
    }
  };
}
```

**Migration strategy:**
1. Create ConfirmProvider with hardened implementation
2. Add to App.tsx
3. Keep existing useConfirmDialog + ConfirmDialog working (backward compatible)
4. Migrate one component at a time to useConfirm
5. Eventually remove old useConfirmDialog hook

**Checklist:**
- [ ] Create ConfirmProvider.tsx with hardened implementation
- [ ] Export useConfirm from index.ts
- [ ] Add ConfirmProvider to App.tsx
- [ ] Migrate AdminPage to useConfirm
- [ ] Migrate CalibrationPage to useConfirm
- [ ] Migrate LibraryManagement to useConfirm
- [ ] Migrate InspectTagsPage to useConfirm
- [ ] Migrate TaggerStatusPage to useConfirm
- [ ] Delete old useConfirmDialog hook (after all migrated)

---

### 2.3 Add Skeleton Loading States

**Goal:** Replace "Loading..." text with proper skeleton UI.

**Create:** `shared/components/ui/PageSkeleton.tsx`

```tsx
import { Skeleton, Stack } from "@mui/material";
import { PageContainer } from "./PageContainer";

export function PageSkeleton({ title = "Loading..." }: { title?: string }) {
  return (
    <PageContainer title={title}>
      <Stack spacing={2}>
        <Skeleton variant="rectangular" height={120} />
        <Skeleton variant="rectangular" height={300} />
      </Stack>
    </PageContainer>
  );
}
```

**Update Suspense fallback in AppRouter.tsx:**
```tsx
<Suspense fallback={<PageSkeleton />}>
```

**Update individual pages to use loading skeletons:**
```tsx
if (loading) {
  return (
    <PageContainer title="Library">
      <Stack spacing={2}>
        <Skeleton variant="rectangular" height={100} />
        <Skeleton variant="rectangular" height={400} />
      </Stack>
    </PageContainer>
  );
}
```

**Checklist:**
- [ ] Create PageSkeleton.tsx
- [ ] Update AppRouter Suspense fallback
- [ ] Add skeleton states to DashboardPage
- [ ] Add skeleton states to LibraryPage
- [ ] Add skeleton states to TaggerStatusPage
- [ ] Add skeleton states to BrowsePage
- [ ] Add skeleton states to AnalyticsPage

---

## Phase 3: Code Quality (Low Priority)

### 3.1 Enable Case Transformation by Default

**Goal:** After Phase 1.2 is complete and stable, enable `transformCase: true` by default in client.ts.

**Steps:**
1. Verify all API calls work with current opt-in approach
2. Identify any APIs that break with case transformation
3. Update types to use camelCase (if not already)
4. Change default from `transformCase = false` to `transformCase = true`
5. Remove explicit `transformCase: true` from individual calls

**Checklist:**
- [ ] Audit all API response types for case consistency
- [ ] Update types that still use snake_case
- [ ] Enable transformCase by default
- [ ] Remove redundant transformCase options

---

### 3.2 Add React Query for Server State (Future)

**Goal:** Proper caching, background refetching, and optimistic updates.

**Note:** This is a larger undertaking. Consider for v1.0.

**Benefits:**
- Automatic caching (library stats shared between Dashboard and Library pages)
- Background refetching
- Loading/error states built-in
- Optimistic updates for mutations

**Would require:**
- Adding @tanstack/react-query dependency
- Creating query hooks for each API domain
- Migrating all useEffect-based data fetching

**Skip for now, revisit after Phase 1-2 complete.**

---

### 3.3 Add Basic Unit Tests (Future)

**Goal:** Test critical paths.

**Would require:**
- Adding vitest, @testing-library/react dependencies
- Creating test files alongside components
- CI integration

**Priority tests:**
- API client error handling
- Auth state management
- ConfirmProvider behavior (especially double-click prevention)
- Case conversion utilities

**Skip for now, revisit after Phase 1-2 complete.**

---

## Execution Order

```
Phase 1: Consistency & Quick Wins
├── Commit 1: Create shared/api/client.ts with all request concerns
├── Commit 2: Create domain modules (queue, library, etc.) with named exports
├── Commit 3: Create index.ts with re-exports
├── Commit 4: Delete old api.ts
├── Commit 5: Fix all import errors (TypeScript will guide you)
├── Commit 6: Migrate AdminPage to MUI/PageContainer
├── Commit 7: Migrate AnalyticsPage to MUI/PageContainer
├── Commit 8: Migrate CalibrationPage to MUI/PageContainer
├── Commit 9: Migrate ConfigPage to MUI/PageContainer
└── Commit 10: Move ServerFilePicker.README.md

Phase 2: Error Handling & UX
├── Commit 11: Add ErrorBoundary with panel helper
├── Commit 12: Wrap routes in ErrorBoundary
├── Commit 13: Add hardened ConfirmProvider
├── Commit 14: Add ConfirmProvider to App.tsx
├── Commit 15: Create PageSkeleton component
├── Commit 16: Update Suspense fallback
├── Commit 17-21: Migrate pages to useConfirm (one per commit)
└── Commit 22: Add skeleton loading to pages

Phase 3: Code Quality (Future)
├── Enable case transformation by default
├── Add React Query (v1.0)
└── Add unit tests (ongoing)
```

---

## Implementation Rules

1. **No legacy shims** - Delete old code, let TypeScript errors guide updates
2. **Test in browser after build passes** - Catch runtime errors early
3. **Keep existing components working** - useConfirmDialog stays until useConfirm migration complete
4. **One concern per commit** - Easy to review and revert

---

## Definition of Done

Each task is complete when:
1. Code compiles without errors (`npm run build`)
2. ESLint passes (`npm run lint`)
3. Feature works as expected in browser
4. No console errors
5. Visual consistency with existing MUI pages

---

## Notes

- **No backwards compatibility** - Delete old api.ts immediately, fix all errors in same commit
- **TypeScript errors are the migration guide** - Run build, fix what breaks
- **ConfirmProvider prevents double-resolve** - busy state + ref cleanup
- **ErrorBoundary at router level** - Panel-level helper ready for future use
- **snakeToCamel is opt-in initially** - Enable by default after testing

