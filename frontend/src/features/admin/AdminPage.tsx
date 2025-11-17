/**
 * Admin page.
 *
 * Features:
 * - Worker control (pause/resume)
 * - Server restart
 */

import { useState } from "react";

import { api } from "../../shared/api";

export function AdminPage() {
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

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Admin</h1>

      <div style={{ display: "grid", gap: "20px" }}>
        {/* Worker Controls */}
        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>Worker Controls</h2>
          <div style={{ display: "grid", gap: "10px" }}>
            <button
              onClick={handlePauseWorker}
              disabled={actionLoading}
              style={styles.button}
            >
              Pause Worker
            </button>
            <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
              Stops the worker from processing queue jobs. Jobs remain in the
              queue.
            </p>

            <button
              onClick={handleResumeWorker}
              disabled={actionLoading}
              style={{ ...styles.button, marginTop: "10px" }}
            >
              Resume Worker
            </button>
            <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
              Starts the worker to process queue jobs.
            </p>
          </div>
        </section>

        {/* System Controls */}
        <section style={styles.section}>
          <h2 style={styles.sectionTitle}>System Controls</h2>
          <div style={{ display: "grid", gap: "10px" }}>
            <button
              onClick={handleRestart}
              disabled={actionLoading}
              style={{ ...styles.button, backgroundColor: "#d32f2f" }}
            >
              Restart Server
            </button>
            <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
              Restarts the API server. Useful after config changes. The page
              will reload automatically.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}

const styles = {
  section: {
    backgroundColor: "#1a1a1a",
    padding: "20px",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  sectionTitle: {
    fontSize: "1.25rem",
    marginBottom: "15px",
    color: "#fff",
  },
  button: {
    padding: "12px 20px",
    backgroundColor: "#4a9eff",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
    cursor: "pointer",
    transition: "background-color 0.2s",
  },
};
