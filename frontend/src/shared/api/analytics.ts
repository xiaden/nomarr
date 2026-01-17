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
 */
export async function getMoodDistribution(): Promise<MoodDistributionResponse> {
  return get("/api/web/analytics/mood-distribution");
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
 */
export async function getTagCoOccurrence(
  requestBody: TagCoOccurrenceRequest
): Promise<TagCoOccurrenceResponse> {
  return post("/api/web/analytics/tag-co-occurrences", requestBody);
}
