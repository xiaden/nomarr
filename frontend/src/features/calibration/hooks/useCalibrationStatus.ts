/**
 * Custom hook for managing calibration status.
 * Handles loading status, generating, applying, and clearing calibration.
 */

import { useEffect, useState } from "react";

import { api } from "../../../shared/api";

export interface CalibrationStatus {
  pending: number;
  running: number;
  completed: number;
  errors: number;
  worker_alive: boolean;
  worker_busy: boolean;
}

export function useCalibrationStatus() {
  const [status, setStatus] = useState<CalibrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.calibration.getStatus();
      setStatus(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load status");
      console.error("[Calibration] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const handleGenerate = async () => {
    if (!confirm("Generate new calibration? This analyzes all library files."))
      return;

    try {
      setActionLoading(true);
      await api.calibration.generate(true);
      alert("Calibration generated successfully!");
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "Failed to generate calibration"
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleApply = async () => {
    if (
      !confirm(
        "Apply calibration to entire library? This will queue all files for reprocessing."
      )
    )
      return;

    try {
      setActionLoading(true);
      const result = await api.calibration.apply();
      alert(`Queued ${result.queued} files for recalibration`);
      await loadStatus();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to apply calibration");
    } finally {
      setActionLoading(false);
    }
  };

  const handleClear = async () => {
    if (!confirm("Clear all calibration queue jobs?")) return;

    try {
      setActionLoading(true);
      const result = await api.calibration.clear();
      alert(`Cleared ${result.cleared} jobs`);
      await loadStatus();
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "Failed to clear calibration queue"
      );
    } finally {
      setActionLoading(false);
    }
  };

  return {
    status,
    loading,
    error,
    actionLoading,
    handleGenerate,
    handleApply,
    handleClear,
  };
}
