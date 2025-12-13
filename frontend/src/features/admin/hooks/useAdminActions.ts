/**
 * Custom hook for admin actions.
 * Provides worker pause/resume and server restart functionality.
 */

import { useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import { api } from "../../../shared/api";

export function useAdminActions() {
  const { showSuccess, showError } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();
  
  const [actionLoading, setActionLoading] = useState(false);

  const handlePauseWorker = async () => {
    const confirmed = await confirm({
      title: "Pause Worker?",
      message: "Pause the worker? Processing will stop.",
      confirmLabel: "Pause",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.admin.pauseWorker();
      showSuccess(result.message);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to pause worker");
    } finally {
      setActionLoading(false);
    }
  };

  const handleResumeWorker = async () => {
    const confirmed = await confirm({
      title: "Resume Worker?",
      message: "Resume the worker? Processing will start.",
      confirmLabel: "Resume",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.admin.resumeWorker();
      showSuccess(result.message);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to resume worker");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRestart = async () => {
    const confirmed = await confirm({
      title: "Restart Server?",
      message: "Restart the API server? The page will reload in a few seconds.",
      confirmLabel: "Restart",
      severity: "error",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await api.admin.restart();
      showSuccess(result.message);
      // Wait a moment then reload
      setTimeout(() => {
        window.location.reload();
      }, 3000);
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to restart server");
      setActionLoading(false);
    }
  };

  return {
    actionLoading,
    handlePauseWorker,
    handleResumeWorker,
    handleRestart,
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}
