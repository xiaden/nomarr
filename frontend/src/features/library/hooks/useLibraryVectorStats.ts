import { useCallback, useEffect, useState } from "react";

import {
  getLibraryVectorStats,
  type LibraryVectorStatsResponse,
} from "../../../shared/api/library";

export function useLibraryVectorStats(libraryId: string | null) {
  const [stats, setStats] = useState<LibraryVectorStatsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadStats = useCallback(async () => {
    if (!libraryId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await getLibraryVectorStats(libraryId);
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load vector stats");
    } finally {
      setLoading(false);
    }
  }, [libraryId]);

  useEffect(() => {
    loadStats();
  }, [loadStats]);

  return { stats, loading, error, reload: loadStats };
}
