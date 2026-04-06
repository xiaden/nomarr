# Nomarr Frontend

React + TypeScript + Vite frontend for Nomarr music tagger.

## Structure

```
src/
├── main.tsx              # React entry point
├── App.tsx               # Root component
├── index.css             # Global dark theme styles
├── router/
│   └── AppRouter.tsx     # Routing with protected/public routes
├── components/
│   └── layout/
│       ├── AppShell.tsx  # Main layout wrapper (header + nav + content)
│       └── NavTabs.tsx   # Navigation tabs with active state
├── pages/
│   ├── LoginPage.tsx     # Authentication page
│   ├── DashboardPage.tsx # Dashboard overview
│   └── QueuePage.tsx     # Queue management
├── hooks/
│   └── useSSE.ts         # React hook for Server-Sent Events
└── shared/
    ├── api.ts            # Typed API client for backend
    ├── auth.ts           # Authentication utilities
    ├── sse.ts            # SSE connection helper
    └── types.ts          # TypeScript type definitions
```

## Development

```bash
npm install
npm run dev
```

Frontend runs on `http://localhost:5173`.
Backend API is at `http://localhost:8356`.

## Architecture

### Authentication

- Backend uses Bearer token authentication via `/web/auth/login`
- Session token stored in localStorage
- Protected routes redirect to `/login` if not authenticated
- Public routes redirect to `/` if already authenticated

### API Client (`shared/api.ts`)

Provides typed methods for backend endpoints:

```typescript
import { api } from "./shared/api";

// Login
const result = await api.auth.login("password");
setSessionToken(result.session_token);

// Get queue status
const summary = await api.queue.getStatus();
console.log(summary.pending, summary.running);

// Get specific job
const job = await api.queue.getJob(123);
console.log(job.status, job.path);
```

All authenticated requests automatically include the Bearer token from localStorage.

### SSE Updates (`hooks/useSSE.ts`)

Real-time updates via Server-Sent Events:

```typescript
import { useSSE } from "./hooks/useSSE";

function MyComponent() {
  const { connected } = useSSE({
    onMessage: (event) => {
      const data = JSON.parse(event.data);
      console.log("SSE update:", data);
    },
  });

  return <div>Connected: {connected ? "Yes" : "No"}</div>;
}
```

The backend sends updates for:

- Queue statistics (pending/running/completed counts)
- Active job state
- Worker state

## Type Definitions (`shared/types.ts`)

All backend response types are defined in TypeScript:

- `AuthResult` - Login response with session token
- `QueueJob` - Individual queue job with status/timestamps
- `QueueSummary` - Queue counts by status
- `SSEMessage` - Server-Sent Event message shape
- `LibraryStats` - Library statistics
- And more...

## Building Blocks

This scaffold provides the foundation. Feature implementation will follow the pattern:

1. Define types in `shared/types.ts`
2. Add API methods to `shared/api.ts`
3. Create page components in `pages/`
4. Add routes to `AppRouter.tsx`
5. Add navigation links to `NavTabs.tsx`

## Library management features

The library management UI now includes pipeline-oriented controls and status surfaces:

- **Pipeline status badges** on library cards so users can see whether a library is scanning, running ML, waiting for calibration, ready to write, writing, or done
- **Auto-write toggle** in library create/edit flows so users can choose whether writeback starts automatically after calibration apply completes
- **Pipeline status API integration** via the per-library pipeline endpoint for selective counts and current state

These features complement the existing scan controls and make it easier to see which libraries need attention versus which ones are progressing automatically.

## Next Steps

- Implement LoginPage with form and API integration
- Implement QueuePage with table and SSE updates
- Add analytics charts
- Expand library management UI polish and coverage
- Add worker monitoring
- Add calibration UI
