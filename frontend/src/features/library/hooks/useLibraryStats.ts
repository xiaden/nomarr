/**
 * Custom hook for loading library statistics.
 */

import { useEffect, useState } from "react";

import { getStats } from "../../../shared/api/library";

export interface LibraryStatsData {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

export function useLibraryStats() {
  const [stats, setStats] = useState<LibraryStatsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getStats();
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
      console.error("[Library] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  return { stats, loading, error };
}
