/**
 * useVectorSearch - Hook for vector similarity search.
 */

import { useCallback, useState } from "react";

import { ApiError } from "@shared/api/client";
import {
  searchVectors,
  type VectorSearchResultItem,
} from "@shared/api/vectors";

export interface UseVectorSearchResult {
  loading: boolean;
  error: string | null;
  results: VectorSearchResultItem[] | null;
  searchByFileId: (
    backboneId: string,
    fileId: string,
    limit?: number,
    minScore?: number
  ) => Promise<void>;
}

/**
 * Hook for performing vector similarity searches.
 *
 * Provides:
 * - searchByFileId: Single-call search by file ID (backend resolves vector internally)
 * - Loading and error state management
 */
export function useVectorSearch(): UseVectorSearchResult {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<VectorSearchResultItem[] | null>(null);

  const searchByFileId = useCallback(
    async (
      backboneId: string,
      fileId: string,
      limit = 10,
      minScore = 0
    ): Promise<void> => {
      setLoading(true);
      setError(null);
      setResults(null);

      try {
        const response = await searchVectors(
          backboneId,
          fileId,
          limit,
          minScore
        );
        setResults(response.results);
      } catch (err) {
        if (err instanceof ApiError) {
          if (err.status === 404) {
            setError(
              `No vector found for this track with backbone "${backboneId}". ` +
                "The track may not have been processed yet."
            );
          } else if (err.status === 503) {
            setError(
              "Vector search not available: no vector index exists. " +
                "Run promote & rebuild from the admin panel first."
            );
          } else {
            setError(`API Error (${err.status}): ${err.message}`);
          }
        } else if (err instanceof Error) {
          setError(err.message);
        } else {
          setError("Unknown error occurred");
        }
      } finally {
        setLoading(false);
      }
    },
    []
  );

  return {
    loading,
    error,
    results,
    searchByFileId,
  };
}
