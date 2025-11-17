/**
 * Inspect Tags page.
 *
 * Features:
 * - View tags from a specific audio file
 * - Display namespace and tag count
 * - Show all tags with their values
 */

import { useState } from "react";

import { api } from "../../shared/api";

interface TagsData {
  path: string;
  namespace: string;
  tags: Record<string, unknown>;
  count: number;
}

export function InspectTagsPage() {
  const [filePath, setFilePath] = useState("");
  const [tagsData, setTagsData] = useState<TagsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;

    try {
      setLoading(true);
      setError(null);
      const data = await api.tags.showTags(filePath);
      setTagsData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tags");
      setTagsData(null);
      console.error("[Inspect] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const renderValue = (value: unknown): string => {
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    return String(value);
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Inspect Tags</h1>

      <section style={styles.section}>
        <h2 style={styles.sectionTitle}>File Path</h2>
        <form onSubmit={handleSubmit}>
          <div style={{ display: "flex", gap: "10px" }}>
            <input
              type="text"
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              placeholder="Enter full path to audio file"
              style={styles.input}
              disabled={loading}
            />
            <button
              type="submit"
              style={styles.button}
              disabled={loading || !filePath.trim()}
            >
              {loading ? "Loading..." : "Inspect"}
            </button>
          </div>
        </form>
      </section>

      {error && (
        <section style={{ ...styles.section, marginTop: "20px" }}>
          <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>
        </section>
      )}

      {tagsData && (
        <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
          {/* Metadata */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>File Metadata</h2>
            <div style={{ display: "grid", gap: "10px" }}>
              <div>
                <span style={styles.label}>Path:</span>
                <span style={styles.value}>{tagsData.path}</span>
              </div>
              <div>
                <span style={styles.label}>Namespace:</span>
                <span style={styles.value}>{tagsData.namespace}</span>
              </div>
              <div>
                <span style={styles.label}>Tag Count:</span>
                <span style={styles.value}>{tagsData.count}</span>
              </div>
            </div>
          </section>

          {/* Tags */}
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Tags</h2>
            {tagsData.count === 0 ? (
              <p style={{ color: "#888", fontStyle: "italic" }}>
                No tags found in this file.
              </p>
            ) : (
              <div style={{ overflowX: "auto" }}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Tag Key</th>
                      <th style={styles.th}>Value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(tagsData.tags).map(([key, value]) => (
                      <tr key={key}>
                        <td style={styles.td}>{key}</td>
                        <td style={styles.td}>{renderValue(value)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </div>
      )}

      {!tagsData && !error && (
        <section style={{ ...styles.section, marginTop: "20px" }}>
          <p style={{ color: "#888", fontStyle: "italic" }}>
            Enter a file path above to inspect its tags.
          </p>
        </section>
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
  label: {
    fontWeight: "bold" as const,
    marginRight: "10px",
    color: "#888",
  },
  value: {
    color: "#fff",
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
    wordBreak: "break-word" as const,
  },
};
