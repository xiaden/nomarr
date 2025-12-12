/**
 * QueueJobsTable component.
 * Displays queue jobs in a table with pagination.
 */

import type { QueueJob } from "../../../shared/types";

interface QueueJobsTableProps {
  jobs: QueueJob[];
  total: number;
  currentPage: number;
  totalPages: number;
  onRemoveJob: (jobId: number) => Promise<void>;
  onNextPage: () => void;
  onPrevPage: () => void;
  statusFilter: string;
}

export function QueueJobsTable({
  jobs,
  total,
  currentPage,
  totalPages,
  onRemoveJob,
  onNextPage,
  onPrevPage,
  statusFilter,
}: QueueJobsTableProps) {
  const formatTimestamp = (ts: number | null | undefined): string => {
    if (!ts) return "-";
    return new Date(ts * 1000).toLocaleString();
  };

  const truncatePath = (path: string, maxLen = 60): string => {
    if (path.length <= maxLen) return path;
    const start = path.substring(0, 30);
    const end = path.substring(path.length - 27);
    return start + "..." + end;
  };

  const getStatusBadgeStyle = (status: string) => {
    const baseStyle = {
      padding: "4px 8px",
      borderRadius: "4px",
      fontSize: "12px",
      fontWeight: "bold" as const,
      color: "#fff",
    };
    
    let backgroundColor = "#555";
    if (status === "running") backgroundColor = "#ff9800";
    else if (status === "done") backgroundColor = "#4caf50";
    else if (status === "error") backgroundColor = "#f44336";
    
    return { ...baseStyle, backgroundColor };
  };

  if (jobs.length === 0 && total === 0) {
    return (
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
    );
  }

  return (
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
                <td colSpan={7} style={{ textAlign: "center", padding: "40px" }}>
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
                    <button
                      onClick={() => onRemoveJob(job.id)}
                      style={removeButtonStyle}
                      disabled={job.status === "running"}
                    >
                      Remove
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {totalPages > 1 && (
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginTop: "20px",
            padding: "15px",
            backgroundColor: "#1a1a1a",
            borderRadius: "6px",
            border: "1px solid #333",
          }}
        >
          <button
            onClick={onPrevPage}
            disabled={currentPage === 1}
            style={paginationButtonStyle}
          >
            Previous
          </button>
          <span>
            Page {currentPage} of {totalPages} ({total} total jobs)
          </span>
          <button
            onClick={onNextPage}
            disabled={currentPage === totalPages}
            style={paginationButtonStyle}
          >
            Next
          </button>
        </div>
      )}
    </>
  );
}

const tableStyle = {
  width: "100%",
  borderCollapse: "collapse" as const,
  backgroundColor: "#1a1a1a",
  borderRadius: "8px",
  overflow: "hidden",
};

const thStyle = {
  padding: "12px",
  textAlign: "left" as const,
  borderBottom: "2px solid #333",
  fontWeight: "bold" as const,
  fontSize: "14px",
};

const tdStyle = {
  padding: "12px",
  borderBottom: "1px solid #2a2a2a",
  fontSize: "14px",
};

const trStyle = {
  transition: "background-color 0.15s",
};

const removeButtonStyle = {
  padding: "4px 12px",
  backgroundColor: "#d32f2f",
  border: "none",
  borderRadius: "4px",
  color: "#fff",
  cursor: "pointer",
  fontSize: "12px",
};

const paginationButtonStyle = {
  padding: "8px 16px",
  backgroundColor: "#4a9eff",
  border: "none",
  borderRadius: "4px",
  color: "#fff",
  cursor: "pointer",
  fontSize: "14px",
};
