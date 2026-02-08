/**
 * Custom hook for managing calibration status.
 * Handles loading status, generating, and applying calibration.
 */

import { useEffect, useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import type { CalibrationStatus } from "../../../shared/api/calibration";
import { apply, getStatus } from "../../../shared/api/calibration";

import {
  useHistogramCalibrationGeneration,
  type CalibrationGenerationState,
} from "./useHistogramCalibrationGeneration";

export function useCalibrationStatus() {
  const { showSuccess, showError, showInfo } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } =
    useConfirmDialog();
  const [status, setStatus] = useState<CalibrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  // Background calibration generation hook
  const {
    state: generationState,
    startGeneration,
    reset: resetGeneration,
  } = useHistogramCalibrationGeneration();

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getStatus();
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

  // Watch for generation completion and show notifications
  useEffect(() => {
    if (!generationState.completed) return;

    if (generationState.error) {
      showError(`Calibration failed: ${generationState.error}`);
      resetGeneration();
      return;
    }

    if (generationState.result) {
      const { heads_processed, heads_success, heads_failed } =
        generationState.result;
      let message = `Calibration generated! Processed ${heads_processed} heads`;
      if (heads_failed > 0) {
        message += ` (${heads_success} success, ${heads_failed} failed)`;
      }
      showSuccess(message);
      resetGeneration();
      loadStatus(); // Refresh status after generation completes
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [generationState.completed]);

  const handleGenerate = async () => {
    const confirmed = await confirm({
      title: "Generate Calibration?",
      message:
        "This analyzes all library files and may take some time. Progress will be shown while running.",
      confirmLabel: "Generate",
      severity: "warning",
    });
    if (!confirmed) return;

    // Start background generation (non-blocking)
    await startGeneration();
  };

  const handleApply = async () => {
    const confirmed = await confirm({
      title: "Apply Calibration?",
      message:
        "Apply calibration to entire library? This will queue all files for reprocessing.",
      confirmLabel: "Apply",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await apply();
      showSuccess(`Queued ${result.queued} files for recalibration`);
      await loadStatus();
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to apply calibration"
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleUpdateFiles = () => {
    showInfo("Not implemented");
  };

  return {
    status,
    loading,
    error,
    actionLoading,
    // Generation state for progress UI
    generationState,
    handleGenerate,
    handleApply,
    handleUpdateFiles,
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}

// Re-export type for consumers
export type { CalibrationGenerationState };
