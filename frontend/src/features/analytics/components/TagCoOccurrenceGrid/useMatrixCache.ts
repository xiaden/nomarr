/**
 * Cache hook for co-occurrence matrix data.
 * 
 * Provides caching for matrix API responses to avoid redundant network requests
 * when switching between preset combinations.
 */

import { useCallback } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";

import type { MatrixData } from "./types";

// Module-level cache shared across all component instances
const matrixCache = new Map<string, MatrixData>();

/**
 * Generate a cache key from matrix parameters.
 * 
 * Normalizes tags by sorting them to ensure consistent keys regardless of order.
 * Note: Order matters for the matrix (swapping X/Y produces different results),
 * so we only sort within each axis, not across axes.
 */
function getCacheKey(
  xTags: TagSpec[],
  yTags: TagSpec[],
  libraryId?: string
): string {
  const normalize = (tags: TagSpec[]) =>
    JSON.stringify(
      tags.map((t) => `${t.key}:${t.value}`).sort()
    );

  return JSON.stringify({
    x: normalize(xTags),
    y: normalize(yTags),
    lib: libraryId ?? null,
  });
}

/**
 * Hook providing cache operations for matrix data.
 * 
 * @returns Object with getCached and setCached functions
 * 
 * @example
 * ```tsx
 * const { getCached, setCached } = useMatrixCache();
 * 
 * // Check cache before API call
 * const cached = getCached(xTags, yTags, libraryId);
 * if (cached) {
 *   setMatrix(cached);
 *   return;
 * }
 * 
 * // After API call
 * setCached(xTags, yTags, libraryId, result);
 * ```
 */
export function useMatrixCache() {
  const getCached = useCallback(
    (xTags: TagSpec[], yTags: TagSpec[], libraryId?: string): MatrixData | null => {
      const key = getCacheKey(xTags, yTags, libraryId);
      return matrixCache.get(key) ?? null;
    },
    []
  );

  const setCached = useCallback(
    (
      xTags: TagSpec[],
      yTags: TagSpec[],
      libraryId: string | undefined,
      data: MatrixData
    ) => {
      const key = getCacheKey(xTags, yTags, libraryId);
      matrixCache.set(key, data);
    },
    []
  );

  return { getCached, setCached };
}

/**
 * Clear the matrix cache.
 * 
 * Useful for testing or when data needs to be refreshed.
 */
export function clearMatrixCache(): void {
  matrixCache.clear();
}
