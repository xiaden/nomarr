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

import { Search } from "@mui/icons-material";
import {
    Box,
    Button,
    Checkbox,
    Chip,
    FormControlLabel,
    MenuItem,
    Select,
    Stack,
    TextField,
    Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { ErrorMessage, PageContainer, Panel } from "@shared/components/ui";

import { api } from "../../shared/api";
import { FileTagsDataGrid } from "../../shared/components/FileTagsDataGrid";
import type { LibraryFile } from "../../shared/types";

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
  const [expandedFileId, setExpandedFileId] = useState<string | null>(null);

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

  const toggleFileDetails = (fileId: string) => {
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
    <PageContainer title="Browse Tagged Files">
      {/* Search Controls */}
      <Panel>
        <Stack direction="row" spacing={1.5} sx={{ mb: 2, flexWrap: "wrap" }}>
          <TextField
            placeholder="Search artist, album, or title..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSearch()}
            size="small"
            sx={{ flex: 1, minWidth: 250 }}
          />

          <Select
            value={tagKey}
            onChange={(e) => setTagKey(e.target.value)}
            size="small"
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">All Tags</MenuItem>
            {availableTags.map((tag) => (
              <MenuItem key={tag} value={tag}>
                {tag}
              </MenuItem>
            ))}
          </Select>

          {tagKey && (
            <Select
              value={tagValue}
              onChange={(e) => setTagValue(e.target.value)}
              size="small"
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">All Values</MenuItem>
              {availableValues.map((value) => (
                <MenuItem key={value} value={value}>
                  {value}
                </MenuItem>
              ))}
            </Select>
          )}

          <FormControlLabel
            control={
              <Checkbox
                checked={taggedOnly}
                onChange={(e) => setTaggedOnly(e.target.checked)}
              />
            }
            label="Tagged Only"
          />

          <Button
            variant="contained"
            startIcon={<Search />}
            onClick={handleSearch}
          >
            Search
          </Button>
        </Stack>

        {/* Results Summary */}
        <Typography variant="body2" color="text.secondary">
          {loading ? (
            "Loading..."
          ) : (
            <>
              Found {total.toLocaleString()} files
              {total > 0 && (
                <>
                  {" "}
                  (Page {currentPage} of {totalPages})
                </>
              )}
            </>
          )}
        </Typography>
      </Panel>

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {/* Files List */}
      {!loading && files.length === 0 && (
        <Panel>
          <Typography color="text.secondary" textAlign="center">
            No files found. Try adjusting your search filters.
          </Typography>
        </Panel>
      )}

      {files.length > 0 && (
        <Stack spacing={1}>
          {files.map((file) => (
            <Box
              key={file.id}
              sx={{
                bgcolor: "background.paper",
                border: 1,
                borderColor: "divider",
                borderRadius: 1,
                overflow: "hidden",
              }}
            >
              <Box
                onClick={() => toggleFileDetails(file.id)}
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  p: 2,
                  cursor: "pointer",
                  "&:hover": { bgcolor: "action.hover" },
                }}
              >
                <Box sx={{ flex: 1 }}>
                  <Typography variant="h6" sx={{ mb: 0.5 }}>
                    {file.title || "Unknown Title"}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
                    {file.artist && <span>{file.artist}</span>}
                    {file.album && <span> • {file.album}</span>}
                    {file.tags && file.tags.find(t => t.key === "year") && (
                      <span> ({file.tags.find(t => t.key === "year")?.value})</span>
                    )}
                  </Typography>
                  <Typography variant="caption" color="text.disabled">
                    {formatDuration(file.duration_seconds)}
                    {file.tags && file.tags.find(t => t.key === "genre") && (
                      <span> • {file.tags.find(t => t.key === "genre")?.value}</span>
                    )}
                    {file.tagged && (
                      <Chip
                        label="Tagged"
                        size="small"
                        color="primary"
                        sx={{ ml: 1, height: 20, fontSize: "0.75rem" }}
                      />
                    )}
                  </Typography>
                </Box>
                <Typography color="text.disabled">
                  {expandedFileId === file.id ? "▼" : "▶"}
                </Typography>
              </Box>

              {expandedFileId === file.id && (
                <Box
                  sx={{
                    p: 2,
                    borderTop: 1,
                    borderColor: "divider",
                    bgcolor: "background.default",
                  }}
                >
                  <Box sx={{ mb: 2 }}>
                    <Typography variant="body2" fontWeight="bold" component="span">
                      Path:
                    </Typography>
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{
                        mt: 0.5,
                        fontFamily: "monospace",
                        wordBreak: "break-all",
                      }}
                    >
                      {file.path}
                    </Typography>
                  </Box>

                  {/* Tags DataGrid */}
                  <FileTagsDataGrid tags={file.tags || []} />
                </Box>
              )}
            </Box>
          ))}
        </Stack>
      )}

      {/* Pagination */}
      {total > limit && (
        <Box sx={{ mt: 3 }}>
          <Stack direction="row" spacing={2} alignItems="center" justifyContent="center">
            <Button
              variant="outlined"
              onClick={handlePrevPage}
              disabled={offset === 0}
            >
              Previous
            </Button>
            <Typography color="text.secondary">
              Page {currentPage} of {totalPages}
            </Typography>
            <Button
              variant="outlined"
              onClick={handleNextPage}
              disabled={offset + limit >= total}
            >
              Next
            </Button>
          </Stack>
        </Box>
      )}
    </PageContainer>
  );
}
