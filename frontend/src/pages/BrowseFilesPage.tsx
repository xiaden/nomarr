/**
 * BrowseFilesPage - Search and browse tagged library files
 *
 * Features:
 * - Text search across artist/album/title
 * - Filter by tag keys/values
 * - Filter by tagged status
 * - Paginated results
 * - View tags for each file
 */

import { useCallback, useEffect, useState } from "react";

import { api } from "../shared/api";

interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

interface LibraryFile {
  id: number;
  path: string;
  artist?: string;
  album?: string;
  title?: string;
  duration_seconds: number;
  tagged: number;
  tags: FileTag[];
}

export function BrowseFilesPage() {
  const [files, setFiles] = useState<LibraryFile[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Search filters
  const [searchQuery, setSearchQuery] = useState("");
  const [tagKey, setTagKey] = useState("");
  const [tagValue, setTagValue] = useState("");
  const [taggedOnly, setTaggedOnly] = useState(false);
  const [availableTags, setAvailableTags] = useState<string[]>([]);
  const [availableValues, setAvailableValues] = useState<string[]>([]);

  // Pagination
  const [limit] = useState(50);
  const [offset, setOffset] = useState(0);

  // Expanded file details
  const [expandedFileId, setExpandedFileId] = useState<number | null>(null);

  const loadAvailableTags = async () => {
    try {
      const result = await api.files.getUniqueTagKeys(true); // Nomarr tags only
      setAvailableTags(result.tag_keys);
    } catch (err) {
      console.error("[BrowseFiles] Failed to load tags:", err);
    }
  };

  const loadAvailableValues = async (key: string) => {
    if (!key) {
      setAvailableValues([]);
      return;
    }
    try {
      const result = await api.files.getTagValues(key, true); // Nomarr tags only
      setAvailableValues(result.tag_keys); // Backend reuses same DTO structure
    } catch (err) {
      console.error("[BrowseFiles] Failed to load tag values:", err);
      setAvailableValues([]);
    }
  };

  const loadFiles = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const result = await api.files.search({
        q: searchQuery || undefined,
        tagKey: tagKey || undefined,
        tagValue: tagValue || undefined,
        taggedOnly,
        limit,
        offset,
      });

      setFiles(result.files);
      setTotal(result.total);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load files"
      );
      console.error("[BrowseFiles] Load error:", err);
    } finally {
      setLoading(false);
    }
  }, [searchQuery, tagKey, tagValue, taggedOnly, limit, offset]);

  useEffect(() => {
    loadAvailableTags();
  }, []);

  useEffect(() => {
    loadFiles();
  }, [loadFiles]);

  // Load values when tag key changes
  useEffect(() => {
    if (tagKey) {
      loadAvailableValues(tagKey);
      setTagValue(""); // Reset value when key changes
    } else {
      setAvailableValues([]);
      setTagValue("");
    }
  }, [tagKey]);

  const handleSearch = () => {
    setOffset(0);
    loadFiles();
  };

  const handlePrevPage = () => {
    setOffset(Math.max(0, offset - limit));
  };

  const handleNextPage = () => {
    if (offset + limit < total) {
      setOffset(offset + limit);
    }
  };

  const toggleFileDetails = (fileId: number) => {
    setExpandedFileId(expandedFileId === fileId ? null : fileId);
  };

  const formatDuration = (seconds: number | null | undefined): string => {
    if (!seconds || seconds <= 0) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.ceil(total / limit);

  return (
    <div style={styles.container}>
      <h1>Browse Tagged Files</h1>

      {/* Search Controls */}
      <div style={styles.searchSection}>
        <div style={styles.searchRow}>
          <input
            type="text"
            placeholder="Search artist, album, or title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            style={styles.searchInput}
          />

          <select
            value={tagKey}
            onChange={(e) => setTagKey(e.target.value)}
            style={styles.select}
          >
            <option value="">All Tags</option>
            {availableTags.map((tag) => (
              <option key={tag} value={tag}>
                {tag}
              </option>
            ))}
          </select>

          {tagKey && (
            <select
              value={tagValue}
              onChange={(e) => setTagValue(e.target.value)}
              style={styles.select}
            >
              <option value="">All Values</option>
              {availableValues.map((value) => (
                <option key={value} value={value}>
                  {value}
                </option>
              ))}
            </select>
          )}

          <label style={styles.checkboxLabel}>
            <input
              type="checkbox"
              checked={taggedOnly}
              onChange={(e) => setTaggedOnly(e.target.checked)}
              style={styles.checkbox}
            />
            Tagged Only
          </label>

          <button onClick={handleSearch} style={styles.btnPrimary}>
            Search
          </button>
        </div>

        {/* Results Summary */}
        <div style={styles.resultsSummary}>
          {loading ? (
            <span>Loading...</span>
          ) : (
            <span>
              Found {total.toLocaleString()} files
              {total > 0 && (
                <>
                  {" "}
                  (Page {currentPage} of {totalPages})
                </>
              )}
            </span>
          )}
        </div>
      </div>

      {error && <div style={styles.error}>{error}</div>}

      {/* Files List */}
      {!loading && files.length === 0 && (
        <div style={styles.noResults}>
          No files found. Try adjusting your search filters.
        </div>
      )}

      {files.length > 0 && (
        <div style={styles.filesList}>
          {files.map((file) => (
            <div key={file.id} style={styles.fileCard}>
              <div
                style={styles.fileHeader}
                onClick={() => toggleFileDetails(file.id)}
              >
                <div style={styles.fileInfo}>
                  <div style={styles.fileTitle}>
                    {file.title || "Unknown Title"}
                  </div>
                  <div style={styles.fileArtist}>
                    {file.artist && <span>{file.artist}</span>}
                    {file.album && <span> • {file.album}</span>}
                    {file.tags.find(t => t.key === "year") && (
                      <span> ({file.tags.find(t => t.key === "year")?.value})</span>
                    )}
                  </div>
                  <div style={styles.fileMeta}>
                    {formatDuration(file.duration_seconds)}
                    {file.tags.find(t => t.key === "genre") && (
                      <span> • {file.tags.find(t => t.key === "genre")?.value}</span>
                    )}
                    {file.tagged === 1 && (
                      <span style={styles.taggedBadge}>Tagged</span>
                    )}
                  </div>
                </div>
                <div style={styles.expandIcon}>
                  {expandedFileId === file.id ? "▼" : "▶"}
                </div>
              </div>

              {expandedFileId === file.id && (
                <div style={styles.fileDetails}>
                  <div style={styles.detailRow}>
                    <strong>Path:</strong>
                    <div style={styles.pathText}>{file.path}</div>
                  </div>

                  {file.tags.length > 0 && (
                    <div style={styles.tagsSection}>
                      <strong>Tags ({file.tags.length}):</strong>
                      <div style={styles.tagsGrid}>
                        {file.tags.map((tag, idx) => (
                          <div
                            key={idx}
                            style={{
                              ...styles.tag,
                              ...(tag.is_nomarr ? styles.tagNomarr : {}),
                            }}
                          >
                            <div style={styles.tagKey}>{tag.key}</div>
                            {tag.value && (
                              <div style={styles.tagValue}>{tag.value}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {file.tags.length === 0 && (
                    <div style={styles.noTags}>No tags found</div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Pagination */}
      {total > limit && (
        <div style={styles.pagination}>
          <button
            onClick={handlePrevPage}
            disabled={offset === 0}
            style={styles.btnSecondary}
          >
            Previous
          </button>
          <span style={styles.pageInfo}>
            Page {currentPage} of {totalPages}
          </span>
          <button
            onClick={handleNextPage}
            disabled={offset + limit >= total}
            style={styles.btnSecondary}
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}

const styles = {
  container: {
    padding: "2rem",
  },
  searchSection: {
    marginBottom: "2rem",
    padding: "1.5rem",
    backgroundColor: "#1a1a1a",
    borderRadius: "8px",
    border: "1px solid #333",
  },
  searchRow: {
    display: "flex" as const,
    gap: "1rem",
    alignItems: "center" as const,
    marginBottom: "1rem",
  },
  searchInput: {
    flex: 1,
    padding: "0.5rem",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    fontSize: "1rem",
  },
  select: {
    padding: "0.5rem",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    color: "#fff",
    minWidth: "200px",
  },
  checkboxLabel: {
    display: "flex" as const,
    alignItems: "center" as const,
    gap: "0.5rem",
    color: "#fff",
  },
  checkbox: {
    width: "18px",
    height: "18px",
  },
  btnPrimary: {
    padding: "0.5rem 1.5rem",
    backgroundColor: "#4a9eff",
    color: "#fff",
    border: "none",
    borderRadius: "4px",
    cursor: "pointer" as const,
    fontWeight: "bold" as const,
  },
  btnSecondary: {
    padding: "0.5rem 1rem",
    backgroundColor: "#333",
    color: "#fff",
    border: "1px solid #555",
    borderRadius: "4px",
    cursor: "pointer" as const,
  },
  resultsSummary: {
    color: "#888",
    fontSize: "0.875rem",
  },
  error: {
    padding: "1rem",
    backgroundColor: "#2a1a1a",
    border: "1px solid #f87171",
    borderRadius: "4px",
    color: "#f87171",
    marginBottom: "1rem",
  },
  noResults: {
    padding: "2rem",
    textAlign: "center" as const,
    color: "#888",
  },
  filesList: {
    display: "flex" as const,
    flexDirection: "column" as const,
    gap: "0.75rem",
  },
  fileCard: {
    backgroundColor: "#1a1a1a",
    border: "1px solid #333",
    borderRadius: "6px",
    overflow: "hidden" as const,
  },
  fileHeader: {
    display: "flex" as const,
    justifyContent: "space-between" as const,
    alignItems: "center" as const,
    padding: "1rem",
    cursor: "pointer" as const,
  },
  fileInfo: {
    flex: 1,
  },
  fileTitle: {
    fontSize: "1.125rem",
    fontWeight: "bold" as const,
    color: "#fff",
    marginBottom: "0.25rem",
  },
  fileArtist: {
    color: "#888",
    marginBottom: "0.25rem",
  },
  fileMeta: {
    fontSize: "0.875rem",
    color: "#666",
  },
  taggedBadge: {
    marginLeft: "0.5rem",
    padding: "0.125rem 0.5rem",
    backgroundColor: "#4a9eff",
    color: "#fff",
    borderRadius: "3px",
    fontSize: "0.75rem",
    fontWeight: "bold" as const,
  },
  expandIcon: {
    color: "#666",
    fontSize: "1rem",
  },
  fileDetails: {
    padding: "1rem",
    borderTop: "1px solid #333",
    backgroundColor: "#0f0f0f",
  },
  detailRow: {
    marginBottom: "1rem",
    color: "#ccc",
  },
  pathText: {
    marginTop: "0.25rem",
    color: "#888",
    fontSize: "0.875rem",
    fontFamily: "monospace",
    wordBreak: "break-all" as const,
  },
  tagsSection: {
    marginTop: "1rem",
    color: "#ccc",
  },
  tagsGrid: {
    display: "grid" as const,
    gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))",
    gap: "0.5rem",
    marginTop: "0.5rem",
  },
  tag: {
    padding: "0.5rem",
    backgroundColor: "#222",
    border: "1px solid #444",
    borderRadius: "4px",
    fontSize: "0.875rem",
  },
  tagNomarr: {
    borderColor: "#4a9eff",
  },
  tagKey: {
    fontWeight: "bold" as const,
    color: "#4a9eff",
    marginBottom: "0.25rem",
  },
  tagValue: {
    color: "#ccc",
  },
  noTags: {
    padding: "1rem",
    textAlign: "center" as const,
    color: "#666",
  },
  pagination: {
    display: "flex" as const,
    justifyContent: "center" as const,
    alignItems: "center" as const,
    gap: "1rem",
    marginTop: "2rem",
  },
  pageInfo: {
    color: "#888",
  },
};
