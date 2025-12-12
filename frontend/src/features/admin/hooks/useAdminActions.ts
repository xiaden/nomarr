/**
 * Custom hook for admin actions.
 * Provides worker pause/resume and server restart functionality.
 */

import { useState } from "react";

import { api } from "../../../shared/api";

export function useAdminActions() {
  const [actionLoading, setActionLoading] = useState(false);

  const handlePauseWorker = async () => {
    if (!confirm("Pause the worker? Processing will stop.")) return;

    try {
      setActionLoading(true);
      const result = await api.admin.pauseWorker();
      alert(result.message);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to pause worker");
    } finally {
      setActionLoading(false);
    }
  };

  const handleResumeWorker = async () => {
    if (!confirm("Resume the worker? Processing will start.")) return;

    try {
      setActionLoading(true);
      const result = await api.admin.resumeWorker();
      alert(result.message);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to resume worker");
    } finally {
      setActionLoading(false);
    }
  };

  const handleRestart = async () => {
    if (
      !confirm("Restart the API server? The page will reload in a few seconds.")
    )
      return;

    try {
      setActionLoading(true);
      const result = await api.admin.restart();
      alert(result.message);
      // Wait a moment then reload
      setTimeout(() => {
        window.location.reload();
      }, 3000);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to restart server");
      setActionLoading(false);
    }
  };

  return {
    actionLoading,
    handlePauseWorker,
    handleResumeWorker,
    handleRestart,
  };
}
