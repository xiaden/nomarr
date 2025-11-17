/**
 * Navidrome integration page.
 *
 * Features:
 * - Preview tags for Navidrome config
 * - Generate Navidrome TOML configuration
 * - Preview Smart Playlist queries
 * - Generate Smart Playlist (.nsp) files
 */

import { useState } from "react";

import { api } from "../../shared/api";

interface TagPreview {
  tag_key: string;
  type: string;
  is_multivalue: boolean;
  summary: string;
  total_count: number;
}

export function NavidromePage() {
  const [activeTab, setActiveTab] = useState<"config" | "playlist">("config");

  // Config state
  const [preview, setPreview] = useState<TagPreview[] | null>(null);
  const [configText, setConfigText] = useState<string | null>(null);
  const [configLoading, setConfigLoading] = useState(false);
  const [configError, setConfigError] = useState<string | null>(null);

  // Playlist state
  const [playlistQuery, setPlaylistQuery] = useState("");
  const [playlistName, setPlaylistName] = useState("My Playlist");
  const [playlistComment, setPlaylistComment] = useState("");
  const [playlistLimit, setPlaylistLimit] = useState<number | undefined>(
    undefined
  );
  const [playlistSort, setPlaylistSort] = useState("");
  const [playlistPreview, setPlaylistPreview] = useState<Record<
    string,
    unknown
  > | null>(null);
  const [playlistContent, setPlaylistContent] = useState<string | null>(null);
  const [playlistLoading, setPlaylistLoading] = useState(false);
  const [playlistError, setPlaylistError] = useState<string | null>(null);

  // Config functions
  const handleLoadPreview = async () => {
    try {
      setConfigLoading(true);
      setConfigError(null);
      const data = await api.navidrome.getPreview();
      setPreview(data.tags);
    } catch (err) {
      setConfigError(
        err instanceof Error ? err.message : "Failed to load preview"
      );
    } finally {
      setConfigLoading(false);
    }
  };

  const handleGenerateConfig = async () => {
    try {
      setConfigLoading(true);
      setConfigError(null);
      const data = await api.navidrome.getConfig();
      setConfigText(data.config);
    } catch (err) {
      setConfigError(
        err instanceof Error ? err.message : "Failed to generate config"
      );
    } finally {
      setConfigLoading(false);
    }
  };

  // Playlist functions
  const handlePreviewPlaylist = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!playlistQuery.trim()) return;

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const data = await api.navidrome.previewPlaylist(playlistQuery, 10);
      setPlaylistPreview(data);
    } catch (err) {
      setPlaylistError(
        err instanceof Error ? err.message : "Failed to preview playlist"
      );
    } finally {
      setPlaylistLoading(false);
    }
  };

  const handleGeneratePlaylist = async () => {
    if (!playlistQuery.trim()) {
      alert("Query is required");
      return;
    }
    if (!playlistName.trim()) {
      alert("Playlist name is required");
      return;
    }

    try {
      setPlaylistLoading(true);
      setPlaylistError(null);
      const data = await api.navidrome.generatePlaylist({
        query: playlistQuery,
        playlist_name: playlistName,
        comment: playlistComment,
        limit: playlistLimit,
        sort: playlistSort || undefined,
      });
      setPlaylistContent(data.content);
    } catch (err) {
      setPlaylistError(
        err instanceof Error ? err.message : "Failed to generate playlist"
      );
    } finally {
      setPlaylistLoading(false);
    }
  };

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Navidrome Integration</h1>

      {/* Tabs */}
      <div style={styles.tabs}>
        <button
          onClick={() => setActiveTab("config")}
          style={{
            ...styles.tab,
            ...(activeTab === "config" ? styles.tabActive : {}),
          }}
        >
          Config Generator
        </button>
        <button
          onClick={() => setActiveTab("playlist")}
          style={{
            ...styles.tab,
            ...(activeTab === "playlist" ? styles.tabActive : {}),
          }}
        >
          Playlist Generator
        </button>
      </div>

      {/* Config Tab */}
      {activeTab === "config" && (
        <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Navidrome TOML Configuration</h2>
            <div style={{ display: "grid", gap: "10px" }}>
              <button
                onClick={handleLoadPreview}
                disabled={configLoading}
                style={styles.button}
              >
                {configLoading ? "Loading..." : "Load Tag Preview"}
              </button>
              <button
                onClick={handleGenerateConfig}
                disabled={configLoading}
                style={styles.button}
              >
                {configLoading ? "Generating..." : "Generate Config"}
              </button>
            </div>
            {configError && (
              <p style={{ color: "var(--accent-red)", marginTop: "10px" }}>
                Error: {configError}
              </p>
            )}
          </section>

          {preview && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Tag Preview</h2>
              <div style={{ overflowX: "auto" }}>
                <table style={styles.table}>
                  <thead>
                    <tr>
                      <th style={styles.th}>Tag</th>
                      <th style={styles.th}>Type</th>
                      <th style={styles.th}>Multivalue</th>
                      <th style={styles.th}>Count</th>
                      <th style={styles.th}>Summary</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.map((tag) => (
                      <tr key={tag.tag_key}>
                        <td style={styles.td}>{tag.tag_key}</td>
                        <td style={styles.td}>{tag.type}</td>
                        <td style={styles.td}>
                          {tag.is_multivalue ? "Yes" : "No"}
                        </td>
                        <td style={styles.td}>{tag.total_count}</td>
                        <td style={styles.td}>{tag.summary}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          )}

          {configText && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Generated Config</h2>
              <textarea
                readOnly
                value={configText}
                style={styles.textarea}
                rows={20}
              />
              <button
                onClick={() => {
                  navigator.clipboard.writeText(configText);
                  alert("Copied to clipboard!");
                }}
                style={{ ...styles.button, marginTop: "10px" }}
              >
                Copy to Clipboard
              </button>
            </section>
          )}
        </div>
      )}

      {/* Playlist Tab */}
      {activeTab === "playlist" && (
        <div style={{ display: "grid", gap: "20px", marginTop: "20px" }}>
          <section style={styles.section}>
            <h2 style={styles.sectionTitle}>Smart Playlist Generator</h2>
            <form onSubmit={handlePreviewPlaylist}>
              <div style={{ display: "grid", gap: "15px" }}>
                <div>
                  <label style={styles.label}>Query *</label>
                  <textarea
                    value={playlistQuery}
                    onChange={(e) => setPlaylistQuery(e.target.value)}
                    placeholder="e.g., tag:nom_happy > 0.8"
                    style={styles.textarea}
                    rows={3}
                    disabled={playlistLoading}
                    required
                  />
                </div>
                <div>
                  <label style={styles.label}>Playlist Name *</label>
                  <input
                    type="text"
                    value={playlistName}
                    onChange={(e) => setPlaylistName(e.target.value)}
                    style={styles.input}
                    disabled={playlistLoading}
                    required
                  />
                </div>
                <div>
                  <label style={styles.label}>Comment</label>
                  <input
                    type="text"
                    value={playlistComment}
                    onChange={(e) => setPlaylistComment(e.target.value)}
                    style={styles.input}
                    disabled={playlistLoading}
                  />
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr",
                    gap: "10px",
                  }}
                >
                  <div>
                    <label style={styles.label}>Limit</label>
                    <input
                      type="number"
                      value={playlistLimit ?? ""}
                      onChange={(e) =>
                        setPlaylistLimit(
                          e.target.value ? parseInt(e.target.value) : undefined
                        )
                      }
                      style={styles.input}
                      disabled={playlistLoading}
                      placeholder="Optional"
                    />
                  </div>
                  <div>
                    <label style={styles.label}>Sort</label>
                    <input
                      type="text"
                      value={playlistSort}
                      onChange={(e) => setPlaylistSort(e.target.value)}
                      style={styles.input}
                      disabled={playlistLoading}
                      placeholder="Optional"
                    />
                  </div>
                </div>
                <div style={{ display: "flex", gap: "10px" }}>
                  <button
                    type="submit"
                    style={styles.button}
                    disabled={playlistLoading}
                  >
                    {playlistLoading ? "Loading..." : "Preview Query"}
                  </button>
                  <button
                    type="button"
                    onClick={handleGeneratePlaylist}
                    style={styles.button}
                    disabled={playlistLoading}
                  >
                    {playlistLoading ? "Generating..." : "Generate .nsp"}
                  </button>
                </div>
              </div>
            </form>
            {playlistError && (
              <p style={{ color: "var(--accent-red)", marginTop: "10px" }}>
                Error: {playlistError}
              </p>
            )}
          </section>

          {playlistPreview && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Query Preview</h2>
              <pre style={styles.pre}>
                {JSON.stringify(playlistPreview, null, 2)}
              </pre>
            </section>
          )}

          {playlistContent && (
            <section style={styles.section}>
              <h2 style={styles.sectionTitle}>Generated Playlist (.nsp)</h2>
              <textarea
                readOnly
                value={playlistContent}
                style={styles.textarea}
                rows={15}
              />
              <button
                onClick={() => {
                  const blob = new Blob([playlistContent], {
                    type: "text/plain",
                  });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = `${playlistName}.nsp`;
                  a.click();
                  URL.revokeObjectURL(url);
                }}
                style={{ ...styles.button, marginTop: "10px" }}
              >
                Download .nsp File
              </button>
            </section>
          )}
        </div>
      )}
    </div>
  );
}

const styles = {
  tabs: {
    display: "flex",
    gap: "0",
    borderBottom: "1px solid #333",
  },
  tab: {
    padding: "12px 24px",
    backgroundColor: "transparent",
    border: "none",
    borderBottom: "2px solid transparent",
    color: "#888",
    fontSize: "1rem",
    cursor: "pointer",
    transition: "color 0.2s, border-color 0.2s",
  },
  tabActive: {
    color: "#fff",
    borderBottomColor: "#4a9eff",
  },
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
  },
  label: {
    display: "block",
    fontSize: "0.875rem",
    color: "#888",
    marginBottom: "5px",
    fontWeight: "bold" as const,
  },
  input: {
    width: "100%",
    padding: "10px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
  },
  textarea: {
    width: "100%",
    padding: "10px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "0.875rem",
    fontFamily: "monospace",
    resize: "vertical" as const,
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
    fontSize: "0.875rem",
  },
  td: {
    padding: "10px",
    borderBottom: "1px solid #333",
    fontSize: "0.875rem",
  },
  pre: {
    padding: "15px",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    overflow: "auto",
    fontSize: "0.875rem",
    color: "#fff",
  },
};
