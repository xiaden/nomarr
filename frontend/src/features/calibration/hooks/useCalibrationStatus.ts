/**
 * Custom hook for managing calibration status.
 * Handles loading status, generating, and applying calibration.
 */

import { useEffect, useRef, useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import type { CalibrationStatus } from "../../../shared/api/calibration";
import { clearCalibration, getStatus } from "../../../shared/api/calibration";

import {
  useCalibrationApply,
  type CalibrationApplyState,
} from "./useCalibrationApply";
import {
  useHistogramCalibrationGeneration,
  type CalibrationGenerationState,
} from "./useHistogramCalibrationGeneration";

export function useCalibrationStatus() {
  const { showSuccess, showError } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } =
    useConfirmDialog();
  const [status, setStatus] = useState<CalibrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  // Stable refs for callbacks used inside effects that watch narrow deps
  const showErrorRef = useRef(showError);
  showErrorRef.current = showError;
  const showSuccessRef = useRef(showSuccess);
  showSuccessRef.current = showSuccess;
  const loadStatusRef = useRef(loadStatus);
  loadStatusRef.current = loadStatus;

  // Background calibration generation hook
  const {
    state: generationState,
    startGeneration,
    reset: resetGeneration,
  } = useHistogramCalibrationGeneration();

  // Background calibration apply hook
  const {
    state: applyState,
    startApply,
    reset: resetApply,
  } = useCalibrationApply();

  useEffect(() => {
    loadStatus();
  }, []);

  // Watch for generation completion and show notifications
  useEffect(() => {
    if (!generationState.completed) return;

    if (generationState.error) {
      showErrorRef.current(`Calibration failed: ${generationState.error}`);
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
      showSuccessRef.current(message);
      resetGeneration();
      loadStatusRef.current(); // Refresh status after generation completes
    }
  }, [generationState.completed, generationState.error, generationState.result, resetGeneration]);

  // Watch for apply completion and show notifications
  useEffect(() => {
    if (!applyState.completed) return;

    if (applyState.error) {
      showErrorRef.current(`Calibration apply failed: ${applyState.error}`);
      resetApply();
      return;
    }

    if (applyState.result) {
      const { processed, failed, total } = applyState.result;
      let msg = `Applied calibration to ${processed}/${total} files`;
      if (failed > 0) {
        msg += ` (${failed} failed)`;
      }
      showSuccessRef.current(msg);
      resetApply();
      loadStatusRef.current(); // Refresh status after apply completes
    }
  }, [applyState.completed, applyState.error, applyState.result, resetApply]);

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
        "Apply calibration to entire library? This will reprocess all files with current calibration values.",
      confirmLabel: "Apply",
      severity: "warning",
    });
    if (!confirmed) return;

    // Start background apply (non-blocking)
    await startApply();
  };

  const handleClear = async () => {
    const confirmed = await confirm({
      title: "Clear All Calibration Data?",
      message:
        "This will permanently remove all calibration states, history, and reset file calibration hashes. You will need to regenerate calibration afterward.",
      confirmLabel: "Clear",
      severity: "error",
    });
    if (!confirmed) return;

    try {
      const result = await clearCalibration();
      showSuccess(
        `Calibration data cleared. ${result.files_updated} file hashes reset.`
      );
      loadStatus();
    } catch (err) {
      showError(
        err instanceof Error ? err.message : "Failed to clear calibration"
      );
    }
  };

  return {
    status,
    loading,
    error,
    // Generation state for progress UI
    generationState,
    // Apply state for progress UI
    applyState,
    handleGenerate,
    handleApply,
    handleClear,
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}

// Re-export types for consumers
export type { CalibrationGenerationState };
export type { CalibrationApplyState };
