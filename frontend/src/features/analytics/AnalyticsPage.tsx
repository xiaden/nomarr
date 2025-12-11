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

interface CoOccurrence {
  tag: string;
  count: number;
  percentage: number;
}

interface Artist {
  name: string;
  count: number;
  percentage: number;
}

interface Genre {
  name: string;
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

  // Co-occurrence search
  const [searchTag, setSearchTag] = useState("");
  const [totalOccurrences, setTotalOccurrences] = useState<number>(0);
  const [coOccurrences, setCoOccurrences] = useState<CoOccurrence[] | null>(
    null
  );
  const [topArtists, setTopArtists] = useState<Artist[] | null>(null);
  const [topGenres, setTopGenres] = useState<Genre[] | null>(null);
  const [coOccurrenceLoading, setCoOccurrenceLoading] = useState(false);
  const [coOccurrenceError, setCoOccurrenceError] = useState<string | null>(
    null
  );

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

  const handleCoOccurrenceSearch = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!searchTag.trim()) return;

    try {
      setCoOccurrenceLoading(true);
      setCoOccurrenceError(null);

      const data = await api.analytics.getTagCoOccurrences(searchTag, 10);
      setTotalOccurrences(data.total_occurrences);
      setCoOccurrences(data.co_occurrences);
      setTopArtists(data.top_artists);
      setTopGenres(data.top_genres);
    } catch (err) {
      setCoOccurrenceError(
        err instanceof Error ? err.message : "Failed to search co-occurrences"
      );
      console.error("[Analytics] Co-occurrence search error:", err);
    } finally {
      setCoOccurrenceLoading(false);
    }
  };

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

          {/* Co-occurrence Search */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Tag Value Co-occurrence Search</h2>
            <p style={{ marginBottom: "15px", color: "#888", fontSize: "0.9rem" }}>
              Search for any mood value (e.g., "happy", "dark", "energetic") to
              see which other moods, genres, and artists co-occur with it.
            </p>
            <form
              onSubmit={handleCoOccurrenceSearch}
              style={{ marginBottom: "15px" }}
            >
              <div style={{ display: "flex", gap: "10px" }}>
                <input
                  type="text"
                  value={searchTag}
                  onChange={(e) => setSearchTag(e.target.value)}
                  placeholder="Enter mood value (e.g., happy, dark, energetic)"
                  style={styles.input}
                  disabled={coOccurrenceLoading}
                />
                <button
                  type="submit"
                  style={styles.button}
                  disabled={coOccurrenceLoading}
                >
                  {coOccurrenceLoading ? "Searching..." : "Search"}
                </button>
              </div>
            </form>

            {coOccurrenceError && (
              <p style={{ color: "var(--accent-red)" }}>
                Error: {coOccurrenceError}
              </p>
            )}

            {coOccurrences && (
              <div style={{ display: "grid", gap: "15px" }}>
                <div style={{ marginBottom: "10px", color: "#aaa" }}>
                  <strong>Found {totalOccurrences} files</strong> with mood value "{searchTag}"
                </div>
                
                {coOccurrences.length > 0 ? (
                  <div>
                    <h3 style={{ fontSize: "1rem", marginBottom: "10px" }}>
                      Co-occurring Mood Values
                    </h3>
                    <ul style={styles.list}>
                      {coOccurrences.map((co) => (
                        <li key={co.tag}>
                          {co.tag}: {co.count} files ({co.percentage.toFixed(1)}%)
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : (
                  <p style={{ color: "#888" }}>
                    {totalOccurrences > 0 
                      ? "No other moods co-occur with this value." 
                      : "No files found with this mood value."}
                  </p>
                )}

                {topArtists && topArtists.length > 0 && (
                  <div>
                    <h3 style={{ fontSize: "1rem", marginBottom: "10px" }}>
                      Top Artists
                    </h3>
                    <ul style={styles.list}>
                      {topArtists.map((artist) => (
                        <li key={artist.name}>
                          {artist.name}: {artist.count} (
                          {artist.percentage.toFixed(1)}%)
                        </li>
                      ))}
                    </ul>
                  </div>
                )}

                {topGenres && topGenres.length > 0 && (
                  <div>
                    <h3 style={{ fontSize: "1rem", marginBottom: "10px" }}>
                      Top Genres
                    </h3>
                    <ul style={styles.list}>
                      {topGenres.map((genre) => (
                        <li key={genre.name}>
                          {genre.name}: {genre.count} (
                          {genre.percentage.toFixed(1)}%)
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
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
