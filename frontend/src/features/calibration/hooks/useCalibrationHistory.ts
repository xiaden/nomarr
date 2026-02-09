/**
 * Custom hook for fetching calibration history across all heads.
 * Returns per-head convergence snapshots for charting.
 */

import { useEffect, useState } from "react";

import type { HistorySnapshot } from "@shared/api/calibration";
import { getHistory } from "@shared/api/calibration";

export interface CalibrationHistoryData {
  [head_key: string]: HistorySnapshot[];
}

export function useCalibrationHistory() {
  const [data, setData] = useState<CalibrationHistoryData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHistory = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getHistory();
      // When no calibrationKey, response is { all_heads: { [key]: snapshots[] } }
      const allHeads = (result as unknown as Record<string, Record<string, HistorySnapshot[]>>).all_heads;
      setData(allHeads ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load calibration history");
      console.error("[Calibration] History load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistory();
  }, []);

  return { data, loading, error, reload: loadHistory };
}
