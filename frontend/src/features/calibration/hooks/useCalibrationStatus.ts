/**
 * Custom hook for managing calibration status.
 * Handles loading status, generating, and applying calibration.
 */

import { useEffect, useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import type { CalibrationStatus } from "../../../shared/api/calibration";
import {
    apply,
    generate,
    getStatus,
} from "../../../shared/api/calibration";
import { reconcileTags } from "../../../shared/api/library";

export function useCalibrationStatus() {
  const { showSuccess, showError, showInfo } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();
  
  const [status, setStatus] = useState<CalibrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

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
      const result = await generate(true);
      
      const calibCount = Object.keys(result.data.calibrations || {}).length;
      const filesSaved = result.saved_files?.saved_files || 0;
      
      let message = `Calibration generated! Library: ${result.data.library_size} files, `;
      message += `Calibrations: ${calibCount}, Skipped: ${result.data.skipped_tags}`;
      if (filesSaved > 0) {
        message += `, Saved ${filesSaved} files`;
      }
      
      showSuccess(message);
      await loadStatus();
      
      // Check if reconciliation is needed for affected libraries
      if (result.requires_reconciliation && result.affected_libraries?.length) {
        const affected = result.affected_libraries;
        const totalOutdated = affected.reduce((sum, lib) => sum + lib.outdated_files, 0);
        const libraryNames = affected.map((lib) => lib.name).join(", ");
        const reconcileConfirmed = await confirm({
          title: "Reconcile File Tags?",
          message: `Calibration changed for ${affected.length} ${affected.length === 1 ? "library" : "libraries"} (${libraryNames}). ` +
            `${totalOutdated} files need to be rewritten to reflect the new calibration. Reconcile now?`,
          confirmLabel: "Reconcile",
          cancelLabel: "Later",
          severity: "info",
        });
        
        if (reconcileConfirmed) {
          setActionLoading(true);
          let totalProcessed = 0;
          let totalFailed = 0;
          
          for (const lib of affected) {
            try {
              const reconcileResult = await reconcileTags(lib.library_id);
              totalProcessed += reconcileResult.processed;
              totalFailed += reconcileResult.failed;
            } catch (err) {
              console.error(`[Calibration] Reconcile error for library ${lib.name}:`, err);
              totalFailed += 1;
            }
          }
          
          if (totalFailed > 0) {
            showError(`Reconciled ${totalProcessed} files, ${totalFailed} failed`);
          } else {
            showSuccess(`Reconciled ${totalProcessed} files across ${affected.length} ${affected.length === 1 ? "library" : "libraries"}`);
          }
        }
      }
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
      const result = await apply();
      showSuccess(`Queued ${result.queued} files for recalibration`);
      await loadStatus();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to apply calibration");
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
    handleGenerate,
    handleApply,
    handleUpdateFiles,
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}
