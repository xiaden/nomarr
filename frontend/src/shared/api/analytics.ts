/**
 * Analytics API functions.
 */

import { get, post } from "./client";

export interface TagFrequency {
  tag_key: string;
  total_count: number;
  unique_values: number;
}

export interface TagFrequenciesResponse {
  tag_frequencies: TagFrequency[];
}

/**
 * Get tag frequency statistics.
 */
export async function getTagFrequencies(
  limit = 50
): Promise<TagFrequenciesResponse> {
  return get(`/api/web/analytics/tag-frequencies?limit=${limit}`);
}

export interface MoodDistributionItem {
  mood: string;
  count: number;
  percentage: number;
}

export interface MoodDistributionResponse {
  mood_distribution: MoodDistributionItem[];
}

/**
 * Get mood distribution.
 * Optionally filtered by libraryId.
 */
export async function getMoodDistribution(
  libraryId?: string
): Promise<MoodDistributionResponse> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : "";
  return get(`/api/web/analytics/mood-distribution${params}`);
}

/**
 * Get tag correlations matrix.
 */
export async function getTagCorrelations(
  topN = 20
): Promise<Record<string, unknown>> {
  return get(`/api/web/analytics/tag-correlations?top_n=${topN}`);
}

export interface CoOccurrence {
  tag: string;
  count: number;
  percentage: number;
}

export interface TopItem {
  name: string;
  count: number;
  percentage: number;
}

export interface TagCoOccurrencesResponse {
  tag: string;
  total_occurrences: number;
  co_occurrences: CoOccurrence[];
  top_artists: TopItem[];
  top_genres: TopItem[];
  limit: number;
}

/**
 * Get co-occurrences for a specific tag.
 */
export async function getTagCoOccurrences(
  tag: string,
  limit = 10
): Promise<TagCoOccurrencesResponse> {
  return get(
    `/api/web/analytics/tag-co-occurrences/${encodeURIComponent(tag)}?limit=${limit}`
  );
}

export interface TagSpec {
  key: string;
  value: string;
}

export interface TagCoOccurrenceRequest {
  x: TagSpec[];
  y: TagSpec[];
}

export interface TagCoOccurrenceResponse {
  x: TagSpec[];
  y: TagSpec[];
  matrix: number[][];
}

/**
 * Get generic tag co-occurrence matrix.
 *
 * POST request with X and Y axis tag specifications.
 * Returns matrix where matrix[j][i] = count of files with both y[j] and x[i].
 * Maximum 16x16 matrix size.
 * Optionally filtered by libraryId.
 */
export async function getTagCoOccurrence(
  requestBody: TagCoOccurrenceRequest,
  libraryId?: string
): Promise<TagCoOccurrenceResponse> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : "";
  return post(`/api/web/analytics/tag-co-occurrences${params}`, requestBody);
}


// ──────────────────────────────────────────────────────────────────────
// Collection Profile Types & API
// ──────────────────────────────────────────────────────────────────────

export interface LibraryStats {
  file_count: number;
  total_duration_ms: number;
  total_file_size_bytes: number;
  avg_track_length_ms: number;
}

export interface YearDistributionItem {
  year: number | string;
  count: number;
}

export interface GenreDistributionItem {
  genre: string;
  count: number;
}

export interface ArtistDistributionItem {
  artist: string;
  count: number;
}

export interface ArtistDistribution {
  top_artists: ArtistDistributionItem[];
  others_count: number;
  total_artists: number;
}

export interface CollectionOverviewResponse {
  stats: LibraryStats;
  year_distribution: YearDistributionItem[];
  genre_distribution: GenreDistributionItem[];
  artist_distribution: ArtistDistribution;
}

/**
 * Get collection overview statistics.
 * Optionally filtered by libraryId.
 */
export async function getCollectionOverview(
  libraryId?: string
): Promise<CollectionOverviewResponse> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : "";
  return get(`/api/web/analytics/collection-overview${params}`);
}

// ──────────────────────────────────────────────────────────────────────
// Mood Analysis Types & API
// ──────────────────────────────────────────────────────────────────────

export interface MoodCoverageTier {
  tagged: number;
  percentage: number;
}

export interface MoodCoverage {
  total_files: number;
  tiers: Record<string, MoodCoverageTier>;
}

export interface MoodBalanceItem {
  mood: string;
  count: number;
}

export interface MoodPairItem {
  mood1: string;
  mood2: string;
  count: number;
}

export interface DominantVibeItem {
  mood: string;
  percentage: number;
}

export interface MoodAnalysisResponse {
  coverage: MoodCoverage;
  balance: Record<string, MoodBalanceItem[]>;
  top_pairs: MoodPairItem[];
  dominant_vibes: DominantVibeItem[];
}

/**
 * Get mood analysis statistics.
 * Optionally filtered by libraryId.
 */
export async function getMoodAnalysis(
  libraryId?: string
): Promise<MoodAnalysisResponse> {
  const params = libraryId ? `?library_id=${encodeURIComponent(libraryId)}` : "";
  return get(`/api/web/analytics/mood-analysis${params}`);
}