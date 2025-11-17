/**
 * Shared TypeScript types for Nomarr.
 *
 * These types match the backend API responses from:
 * - /web/auth/* (authentication)
 * - /web/api/* (queue, library, workers, etc.)
 * - /web/events/status (SSE updates)
 */

// ──────────────────────────────────────────────────────────────────────
// Authentication Types
// ──────────────────────────────────────────────────────────────────────

export interface AuthResult {
  session_token: string;
  expires_in: number; // seconds
}

export interface LogoutResult {
  status: string;
}

// ──────────────────────────────────────────────────────────────────────
// Queue Types
// ──────────────────────────────────────────────────────────────────────

export interface QueueJob {
  id: number;
  path: string;
  status: "pending" | "running" | "done" | "error";
  created_at: number; // Unix timestamp
  started_at?: number | null; // Unix timestamp
  finished_at?: number | null; // Unix timestamp
  error_message?: string | null;
  results_json?: string | null;
  force: number; // 0 or 1 (SQLite boolean)
}

export interface QueueSummary {
  pending: number;
  running: number;
  completed: number;
  errors: number;
}

export interface QueueResponse {
  jobs: QueueJob[];
  summary: QueueSummary;
}

// ──────────────────────────────────────────────────────────────────────
// SSE Message Types
// ──────────────────────────────────────────────────────────────────────

export interface SSEMessage {
  type: string;
  data: QueueStatusData | WorkerStatusData | unknown;
}

export interface QueueStatusData {
  pending: number;
  running: number;
  completed: number;
  errors: number;
}

export interface WorkerStatusData {
  worker_id: string;
  status: string;
  current_file?: string;
  progress?: number;
}

// ──────────────────────────────────────────────────────────────────────
// Library Types
// ──────────────────────────────────────────────────────────────────────

export interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

export interface LibraryFile {
  id: number;
  path: string;
  file_size: number;
  modified_time: number;
  duration_seconds: number;
  artist?: string;
  album?: string;
  title?: string;
  genre?: string;
  year?: number;
  track_number?: number;
  tags_json?: string;
  nom_tags?: string;
  scanned_at?: number;
  last_tagged_at?: number;
  tagged: number; // 0 or 1 (SQLite boolean)
  tagged_version?: string;
  skip_auto_tag: number; // 0 or 1 (SQLite boolean)
}

// ──────────────────────────────────────────────────────────────────────
// Admin Types
// ──────────────────────────────────────────────────────────────────────

export interface RemoveJobsResult {
  removed: number;
  status: string;
}

export interface ResetJobsResult {
  status: string;
  message: string;
  reset: number;
}

// Add more types as needed
