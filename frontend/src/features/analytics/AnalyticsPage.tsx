/**
 * Analytics page.
 *
 * Features:
 * - Tag frequency statistics
 * - Mood distribution
 * - Tag correlations
 * - Co-occurrence search
 */

import { useEffect, useState } from "react";

import { api } from "../../shared/api";

interface TagFrequency {
  tag_key: string;
  total_count: number;
  unique_values: number;
}

interface MoodDistribution {
  mood: string;
  count: number;
  percentage: number;
}

export function AnalyticsPage() {
  const [tagFrequencies, setTagFrequencies] = useState<TagFrequency[]>([]);
  const [moodDistribution, setMoodDistribution] = useState<MoodDistribution[]>(
    []
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);



  const loadAnalytics = async () => {
    try {
      setLoading(true);
      setError(null);

      const [tagFreqData, moodData] = await Promise.all([
        api.analytics.getTagFrequencies(50),
        api.analytics.getMoodDistribution(),
      ]);

      setTagFrequencies(tagFreqData.tag_frequencies);
      setMoodDistribution(moodData.mood_distribution);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load analytics");
      console.error("[Analytics] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadAnalytics();
  }, []);



  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Analytics</h1>

      {loading && <p>Loading analytics data...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "20px" }}>
          {/* Mood Distribution */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Mood Distribution</h2>
            <div style={{ display: "grid", gap: "10px" }}>
              {moodDistribution.map((mood) => (
                <div key={mood.mood} style={styles.moodRow}>
                  <span style={styles.moodLabel}>{mood.mood}</span>
                  <span style={styles.moodCount}>
                    {mood.count} ({mood.percentage.toFixed(1)}%)
                  </span>
                  <div
                    style={{
                      ...styles.moodBar,
                      width: `${mood.percentage}%`,
                    }}
                  />
                </div>
              ))}
            </div>
          </section>

          {/* Tag Frequencies */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Tag Frequencies (Top 50)</h2>
            <div style={{ overflowX: "auto" }}>
              <table style={styles.table}>
                <thead>
                  <tr>
                    <th style={styles.th}>Tag</th>
                    <th style={styles.th}>Count</th>
                  </tr>
                </thead>
                <tbody>
                  {tagFrequencies.map((tag) => (
                    <tr key={tag.tag_key}>
                      <td style={styles.td}>{tag.tag_key}</td>
                      <td style={styles.td}>{tag.total_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
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
  moodRow: {
    position: "relative" as const,
    display: "flex",
    justifyContent: "space-between",
    padding: "10px",
    backgroundColor: "#222",
    borderRadius: "4px",
    overflow: "hidden",
  },
  moodLabel: {
    zIndex: 1,
    position: "relative" as const,
  },
  moodCount: {
    zIndex: 1,
    position: "relative" as const,
    color: "#888",
  },
  moodBar: {
    position: "absolute" as const,
    top: 0,
    left: 0,
    height: "100%",
    backgroundColor: "rgba(74, 158, 255, 0.2)",
    transition: "width 0.3s ease",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse" as const,
  },
  th: {
    textAlign: "left" as const,
    padding: "10px",
    backgroundColor: "#222",
    borderBottom: "2px solid #444",
  },
  td: {
    padding: "10px",
    borderBottom: "1px solid #333",
  },
  input: {
    flex: 1,
    padding: "10px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
  },
  button: {
    padding: "10px 20px",
    backgroundColor: "#4a9eff",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
    cursor: "pointer",
  },
  list: {
    listStyle: "none",
    padding: 0,
    margin: 0,
    display: "grid",
    gap: "5px",
  },
};
