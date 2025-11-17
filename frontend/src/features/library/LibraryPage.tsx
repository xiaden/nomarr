/**
 * Library management page.
 *
 * Features:
 * - Library statistics
 * - Real-time updates via SSE
 */

import { useEffect, useState } from "react";

import { api } from "../../shared/api";

interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

export function LibraryPage() {
  const [stats, setStats] = useState<LibraryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadStats = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.library.getStats();
      setStats(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load stats");
      console.error("[Library] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadStats();
  }, []);

  const formatDuration = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Library Management</h1>

      {loading && <p>Loading library statistics...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {stats && (
        <div style={{ display: "grid", gap: "20px" }}>
          {/* Statistics */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Library Statistics</h2>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
                gap: "15px",
              }}
            >
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Total Files</div>
                <div style={styles.statValue}>{stats.total_files}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Artists</div>
                <div style={styles.statValue}>{stats.unique_artists}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Albums</div>
                <div style={styles.statValue}>{stats.unique_albums}</div>
              </div>
              <div style={styles.statCard}>
                <div style={styles.statLabel}>Total Duration</div>
                <div style={styles.statValue}>
                  {formatDuration(stats.total_duration_seconds)}
                </div>
              </div>
            </div>
          </section>

          {/* Placeholder for future scanner controls */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Scanner Controls</h2>
            <p style={{ color: "#888", fontStyle: "italic" }}>
              Scanner controls will be implemented when scanner service is
              available.
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
};
