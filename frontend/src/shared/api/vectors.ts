/**
 * Vector Store API functions.
 *
 * Provides similarity search on cold collections and maintenance operations.
 */

import { get, post } from "./client";

// ============================================================================
// Request/Response Types
// ============================================================================

export interface VectorSearchRequest {
  /** Backbone identifier (e.g., "effnet", "yamnet") */
  backbone_id: string;
  /** Query embedding vector */
  vector: number[];
  /** Maximum number of results (1-100) */
  limit?: number;
  /** Minimum similarity score threshold */
  min_score?: number;
}

export interface VectorSearchResultItem {
  /** Library file document ID */
  file_id: string;
  /** Similarity score */
  score: number;
  /** Stored embedding vector */
  vector: number[];
}

export interface VectorSearchResponse {
  /** List of matching vectors */
  results: VectorSearchResultItem[];
}

export interface VectorHotColdStats {
  /** Backbone identifier */
  backbone_id: string;
  /** Number of vectors in hot collection */
  hot_count: number;
  /** Number of vectors in cold collection */
  cold_count: number;
  /** Whether cold collection has vector index */
  index_exists: boolean;
}

export interface VectorStatsResponse {
  /** Stats for all registered backbones */
  stats: VectorHotColdStats[];
}

export interface VectorPromoteRequest {
  /** Backbone identifier (e.g., "effnet", "yamnet") */
  backbone_id: string;
  /** Number of HNSW graph lists (optional, auto-calculated if null) */
  nlists?: number | null;
}

export interface VectorPromoteResponse {
  /** Operation status */
  status: string;
  /** Backbone identifier */
  backbone_id: string;
  /** Human-readable result message */
  message: string;
}

export interface VectorGetResponse {
  /** Library file document ID */
  file_id: string;
  /** Backbone identifier */
  backbone_id: string;
  /** Embedding vector */
  vector: number[];
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Search for similar tracks using vector similarity.
 *
 * Searches cold collection only (never falls back to hot).
 * Requires cold collection to have a vector index.
 *
 * @param backbone_id - Backbone identifier (e.g., "effnet", "yamnet")
 * @param vector - Query embedding vector
 * @param limit - Maximum number of results (default 10, max 100)
 * @param min_score - Minimum similarity score threshold (default 0)
 * @returns List of matching vectors with scores
 * @throws ApiError with status 503 if no vector index exists
 */
export async function searchVectors(
  backbone_id: string,
  vector: number[],
  limit = 10,
  min_score = 0.0
): Promise<VectorSearchResponse> {
  const body: VectorSearchRequest = {
    backbone_id,
    vector,
    limit,
    min_score,
  };
  return post("/api/v1/vectors/search", body);
}

/**
 * Get hot/cold statistics for all registered backbones.
 *
 * Returns vector counts and index status for monitoring.
 *
 * @returns Stats for all backbones (hot_count, cold_count, index_exists)
 */
export async function getVectorStats(): Promise<VectorStatsResponse> {
  return get("/api/v1/admin/vectors/stats");
}

/**
 * Trigger promote & rebuild operation for a backbone.
 *
 * Synchronously drains vectors from hot to cold and rebuilds the ANN index.
 * This is a long-running operation that blocks until completion.
 *
 * @param backbone_id - Backbone identifier (e.g., "effnet", "yamnet")
 * @param nlists - Number of HNSW graph lists (optional, auto-calculated if null)
 * @returns Operation status and message
 */
export async function promoteVectors(
  backbone_id: string,
  nlists?: number | null
): Promise<VectorPromoteResponse> {
  const body: VectorPromoteRequest = {
    backbone_id,
    nlists: nlists ?? null,
  };
  return post("/api/v1/admin/vectors/promote", body);
}

/**
 * Get embedding vector for a specific track.
 *
 * Tries cold collection first, then falls back to hot if not found.
 * Use this to retrieve a track's vector before performing similarity search.
 *
 * @param backbone_id - Backbone identifier (e.g., "effnet", "yamnet")
 * @param file_id - Library file document ID
 * @returns Track's embedding vector
 * @throws ApiError with status 404 if vector not found
 */
export async function getTrackVector(
  backbone_id: string,
  file_id: string
): Promise<VectorGetResponse> {
  const params = new URLSearchParams({ backbone_id, file_id });
  return get(`/api/v1/vectors/track?${params.toString()}`);
}
