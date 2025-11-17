import { useEffect, useState } from "react";

import { api } from "../shared/api";

/**
 * Dashboard page component.
 *
 * Landing page showing:
 * - System overview
 * - Queue summary
 * - Library stats
 */

interface QueueSummary {
  pending: number;
  running: number;
  completed: number;
  errors: number;
}

interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

export function DashboardPage() {
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadDashboard = async () => {
    try {
      setLoading(true);
      setError(null);

      const [queue, library] = await Promise.all([
        api.queue.getStatus(),
        api.library.getStats(),
      ]);

      setQueueSummary(queue);
      setLibraryStats(library);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load dashboard data"
      );
      console.error("[Dashboard] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  const formatDuration = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  return (
    <div style={{ padding: "2rem" }}>
      <h1>Dashboard</h1>

      {loading && <p style={{ marginTop: "2rem" }}>Loading dashboard...</p>}
      {error && (
        <p style={{ color: "var(--accent-red)", marginTop: "2rem" }}>
          Error: {error}
        </p>
      )}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "1.5rem", marginTop: "2rem" }}>
          {/* Queue Summary */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Queue Summary</h2>
            {queueSummary && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                  gap: "15px",
                }}
              >
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Pending</div>
                  <div style={styles.statValue}>{queueSummary.pending}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Running</div>
                  <div style={styles.statValue}>{queueSummary.running}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Completed</div>
                  <div style={styles.statValue}>{queueSummary.completed}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Errors</div>
                  <div style={styles.statValue}>{queueSummary.errors}</div>
                </div>
              </div>
            )}
          </section>

          {/* Library Stats */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Library Stats</h2>
            {libraryStats && (
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                  gap: "15px",
                }}
              >
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Total Files</div>
                  <div style={styles.statValue}>{libraryStats.total_files}</div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Artists</div>
                  <div style={styles.statValue}>
                    {libraryStats.unique_artists}
                  </div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Albums</div>
                  <div style={styles.statValue}>
                    {libraryStats.unique_albums}
                  </div>
                </div>
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Total Duration</div>
                  <div style={styles.statValue}>
                    {formatDuration(libraryStats.total_duration_seconds)}
                  </div>
                </div>
              </div>
            )}
          </section>

          {/* Recent Activity placeholder */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Recent Activity</h2>
            <p style={styles.placeholder}>
              Recently processed tracks and system events will appear here.
            </p>
          </section>
        </div>
      )}
    </div>
  );
}

const styles = {
  section: {
    backgroundColor: "#1a1a1a",
    padding: "1.5rem",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  sectionTitle: {
    fontSize: "1.25rem",
    marginBottom: "1rem",
    color: "#fff",
  },
  placeholder: {
    color: "#888",
    fontStyle: "italic" as const,
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
};
