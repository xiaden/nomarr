/**
 * Shared TypeScript types for Nomarr.
 *
 * These types match the backend API responses from:
 * - /api/web/* (web UI endpoints: auth, queue, library, analytics, etc.)
 */

// ──────────────────────────────────────────────────────────────────────
// Library Types
// ──────────────────────────────────────────────────────────────────────

export interface Library {
  library_id: string; // HTTP-encoded Arango _id (e.g., "libraries:123")
  name: string;
  rootPath: string; // maps to backend root_path
  isEnabled: boolean;
  watchMode: string; // 'off', 'event', or 'poll'
  fileWriteMode: "none" | "minimal" | "full"; // Tag writing mode
  libraryAutoWrite?: boolean;
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

export interface ScanResult {
  status: string;
  message: string;
  stats: {
    files_queued?: number;
    [key: string]: unknown;
  };
}

export interface LibraryFile {
  file_id: string; // HTTP-encoded Arango _id (e.g., "library_files:123")
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
  tagged: boolean; // Arango boolean
  tagged_version?: string;
  skip_auto_tag: boolean; // Arango boolean
  created_at?: string | number;
  updated_at?: string | number;
  tags?: FileTag[]; // Tags included in some responses
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

// ──────────────────────────────────────────────────────────────────────
// Filesystem Types
// ──────────────────────────────────────────────────────────────────────

export interface FsEntry {
  name: string;
  is_dir: boolean;
}

// ──────────────────────────────────────────────────────────────────────
// Metadata Entity Types
// ──────────────────────────────────────────────────────────────────────

export interface Entity {
  entity_id: string; // Entity _id (e.g., 'artists:v1_abc123...')
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

export type EntityCollection = "artist" | "album" | "label" | "genre" | "year";

// Add more types as needed


