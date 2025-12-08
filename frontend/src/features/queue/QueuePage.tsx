/**
 * Queue management page.
 *
 * Features:
 * - List all queue jobs with pagination
 * - Filter by status (all, pending, running, done, error)
 * - Real-time updates via SSE
 * - Job removal actions
 * - Clear completed/error jobs
 */

import { useEffect, useState } from "react";

import { useSSE } from "../../hooks/useSSE";
import { api } from "../../shared/api";
import type { QueueJob, QueueSummary } from "../../shared/types";

type StatusFilter = "all" | "pending" | "running" | "done" | "error";

export function QueuePage() {
  // State
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

  // Filters & pagination
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);

  // Calculate current page
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  // Load queue data
  const loadQueue = async () => {
    try {
      setLoading(true);
      setError(null);

      // Fetch jobs
      const params: { status?: string; limit: number; offset: number } = {
        limit,
        offset,
      };
      if (statusFilter !== "all") {
        params.status = statusFilter;
      }

      const jobsResponse = await api.queue.listJobs(params);
      setJobs(jobsResponse.jobs);
      setTotal(jobsResponse.total);

      // Fetch summary
      const summaryResponse = await api.queue.getStatus();
      setSummary(summaryResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load queue");
      console.error("[Queue] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  // Load queue on mount and when filters change
  useEffect(() => {
    loadQueue();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [statusFilter, offset]);

  // SSE updates - update summary directly from event data
  const { connected } = useSSE({
    onMessage: (event) => {
      try {
        const data = JSON.parse(event.data);
        
        // Handle queue:status updates (summary data)
        if (data.topic === "queue:status" && data.state) {
          setSummary({
            pending: data.state.pending || 0,
            running: data.state.running || 0,
            completed: data.state.completed || 0,
            errors: data.state.errors || 0,
          });
          console.log("[Queue] SSE: Updated summary from event", data.state);
        }
        
        // Handle queue:jobs updates (job state changes) - reload to refresh job list
        if (data.topic === "queue:jobs" && !loading) {
          console.log("[Queue] SSE: Job update, reloading job list");
          loadQueue();
        }
      } catch (err) {
        console.warn("[Queue] Failed to parse SSE message:", err);
      }
    },
  });

  // Actions
  const removeJob = async (jobId: number) => {
    if (!confirm(`Remove job ${jobId}?`)) return;

    try {
      setActionLoading(true);
      await api.queue.removeJobs({ job_id: jobId });
      await loadQueue(); // Reload to reflect changes
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to remove job");
    } finally {
      setActionLoading(false);
    }
  };

  const clearCompleted = async () => {
    if (!confirm("Clear all completed jobs?")) return;

    try {
      setActionLoading(true);
      const result = await api.queue.clearCompleted();
      alert(`Removed ${result.removed} completed job(s)`);
      await loadQueue();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to clear completed");
    } finally {
      setActionLoading(false);
    }
  };

  const clearErrors = async () => {
    if (!confirm("Clear all error jobs?")) return;

    try {
      setActionLoading(true);
      const result = await api.queue.clearErrors();
      alert(`Removed ${result.removed} error job(s)`);
      await loadQueue();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to clear errors");
    } finally {
      setActionLoading(false);
    }
  };

  const clearAll = async () => {
    if (!confirm("Clear ALL jobs (except running)?")) return;

    try {
      setActionLoading(true);
      const result = await api.queue.clearAll();
      alert(`Removed ${result.removed} job(s)`);
      await loadQueue();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to clear all");
    } finally {
      setActionLoading(false);
    }
  };

  // Pagination
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

  // Format timestamp
  const formatTimestamp = (ts: number | null | undefined): string => {
    if (!ts) return "-";
    return new Date(ts * 1000).toLocaleString();
  };

  // Truncate path for display
  const truncatePath = (path: string, maxLen = 60): string => {
    if (path.length <= maxLen) return path;
    const start = path.substring(0, 30);
    const end = path.substring(path.length - 27);
    return `${start}...${end}`;
  };

  // Render
  return (
    <div style={{ padding: "20px" }}>
      {/* Header */}
      <div style={{ marginBottom: "20px" }}>
        <h1 style={{ marginBottom: "10px" }}>Queue Management</h1>
        <div style={{ display: "flex", gap: "20px", alignItems: "center" }}>
          <span>
            SSE:{" "}
            <span
              style={{
                color: connected ? "var(--accent-green)" : "var(--accent-red)",
              }}
            >
              {connected ? "Connected" : "Disconnected"}
            </span>
          </span>
        </div>
      </div>

      {/* Summary badges */}
      <div
        style={{
          display: "flex",
          gap: "15px",
          marginBottom: "20px",
          flexWrap: "wrap",
        }}
      >
        <div style={badgeStyle}>
          <span style={{ fontSize: "24px", fontWeight: "bold" }}>
            {summary.pending}
          </span>
          <span style={{ fontSize: "12px", opacity: 0.8 }}>Pending</span>
        </div>
        <div style={badgeStyle}>
          <span style={{ fontSize: "24px", fontWeight: "bold" }}>
            {summary.running}
          </span>
          <span style={{ fontSize: "12px", opacity: 0.8 }}>Running</span>
        </div>
        <div style={badgeStyle}>
          <span style={{ fontSize: "24px", fontWeight: "bold" }}>
            {summary.completed}
          </span>
          <span style={{ fontSize: "12px", opacity: 0.8 }}>Completed</span>
        </div>
        <div style={badgeStyle}>
          <span style={{ fontSize: "24px", fontWeight: "bold" }}>
            {summary.errors}
          </span>
          <span style={{ fontSize: "12px", opacity: 0.8 }}>Errors</span>
        </div>
      </div>

      {/* Filter bar */}
      <div
        style={{
          display: "flex",
          gap: "10px",
          marginBottom: "20px",
          flexWrap: "wrap",
        }}
      >
        <div style={{ display: "flex", gap: "5px" }}>
          {(
            ["all", "pending", "running", "done", "error"] as StatusFilter[]
          ).map((filter) => (
            <button
              key={filter}
              onClick={() => {
                setStatusFilter(filter);
                setOffset(0); // Reset to first page
              }}
              style={{
                ...buttonStyle,
                ...(statusFilter === filter ? activeButtonStyle : {}),
              }}
              disabled={loading}
            >
              {filter.charAt(0).toUpperCase() + filter.slice(1)}
            </button>
          ))}
        </div>

        <div style={{ marginLeft: "auto", display: "flex", gap: "5px" }}>
          <button
            onClick={loadQueue}
            style={buttonStyle}
            disabled={loading || actionLoading}
          >
            Refresh
          </button>
          <button
            onClick={clearCompleted}
            style={buttonStyle}
            disabled={loading || actionLoading || summary.completed === 0}
          >
            Clear Completed
          </button>
          <button
            onClick={clearErrors}
            style={buttonStyle}
            disabled={loading || actionLoading || summary.errors === 0}
          >
            Clear Errors
          </button>
          <button
            onClick={clearAll}
            style={{ ...buttonStyle, ...dangerButtonStyle }}
            disabled={loading || actionLoading}
          >
            Clear All
          </button>
        </div>
      </div>

      {/* Loading state */}
      {loading && (
        <div style={{ textAlign: "center", padding: "40px" }}>
          <p>Loading queue...</p>
        </div>
      )}

      {/* Error state */}
      {error && (
        <div
          style={{
            padding: "20px",
            backgroundColor: "var(--accent-red)",
            borderRadius: "6px",
            marginBottom: "20px",
          }}
        >
          <strong>Error:</strong> {error}
        </div>
      )}

      {/* Jobs table */}
      {!loading && !error && (
        <>
          {jobs.length === 0 && total === 0 ? (
            <div
              style={{
                textAlign: "center",
                padding: "60px 20px",
                backgroundColor: "#1a1a1a",
                borderRadius: "8px",
                border: "1px solid #333",
              }}
            >
              <p style={{ fontSize: "18px", color: "#888", marginBottom: "10px" }}>
                No jobs in queue
              </p>
              <p style={{ fontSize: "14px", color: "#666" }}>
                {statusFilter !== "all"
                  ? `No ${statusFilter} jobs found`
                  : "Queue is empty"}
              </p>
            </div>
          ) : (
            <>
              <div style={{ overflowX: "auto" }}>
                <table style={tableStyle}>
              <thead>
                <tr>
                  <th style={thStyle}>ID</th>
                  <th style={thStyle}>File Path</th>
                  <th style={thStyle}>Status</th>
                  <th style={thStyle}>Created</th>
                  <th style={thStyle}>Started</th>
                  <th style={thStyle}>Error</th>
                  <th style={thStyle}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {jobs.length === 0 ? (
                  <tr>
                    <td
                      colSpan={7}
                      style={{ textAlign: "center", padding: "40px" }}
                    >
                      No jobs found
                    </td>
                  </tr>
                ) : (
                  jobs.map((job) => (
                    <tr key={job.id} style={trStyle}>
                      <td style={tdStyle}>{job.id}</td>
                      <td style={tdStyle} title={job.path}>
                        {truncatePath(job.path)}
                      </td>
                      <td style={tdStyle}>
                        <span style={getStatusBadgeStyle(job.status)}>
                          {job.status}
                        </span>
                      </td>
                      <td style={tdStyle}>{formatTimestamp(job.created_at)}</td>
                      <td style={tdStyle}>{formatTimestamp(job.started_at)}</td>
                      <td
                        style={{
                          ...tdStyle,
                          fontSize: "12px",
                          color: "var(--accent-red)",
                        }}
                      >
                        {job.error_message || "-"}
                      </td>
                      <td style={tdStyle}>
                        {(job.status === "pending" ||
                          job.status === "error") && (
                          <button
                            onClick={() => removeJob(job.id)}
                            style={{ ...buttonStyle, ...smallButtonStyle }}
                            disabled={actionLoading}
                          >
                            Remove
                          </button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div
              style={{
                marginTop: "20px",
                display: "flex",
                gap: "10px",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <button
                onClick={prevPage}
                style={buttonStyle}
                disabled={currentPage === 1 || loading || actionLoading}
              >
                ← Previous
              </button>

              <span style={{ padding: "0 10px" }}>
                Page {currentPage} of {totalPages} ({total} total)
              </span>

              <button
                onClick={nextPage}
                style={buttonStyle}
                disabled={currentPage >= totalPages || loading || actionLoading}
              >
                Next →
              </button>
            </div>
          )}
            </>
          )}
        </>
      )}
    </div>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Styles
// ──────────────────────────────────────────────────────────────────────

const badgeStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  alignItems: "center",
  padding: "15px 25px",
  backgroundColor: "var(--bg-secondary)",
  borderRadius: "8px",
  border: "1px solid var(--border-color)",
};

const buttonStyle: React.CSSProperties = {
  padding: "8px 16px",
  backgroundColor: "var(--bg-secondary)",
  border: "1px solid var(--border-color)",
  borderRadius: "6px",
  color: "var(--text-primary)",
  cursor: "pointer",
  fontSize: "14px",
  transition: "all 0.2s",
};

const activeButtonStyle: React.CSSProperties = {
  backgroundColor: "var(--accent-blue)",
  borderColor: "var(--accent-blue)",
};

const dangerButtonStyle: React.CSSProperties = {
  backgroundColor: "var(--accent-red)",
  borderColor: "var(--accent-red)",
};

const smallButtonStyle: React.CSSProperties = {
  padding: "4px 12px",
  fontSize: "12px",
};

const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  backgroundColor: "var(--bg-secondary)",
  borderRadius: "8px",
  overflow: "hidden",
};

const thStyle: React.CSSProperties = {
  padding: "12px",
  textAlign: "left",
  backgroundColor: "var(--bg-primary)",
  borderBottom: "2px solid var(--border-color)",
  fontWeight: 600,
  fontSize: "14px",
};

const tdStyle: React.CSSProperties = {
  padding: "12px",
  borderBottom: "1px solid var(--border-color)",
  fontSize: "14px",
};

const trStyle: React.CSSProperties = {
  transition: "background-color 0.2s",
};

const getStatusBadgeStyle = (status: string): React.CSSProperties => {
  const baseStyle: React.CSSProperties = {
    padding: "4px 8px",
    borderRadius: "4px",
    fontSize: "12px",
    fontWeight: 600,
    display: "inline-block",
  };

  switch (status) {
    case "pending":
      return { ...baseStyle, backgroundColor: "#666", color: "#fff" };
    case "running":
      return {
        ...baseStyle,
        backgroundColor: "var(--accent-blue)",
        color: "#fff",
      };
    case "done":
      return {
        ...baseStyle,
        backgroundColor: "var(--accent-green)",
        color: "#fff",
      };
    case "error":
      return {
        ...baseStyle,
        backgroundColor: "var(--accent-red)",
        color: "#fff",
      };
    default:
      return baseStyle;
  }
};
