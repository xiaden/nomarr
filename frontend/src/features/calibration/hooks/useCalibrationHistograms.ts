/**
 * Custom hook for fetching calibration histograms across all heads.
 * Returns per-head histogram bin data for visualization.
 */

import { useEffect, useState } from "react";

import type { HeadHistogramResponse } from "@shared/api/calibration";
import { getAllHistograms } from "@shared/api/calibration";

export function useCalibrationHistograms() {
  const [data, setData] = useState<HeadHistogramResponse[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadHistograms = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getAllHistograms();
      setData(result.calibrations ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load histogram data");
      console.error("[Calibration] Histogram load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadHistograms();
  }, []);

  return { data, loading, error, reload: loadHistograms };
}
