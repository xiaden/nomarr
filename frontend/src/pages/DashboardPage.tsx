import { useEffect, useRef, useState } from "react";

import { useSSE } from "../hooks/useSSE";
import { api } from "../shared/api";

/**
 * Dashboard page component.
 *
 * Landing page showing:
 * - System overview with real-time updates
 * - Queue summary with progress tracking
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

interface ProgressTracking {
  totalJobs: number;
  completedCount: number;
  filesPerMinute: number;
  estimatedMinutesRemaining: number | null;
  lastUpdateTime: number;
}

export function DashboardPage() {
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressTracking | null>(null);

  // Track completed count over time for velocity calculation
  const completedHistoryRef = useRef<Array<{ count: number; time: number }>>(
    []
  );

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

      // Initialize progress tracking
      updateProgressTracking(queue);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load dashboard data"
      );
      console.error("[Dashboard] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const updateProgressTracking = (queue: QueueSummary) => {
    const now = Date.now();
    const total = queue.pending + queue.running + queue.completed + queue.errors;
    const completed = queue.completed;

    // Track completed count history (last 5 minutes)
    const history = completedHistoryRef.current;
    history.push({ count: completed, time: now });

    // Keep only last 5 minutes of data
    const fiveMinutesAgo = now - 5 * 60 * 1000;
    completedHistoryRef.current = history.filter(
      (entry) => entry.time > fiveMinutesAgo
    );

    // Calculate velocity (files per minute)
    let filesPerMinute = 0;
    let estimatedMinutesRemaining: number | null = null;

    if (completedHistoryRef.current.length >= 2) {
      const oldest = completedHistoryRef.current[0];
      const newest = completedHistoryRef.current[completedHistoryRef.current.length - 1];
      const timeDiffMinutes = (newest.time - oldest.time) / (1000 * 60);
      const countDiff = newest.count - oldest.count;

      if (timeDiffMinutes > 0 && countDiff > 0) {
        filesPerMinute = countDiff / timeDiffMinutes;

        // Calculate ETA for remaining jobs
        const remaining = queue.pending + queue.running;
        if (remaining > 0 && filesPerMinute > 0) {
          estimatedMinutesRemaining = remaining / filesPerMinute;
        }
      }
    }

    setProgress({
      totalJobs: total,
      completedCount: completed,
      filesPerMinute: Math.round(filesPerMinute * 10) / 10,
      estimatedMinutesRemaining,
      lastUpdateTime: now,
    });
  };

  useEffect(() => {
    loadDashboard();
  }, []);

  // SSE real-time updates
  const { connected } = useSSE({
    onMessage: (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log("[Dashboard] SSE update:", data);

        // Update queue summary if data contains queue info
        if (data.queue) {
          setQueueSummary({
            pending: data.queue.pending || 0,
            running: data.queue.running || 0,
            completed: data.queue.completed || 0,
            errors: data.queue.errors || 0,
          });

          // Update progress tracking
          updateProgressTracking({
            pending: data.queue.pending || 0,
            running: data.queue.running || 0,
            completed: data.queue.completed || 0,
            errors: data.queue.errors || 0,
          });
        }
      } catch (err) {
        console.error("[Dashboard] Failed to parse SSE message:", err);
      }
    },
    onError: (error) => {
      console.error("[Dashboard] SSE error:", error);
    },
  });

  const formatDuration = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  const formatETA = (minutes: number | null): string => {
    if (minutes === null || minutes <= 0) return "—";
    if (minutes < 1) return "< 1 min";
    if (minutes < 60) return `${Math.round(minutes)} min`;
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    return `${hours}h ${mins}m`;
  };

  const hasActiveJobs =
    queueSummary && (queueSummary.pending > 0 || queueSummary.running > 0);
  const progressPercent =
    progress && progress.totalJobs > 0
      ? Math.round((progress.completedCount / progress.totalJobs) * 100)
      : 0;

  return (
    <div style={{ padding: "2rem" }}>
      <h1>Dashboard</h1>

      {/* Connection Status */}
      <div
        style={{
          marginTop: "1rem",
          fontSize: "0.875rem",
          color: connected ? "#4ade80" : "#f87171",
        }}
      >
        {connected ? "● Live" : "● Disconnected"}
      </div>

      {loading && <p style={{ marginTop: "2rem" }}>Loading dashboard...</p>}
      {error && (
        <p style={{ color: "var(--accent-red)", marginTop: "2rem" }}>
          Error: {error}
        </p>
      )}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "1.5rem", marginTop: "2rem" }}>
          {/* Processing Status */}
          {hasActiveJobs && progress && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Processing Status</h2>

              <div style={{ marginBottom: "1.5rem" }}>
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    marginBottom: "0.5rem",
                    fontSize: "0.875rem",
                    color: "#888",
                  }}
                >
                  <span>
                    {progress.completedCount} / {progress.totalJobs} files
                  </span>
                  <span>{progressPercent}%</span>
                </div>

                <div
                  style={{
                    width: "100%",
                    height: "8px",
                    backgroundColor: "#333",
                    borderRadius: "4px",
                    overflow: "hidden",
                  }}
                >
                  <div
                    style={{
                      width: `${progressPercent}%`,
                      height: "100%",
                      backgroundColor: "#4a9eff",
                      transition: "width 0.3s ease",
                    }}
                  />
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
                  gap: "15px",
                }}
              >
                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Velocity</div>
                  <div style={styles.statValue}>
                    {progress.filesPerMinute > 0
                      ? `${progress.filesPerMinute}/min`
                      : "—"}
                  </div>
                </div>

                <div style={styles.statCard}>
                  <div style={styles.statLabel}>ETA</div>
                  <div style={styles.statValue}>
                    {formatETA(progress.estimatedMinutesRemaining)}
                  </div>
                </div>

                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Active</div>
                  <div style={styles.statValue}>
                    {queueSummary?.running || 0}
                  </div>
                </div>

                <div style={styles.statCard}>
                  <div style={styles.statLabel}>Remaining</div>
                  <div style={styles.statValue}>
                    {queueSummary?.pending || 0}
                  </div>
                </div>
              </div>
            </section>
          )}

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
