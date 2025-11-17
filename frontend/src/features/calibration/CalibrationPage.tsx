/**
 * Calibration management page.
 *
 * Features:
 * - Generate new calibration from library data
 * - Apply calibration to library (recalibrate all files)
 * - View calibration queue status
 * - Clear calibration queue
 */

import { useEffect, useState } from "react";

import { api } from "../../shared/api";

interface CalibrationStatus {
  pending: number;
  running: number;
  completed: number;
  errors: number;
  worker_alive: boolean;
  worker_busy: boolean;
}

export function CalibrationPage() {
  const [status, setStatus] = useState<CalibrationStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [actionLoading, setActionLoading] = useState(false);

  const loadStatus = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.calibration.getStatus();
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
    if (!confirm("Generate new calibration? This analyzes all library files."))
      return;

    try {
      setActionLoading(true);
      await api.calibration.generate(true);
      alert("Calibration generated successfully!");
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "Failed to generate calibration"
      );
    } finally {
      setActionLoading(false);
    }
  };

  const handleApply = async () => {
    if (
      !confirm(
        "Apply calibration to entire library? This will queue all files for reprocessing."
      )
    )
      return;

    try {
      setActionLoading(true);
      const result = await api.calibration.apply();
      alert(`Queued ${result.queued} files for recalibration`);
      await loadStatus();
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to apply calibration");
    } finally {
      setActionLoading(false);
    }
  };

  const handleClear = async () => {
    if (!confirm("Clear all calibration queue jobs?")) return;

    try {
      setActionLoading(true);
      const result = await api.calibration.clear();
      alert(`Cleared ${result.cleared} jobs`);
      await loadStatus();
    } catch (err) {
      alert(
        err instanceof Error ? err.message : "Failed to clear calibration queue"
      );
    } finally {
      setActionLoading(false);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Calibration</h1>

      {loading && <p>Loading calibration status...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {status && (
        <div style={{ display: "grid", gap: "20px" }}>
          {/* Status */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Calibration Queue Status</h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                gap: "15px",
              }}
            >
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Pending</div>
                <div style={styles.statValue}>{status.pending}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Running</div>
                <div style={styles.statValue}>{status.running}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Completed</div>
                <div style={styles.statValue}>{status.completed}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Errors</div>
                <div style={styles.statValue}>{status.errors}</div>
              </div>
            </div>
            <div style={{ marginTop: "15px" }}>
              <p>
                Worker:{" "}
                <span
                  style={{
                    color: status.worker_alive
                      ? "var(--accent-green)"
                      : "var(--accent-red)",
                  }}
                >
                  {status.worker_alive ? "Alive" : "Not Running"}
                </span>
                {status.worker_alive && (
                  <span style={{ marginLeft: "15px" }}>
                    Status:{" "}
                    <span
                      style={{
                        color: status.worker_busy
                          ? "var(--accent-yellow)"
                          : "var(--accent-green)",
                      }}
                    >
                      {status.worker_busy ? "Busy" : "Idle"}
                    </span>
                  </span>
                )}
              </p>
            </div>
          </section>

          {/* Controls */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Actions</h2>
            <div style={{ display: "grid", gap: "10px" }}>
              <button
                onClick={handleGenerate}
                disabled={actionLoading}
                style={styles.button}
              >
                Generate Calibration
              </button>
              <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
                Analyzes all tagged files to compute min/max scaling parameters
                for normalizing model outputs to a common [0,1] scale.
              </p>

              <button
                onClick={handleApply}
                disabled={actionLoading}
                style={{ ...styles.button, marginTop: "10px" }}
              >
                Apply Calibration to Library
              </button>
              <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
                Queues all library files for recalibration. Updates tier and
                mood tags by applying calibration to existing raw scores.
              </p>

              <button
                onClick={handleClear}
                disabled={actionLoading}
                style={{
                  ...styles.button,
                  marginTop: "10px",
                  backgroundColor: "#d32f2f",
                }}
              >
                Clear Queue
              </button>
              <p style={{ fontSize: "0.875rem", color: "#888", margin: 0 }}>
                Clears all pending and completed recalibration jobs from the
                queue.
              </p>
            </div>
          </section>
        </div>
      )}
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
  statCard: {
    backgroundColor: "#222",
    padding: "15px",
    borderRadius: "6px",
    border: "1px solid #444",
  },
  statLabel: {
    fontSize: "0.875rem",
    color: "#888",
    marginBottom: "5px",
  },
  statValue: {
    fontSize: "1.5rem",
    fontWeight: "bold" as const,
    color: "#4a9eff",
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
