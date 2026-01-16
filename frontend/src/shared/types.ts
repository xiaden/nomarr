/**
 * Shared TypeScript types for Nomarr.
 *
 * These types match the backend API responses from:
 * - /api/web/* (web UI endpoints: auth, queue, library, analytics, etc.)
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
  id: string; // Arango _id
  path: string;
  status: "pending" | "running" | "done" | "error";
  created_at: number; // Unix timestamp
  started_at?: number | null; // Unix timestamp
  finished_at?: number | null; // Unix timestamp
  error_message?: string | null;
  results_json?: string | null;
  force: boolean; // Arango boolean
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

export interface Library {
  id: string; // Arango _id
  name: string;
  rootPath: string; // maps to backend root_path
  isEnabled: boolean;
  isDefault: boolean;
  createdAt?: string | number; // Can be ISO string or Unix timestamp
  updatedAt?: string | number; // Can be ISO string or Unix timestamp
}

export interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

export interface ScanResult {
  status: string;
  message: string;
  stats: {
    files_queued?: number;
    [key: string]: unknown;
  };
}

export interface LibraryFile {
  id: string; // Arango _id
  library_id: string; // Arango _id
  path: string;
  file_size?: number;
  modified_time?: number;
  duration_seconds?: number;
  artist?: string;
  album?: string;
  title?: string;
  calibration?: string;
  scanned_at?: number;
  last_tagged_at?: number;
  tagged: boolean; // Arango boolean
  tagged_version?: string;
  skip_auto_tag: boolean; // Arango boolean
  created_at?: string | number;
  updated_at?: string | number;
  tags?: FileTag[]; // Tags included in some responses
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

// ──────────────────────────────────────────────────────────────────────
// Tags Types
// ──────────────────────────────────────────────────────────────────────

export interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

export interface TagCleanupResult {
  orphaned_count: number;
  deleted_count: number;
}

export interface FileTagsResult {
  file_id: string; // Arango _id
  path: string;
  tags: FileTag[];
}

// ──────────────────────────────────────────────────────────────────────
// Filesystem Types
// ──────────────────────────────────────────────────────────────────────

export interface FsEntry {
  name: string;
  is_dir: boolean;
}

export interface FsListResponse {
  path: string; // Relative path from library root
  entries: FsEntry[];
}

// Add more types as needed
