/**
 * QueueSummary component.
 * Displays queue statistics badges and SSE connection status.
 */

interface QueueSummaryProps {
  summary: {
    pending: number;
    running: number;
    completed: number;
    errors: number;
  };
  connected: boolean;
}

export function QueueSummary({ summary, connected }: QueueSummaryProps) {
  return (
    <div>
      {/* SSE Status */}
      <div style={{ marginBottom: "20px" }}>
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
    </div>
  );
}

const badgeStyle = {
  display: "flex",
  flexDirection: "column" as const,
  alignItems: "center",
  padding: "15px 25px",
  backgroundColor: "#1a1a1a",
  borderRadius: "8px",
  border: "1px solid #333",
  minWidth: "100px",
};
