/**
 * Inspect Tags page.
 *
 * Features:
 * - View tags from a specific audio file
 * - Display namespace and tag count
 * - Show all tags with their values
 * - Browse filesystem to select file
 */

import { useState } from "react";

import { ServerFilePicker } from "../../components/ServerFilePicker";
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
  const [showPicker, setShowPicker] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeSuccess, setRemoveSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;

    try {
      setLoading(true);
      setError(null);
      setRemoveSuccess(null);
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

  const handleRemoveTags = async () => {
    if (!filePath.trim()) return;
    if (!confirm(`Remove all tags from ${filePath}?\n\nThis cannot be undone!`)) return;

    try {
      setRemoving(true);
      setError(null);
      setRemoveSuccess(null);
      const result = await api.tags.removeTags(filePath);
      setRemoveSuccess(`Removed ${result.removed} tag(s) from ${result.path}`);
      // Refresh tags to show empty state
      const data = await api.tags.showTags(filePath);
      setTagsData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove tags");
      console.error("[Inspect] Remove error:", err);
    } finally {
      setRemoving(false);
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
              placeholder="Enter relative path to audio file"
              style={styles.input}
              disabled={loading}
            />
            <button
              type="button"
              onClick={() => setShowPicker(!showPicker)}
              style={styles.browseButton}
              disabled={loading}
            >
              {showPicker ? "Hide" : "Browse..."}
            </button>
            <button
              type="submit"
              style={styles.button}
              disabled={loading || !filePath.trim()}
            >
              {loading ? "Loading..." : "Inspect"}
            </button>
          </div>
        </form>
        {showPicker && (
          <div style={{ marginTop: "15px" }}>
            <ServerFilePicker
              value={filePath}
              onChange={(newPath) => {
                setFilePath(newPath);
                setShowPicker(false);
              }}
              mode="file"
              label="Select Audio File"
            />
          </div>
        )}
      </section>

      {error && (
        <section style={{ ...styles.section, marginTop: "20px" }}>
          <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>
        </section>
      )}

      {removeSuccess && (
        <section style={{ ...styles.section, marginTop: "20px" }}>
          <p style={{ color: "#4a9eff" }}>{removeSuccess}</p>
        </section>
      )}

      {tagsData && (
        <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
          {/* Metadata */}
          <section style={styles.section}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "15px" }}>
              <h2 style={{ ...styles.sectionTitle, marginBottom: 0 }}>File Metadata</h2>
              {tagsData.count > 0 && (
                <button
                  onClick={handleRemoveTags}
                  disabled={removing}
                  style={styles.removeButton}
                  title="Remove all tags from this file"
                >
                  {removing ? "Removing..." : "Remove All Tags"}
                </button>
              )}
            </div>
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
  browseButton: {
    padding: "10px 20px",
    backgroundColor: "#6c757d",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
    cursor: "pointer",
  },
  removeButton: {
    padding: "8px 16px",
    backgroundColor: "#dc3545",
    border: "none",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "0.9rem",
    cursor: "pointer",
    fontWeight: "bold" as const,
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
