/**
 * Custom hook for fetching calibration convergence status.
 * Provides per-head convergence metrics and status.
 */

import { useEffect, useState } from "react";

import type { ConvergenceStatusResponse } from "../../../shared/api/calibration";
import { getConvergenceStatus } from "../../../shared/api/calibration";

export function useConvergenceStatus() {
  const [data, setData] = useState<ConvergenceStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadConvergenceStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await getConvergenceStatus();
      setData(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load convergence status");
      console.error("[Calibration] Convergence load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadConvergenceStatus();
  }, []);

  return {
    data,
    loading,
    error,
    reload: loadConvergenceStatus,
  };
}
