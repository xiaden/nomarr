# Queue Feature Implementation

Real-time queue management page for Nomarr's processing queue.

## Features

### ✅ Job Listing

- Fetches jobs from `/web/api/list` endpoint
- Displays job ID, file path, status, timestamps, and error messages
- Path truncation with full path on hover

### ✅ Status Filtering

- Filter by: All, Pending, Running, Done, Error
- Resets to page 1 when filter changes
- Active filter highlighted

### ✅ Pagination

- 50 jobs per page (configurable via `limit` state)
- Previous/Next navigation
- Shows current page and total count
- Disabled when on first/last page

### ✅ Real-time Updates (SSE)

- Connects to `/web/events/status` via `useSSE` hook
- Automatically refetches queue on any SSE message
- Shows connection status (Connected/Disconnected)
- Auto-reconnect on connection loss

### ✅ Queue Summary

- Live statistics badges: Pending, Running, Completed, Errors
- Updated from `/web/api/queue-depth` endpoint

### ✅ Job Actions

- **Remove Job**: Delete individual pending/error jobs
- **Clear Completed**: Bulk remove all completed jobs
- **Clear Errors**: Bulk remove all error jobs
- **Clear All**: Remove all jobs except running ones
- Confirmation dialogs for all destructive actions
- Disabled during loading states

### ✅ Error Handling

- Loading indicators during fetch
- Error messages on API failures
- Graceful handling of missing data

### ✅ UI/UX

- Clean table layout with hover effects
- Status badges with color coding:
  - Pending: Gray
  - Running: Blue
  - Done: Green
  - Error: Red
- Responsive button states (disabled when loading)
- Inline styles using CSS variables from `index.css`

## Architecture

```
frontend/src/
├── features/
│   └── queue/
│       └── QueuePage.tsx       # Main implementation
├── pages/
│   └── QueuePage.tsx           # Route wrapper
├── shared/
│   └── api.ts                  # Added queue.listJobs()
├── hooks/
│   └── useSSE.ts               # SSE connection management
└── router/
    └── AppRouter.tsx           # Routes /queue to QueuePage
```

## API Endpoints Used

| Endpoint                               | Method | Purpose                               |
| -------------------------------------- | ------ | ------------------------------------- |
| `/web/api/list`                        | GET    | List jobs with pagination/filtering   |
| `/web/api/queue-depth`                 | GET    | Get queue summary statistics          |
| `/web/api/admin/remove`                | POST   | Remove specific job or jobs by status |
| `/web/api/admin/queue/clear-completed` | POST   | Clear all completed jobs              |
| `/web/api/admin/queue/clear-errors`    | POST   | Clear all error jobs                  |
| `/web/api/admin/queue/clear-all`       | POST   | Clear all non-running jobs            |
| `/web/events/status`                   | SSE    | Real-time queue updates               |

## Usage

```bash
# Start frontend dev server
cd frontend
npm run dev
```

Visit http://localhost:5173, log in, and click the "Queue" tab.

## State Management

- **Local State**: Uses React `useState` for jobs, summary, filters, pagination
- **Side Effects**: Uses React `useEffect` for loading on filter/page change
- **SSE**: Uses custom `useSSE` hook for real-time updates
- **No Global State**: All state local to component (simple and predictable)

## Next Steps

**Potential Enhancements:**

- Add job retry functionality
- Show job progress for running jobs
- Add search/filter by file path
- Export queue to CSV
- Bulk job selection and actions
- Show estimated time remaining for running jobs
- Add sorting (by date, status, etc.)
- Implement optimistic UI updates

**Backend Enhancements Needed:**

- SSE messages should include job details (not just trigger refetch)
- Consider GraphQL or batch endpoints to reduce API calls
- Add WebSocket support for bidirectional communication
