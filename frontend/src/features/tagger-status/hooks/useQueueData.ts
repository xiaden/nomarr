/**
 * Custom hook for managing queue data and actions.
 * Handles loading, filtering, pagination, polling updates, and job actions.
 */

import { useEffect, useState } from "react";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { useNotification } from "../../../hooks/useNotification";
import {
    clearAll as apiClearAll,
    clearCompleted as apiClearCompleted,
    clearErrors as apiClearErrors,
    getQueueStatus,
    listJobs,
    removeJobs,
} from "../../../shared/api/queue";
import type { QueueJob, QueueSummary } from "../../../shared/types";

type StatusFilter = "all" | "pending" | "running" | "done" | "error";

export function useQueueData() {
  const { showSuccess, showError } = useNotification();
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();

  const [jobs, setJobs] = useState<QueueJob[]>([]);
  const [summary, setSummary] = useState<QueueSummary>({
    pending: 0,
    running: 0,
    completed: 0,
    errors: 0,
  });
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  const loadQueue = async () => {
    try {
      setLoading(true);
      setError(null);

      const params: {
        status?: "pending" | "running" | "done" | "error";
        limit: number;
        offset: number;
      } = {
        limit,
        offset,
      };
      if (statusFilter !== "all") {
        params.status = statusFilter as "pending" | "running" | "done" | "error";
      }

      const jobsResponse = await listJobs(params);
      setJobs(jobsResponse.jobs);
      setTotal(jobsResponse.total);

      const summaryResponse = await getQueueStatus();
      setSummary(summaryResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queue");
      console.error("[Queue] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, offset]);

  // Adaptive polling: 1s when active, 30s when idle
  useEffect(() => {
    const hasJobs = total > 0 || summary.pending > 0 || summary.running > 0;
    const pollInterval = hasJobs ? 1000 : 30000; // 1s active, 30s idle

    const interval = setInterval(async () => {
      try {
        const summaryResponse = await getQueueStatus();
        setSummary(summaryResponse);

        // If we're looking at a specific status page, refresh job list
        if (!loading) {
          const params: {
            status?: "pending" | "running" | "done" | "error";
            limit: number;
            offset: number;
          } = {
            limit,
            offset,
          };
          if (statusFilter !== "all") {
            params.status = statusFilter as "pending" | "running" | "done" | "error";
          }

          const jobsResponse = await listJobs(params);
          setJobs(jobsResponse.jobs);
          setTotal(jobsResponse.total);
        }
      } catch (err) {
        console.error("[Queue] Failed to poll queue status:", err);
      }
    }, pollInterval);

    return () => clearInterval(interval);
  }, [total, summary, loading, statusFilter, offset, limit]);

  const removeJob = async (jobId: string) => {
    const confirmed = await confirm({
      title: "Remove Job",
      message: `Remove job ${jobId}?`,
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      await removeJobs({ job_id: jobId });
      await loadQueue();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to remove job");
    } finally {
      setActionLoading(false);
    }
  };

  const clearCompleted = async () => {
    const confirmed = await confirm({
      title: "Clear Completed Jobs",
      message: "Clear all completed jobs?",
      severity: "warning",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await apiClearCompleted();
      showSuccess(`Removed ${result.removed} completed job(s)`);
      await loadQueue();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to clear completed");
    } finally {
      setActionLoading(false);
    }
  };

  const clearErrors = async () => {
    const confirmed = await confirm({
      title: "Clear Error Jobs",
      message: "Clear all error jobs?",
      severity: "error",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await apiClearErrors();
      showSuccess(`Removed ${result.removed} error job(s)`);
      await loadQueue();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to clear errors");
    } finally {
      setActionLoading(false);
    }
  };

  const clearAll = async () => {
    const confirmed = await confirm({
      title: "Clear All Jobs",
      message: "Clear ALL jobs (except running)?",
      severity: "error",
    });
    if (!confirmed) return;

    try {
      setActionLoading(true);
      const result = await apiClearAll();
      showSuccess(`Removed ${result.removed} job(s)`);
      await loadQueue();
    } catch (err) {
      showError(err instanceof Error ? err.message : "Failed to clear all");
    } finally {
      setActionLoading(false);
    }
  };

  const handleFilterChange = (filter: StatusFilter) => {
    setStatusFilter(filter);
    setOffset(0);
  };

  const nextPage = () => {
    if (currentPage < totalPages) {
      setOffset(offset + limit);
    }
  };

  const prevPage = () => {
    if (currentPage > 1) {
      setOffset(Math.max(0, offset - limit));
    }
  };

  return {
    jobs,
    summary,
    total,
    loading,
    error,
    actionLoading,
    statusFilter,
    currentPage,
    totalPages,
    loadQueue,
    removeJob,
    clearCompleted,
    clearErrors,
    clearAll,
    handleFilterChange,
    nextPage,
    prevPage,
    // Dialog state for rendering ConfirmDialog
    dialogState: { isOpen, options, handleConfirm, handleCancel },
  };
}
