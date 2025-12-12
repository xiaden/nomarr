/**
 * QueueFilters component.
 * Status filter buttons and action buttons for queue management.
 */

type StatusFilter = "all" | "pending" | "running" | "done" | "error";

interface QueueFiltersProps {
  statusFilter: StatusFilter;
  onFilterChange: (filter: StatusFilter) => void;
  loading: boolean;
  actionLoading: boolean;
  summary: {
    pending: number;
    running: number;
    completed: number;
    errors: number;
  };
  onRefresh: () => void;
  onClearCompleted: () => Promise<void>;
  onClearErrors: () => Promise<void>;
  onClearAll: () => Promise<void>;
}

export function QueueFilters({
  statusFilter,
  onFilterChange,
  loading,
  actionLoading,
  summary,
  onRefresh,
  onClearCompleted,
  onClearErrors,
  onClearAll,
}: QueueFiltersProps) {
  return (
    <div
      style={{
        display: "flex",
        gap: "10px",
        marginBottom: "20px",
        flexWrap: "wrap",
      }}
    >
      <div style={{ display: "flex", gap: "5px" }}>
        {(["all", "pending", "running", "done", "error"] as StatusFilter[]).map(
          (filter) => (
            <button
              key={filter}
              onClick={() => onFilterChange(filter)}
              style={{
                ...buttonStyle,
                ...(statusFilter === filter ? activeButtonStyle : {}),
              }}
              disabled={loading}
            >
              {filter.charAt(0).toUpperCase() + filter.slice(1)}
            </button>
          )
        )}
      </div>

      <div style={{ marginLeft: "auto", display: "flex", gap: "5px" }}>
        <button
          onClick={onRefresh}
          style={buttonStyle}
          disabled={loading || actionLoading}
        >
          Refresh
        </button>
        <button
          onClick={onClearCompleted}
          style={buttonStyle}
          disabled={loading || actionLoading || summary.completed === 0}
        >
          Clear Completed
        </button>
        <button
          onClick={onClearErrors}
          style={buttonStyle}
          disabled={loading || actionLoading || summary.errors === 0}
        >
          Clear Errors
        </button>
        <button
          onClick={onClearAll}
          style={{ ...buttonStyle, ...dangerButtonStyle }}
          disabled={loading || actionLoading}
        >
          Clear All
        </button>
      </div>
    </div>
  );
}

const buttonStyle = {
  padding: "8px 16px",
  backgroundColor: "#2a2a2a",
  border: "1px solid #444",
  borderRadius: "4px",
  color: "#fff",
  cursor: "pointer",
  fontSize: "14px",
  transition: "all 0.2s",
};

const activeButtonStyle = {
  backgroundColor: "#4a9eff",
  borderColor: "#4a9eff",
};

const dangerButtonStyle = {
  backgroundColor: "#d32f2f",
  borderColor: "#d32f2f",
};
