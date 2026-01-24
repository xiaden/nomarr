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
  id: string; // HTTP-encoded Arango _id (e.g., "queue:123")
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
  id: string; // HTTP-encoded Arango _id (e.g., "libraries:123")
  name: string;
  rootPath: string; // maps to backend root_path
  isEnabled: boolean;
  watchMode: string; // 'off', 'event', or 'poll'
  fileWriteMode: "none" | "minimal" | "full"; // Tag writing mode
  createdAt?: string | number; // Can be ISO string or Unix timestamp
  updatedAt?: string | number; // Can be ISO string or Unix timestamp
  scannedAt?: string | null; // null if never scanned, ISO string if scanned
  // Scan status (for live progress tracking)
  scanStatus?: string | null; // "idle", "scanning", "complete", "error"
  scanProgress?: number | null; // Files processed so far
  scanTotal?: number | null; // Total files to process
  scanError?: string | null; // Error message if scanStatus === "error"
  // Statistics
  fileCount: number;
  folderCount: number;
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
  id: string; // HTTP-encoded Arango _id (e.g., "library_files:123")
  library_id: string; // HTTP-encoded Arango _id (e.g., "libraries:123")
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

// ──────────────────────────────────────────────────────────────────────
// Metadata Entity Types
// ──────────────────────────────────────────────────────────────────────

export interface Entity {
  id: string; // Entity _id (e.g., 'artists/v1_abc123...')
  key: string; // Entity _key
  display_name: string; // Display string
  song_count?: number; // Optional song count
}

export interface EntityListResult {
  entities: Entity[];
  total: number;
  limit: number;
  offset: number;
}

export interface SongListResult {
  song_ids: string[];
  total: number;
  limit: number;
  offset: number;
}

export interface EntityCounts {
  artists: number;
  albums: number;
  labels: number;
  genres: number;
  years: number;
}

export type EntityCollection = "artists" | "albums" | "labels" | "genres" | "years";

// Add more types as needed
