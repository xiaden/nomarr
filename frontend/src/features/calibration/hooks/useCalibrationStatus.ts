/**
 * Custom hook for managing calibration status.
 * Handles loading status, generating, applying, and clearing calibration.
 */

import { useEffect, useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
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
  const { showSuccess, showError } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();
  
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
    const confirmed = await confirm({
      title: "Generate Calibration?",
      message: "This analyzes all library files and may take some time.",
      confirmLabel: "Generate",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.calibration.generate(true);
      
      const calibCount = Object.keys(result.data.calibrations || {}).length;
      const filesSaved = result.saved_files?.saved_files || 0;
      
      let message = `Calibration generated! Library: ${result.data.library_size} files, `;
      message += `Calibrations: ${calibCount}, Skipped: ${result.data.skipped_tags}`;
      if (filesSaved > 0) {
        message += `, Saved ${filesSaved} files`;
      }
      
      showSuccess(message);
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to generate calibration"
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleApply = async () => {
    const confirmed = await confirm({
      title: "Apply Calibration?",
      message: "Apply calibration to entire library? This will queue all files for reprocessing.",
      confirmLabel: "Apply",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.calibration.apply();
      showSuccess(`Queued ${result.queued} files for recalibration`);
      await loadStatus();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to apply calibration");
    } finally {
      setActionLoading(false);
    }
  };

  const handleClear = async () => {
    const confirmed = await confirm({
      title: "Clear Calibration Queue?",
      message: "Clear all calibration queue jobs?",
      confirmLabel: "Clear",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.calibration.clear();
      showSuccess(`Cleared ${result.cleared} jobs`);
      await loadStatus();
    } catch (err) {
      showError(
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
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}
