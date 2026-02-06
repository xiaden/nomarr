/**
 * SimilarTracks - Find and display tracks with similar tag values
 * - Strings: exact match
 * - Numbers: closest 25 by value
 */

import { Search } from "@mui/icons-material";
import { Box, Button, Chip, IconButton, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorMessage } from "@shared/components/ui";

import { search } from "../../../shared/api/files";
import type { FileTag, LibraryFile } from "../../../shared/types";

interface SimilarTracksProps {
  tag: FileTag;
  currentTrackId: string;
  isNumeric: boolean;
}

export function SimilarTracks({
  tag,
  currentTrackId,
  isNumeric,
}: SimilarTracksProps) {
  const [allTracks, setAllTracks] = useState<Array<{ track: LibraryFile; diff: number }>>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterQuery, setFilterQuery] = useState("");
  const [sortBy, setSortBy] = useState<"title" | "artist" | "album">("title");
  const [page, setPage] = useState(0);
  const pageSize = 25;

  const loadSimilarTracks = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      setPage(0);

      if (isNumeric) {
        const result = await search({
          tagKey: tag.key,
          limit: 500,
        });

        const targetValue = parseFloat(tag.value);
        const tracksWithTag = result.files
          .filter((f: LibraryFile) => f.file_id !== currentTrackId)
          .map((track: LibraryFile) => {
            const trackTag = track.tags?.find((t: FileTag) => t.key === tag.key);
            const trackValue = trackTag ? parseFloat(trackTag.value) : null;
            return {
              track,
              value: trackValue,
              diff: trackValue !== null ? Math.abs(trackValue - targetValue) : Infinity,
            };
          })
          .filter((item: { value: number | null }) => item.value !== null)
          // Stable sort: distance, then title, then artist, then id
          .sort((a: { track: LibraryFile; diff: number }, b: { track: LibraryFile; diff: number }) => {
            if (a.diff !== b.diff) return a.diff - b.diff;
            const titleCmp = (a.track.title || "").localeCompare(b.track.title || "");
            if (titleCmp !== 0) return titleCmp;
            const artistCmp = (a.track.artist || "").localeCompare(b.track.artist || "");
            if (artistCmp !== 0) return artistCmp;
            return a.track.file_id.localeCompare(b.track.file_id);
          });

        setAllTracks(tracksWithTag);
      } else {
        const result = await search({
          tagKey: tag.key,
          tagValue: tag.value,
          limit: 500,
        });

        const filteredTracks = result.files
          .filter((f: LibraryFile) => f.file_id !== currentTrackId)
          .map((track: LibraryFile) => ({ track, diff: 0 }));

        setAllTracks(filteredTracks);
      }
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load similar tracks"
      );
      console.error("[SimilarTracks] Load error:", err);
    } finally {
      setLoading(false);
    }
  }, [tag.key, tag.value, currentTrackId, isNumeric]);

  useEffect(() => {
    loadSimilarTracks();
  }, [loadSimilarTracks]);

  const formatDuration = (seconds: number | null | undefined): string => {
    if (!seconds || seconds <= 0) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  const getTagValue = (track: LibraryFile): string | null => {
    const trackTag = track.tags?.find((t) => t.key === tag.key);
    return trackTag?.value || null;
  };

  // Filter and sort, then paginate
  const { paginatedTracks, totalFiltered, totalPages } = useMemo(() => {
    let result = allTracks;
    
    // Apply text filter
    if (filterQuery.trim()) {
      const query = filterQuery.toLowerCase();
      result = result.filter(
        ({ track }) =>
          track.title?.toLowerCase().includes(query) ||
          track.artist?.toLowerCase().includes(query) ||
          track.album?.toLowerCase().includes(query)
      );
    }

    // For string tags, apply user-selected sort
    if (!isNumeric) {
      result = [...result].sort((a, b) => {
        switch (sortBy) {
          case "title":
            return (a.track.title || "").localeCompare(b.track.title || "");
          case "artist":
            return (a.track.artist || "").localeCompare(b.track.artist || "");
          case "album":
            return (a.track.album || "").localeCompare(b.track.album || "");
          default:
            return 0;
        }
      });
    }
    // For numeric tags, result is already sorted by distance (stable)

    const totalFiltered = result.length;
    const totalPages = Math.ceil(totalFiltered / pageSize);
    const start = page * pageSize;
    const paginatedTracks = result.slice(start, start + pageSize).map((item) => item.track);

    return { paginatedTracks, totalFiltered, totalPages };
  }, [allTracks, filterQuery, isNumeric, sortBy, page]);

  // Reset to page 0 when filter changes
  useEffect(() => {
    setPage(0);
  }, [filterQuery]);

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Similar tracks with {tag.key}
        {isNumeric ? ` (by distance to ${tag.value})` : ` = "${tag.value}"`}
      </Typography>

      {allTracks.length > 0 && (
        <Box sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1}>
            <TextField
              placeholder="Filter similar tracks..."
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              size="small"
              fullWidth
              InputProps={{
                endAdornment: (
                  <IconButton size="small" edge="end">
                    <Search fontSize="small" />
                  </IconButton>
                ),
              }}
            />
            {!isNumeric && (
              <Select
                value={sortBy}
                onChange={(e) => setSortBy(e.target.value as "title" | "artist" | "album")}
                size="small"
                sx={{ minWidth: 130 }}
              >
                <MenuItem value="title">Sort by Title</MenuItem>
                <MenuItem value="artist">Sort by Artist</MenuItem>
                <MenuItem value="album">Sort by Album</MenuItem>
              </Select>
            )}
          </Stack>
          <Typography variant="caption" color="text.secondary" sx={{ mt: 0.5, display: "block" }}>
            Showing {paginatedTracks.length} of {totalFiltered} matches
            {totalFiltered !== allTracks.length && ` (${allTracks.length} total)`}
          </Typography>
        </Box>
      )}

      {loading && (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      )}

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {!loading && allTracks.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No similar tracks found.
        </Typography>
      )}

      {!loading && allTracks.length > 0 && paginatedTracks.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No tracks matching "{filterQuery}".
        </Typography>
      )}

      {!loading && allTracks.length > 0 && paginatedTracks.length > 0 && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          {paginatedTracks.map((track) => {
            const tagValue = getTagValue(track);
            return (
              <Box
                key={track.file_id}
                sx={{
                  p: 1.5,
                  bgcolor: "background.default",
                  border: 1,
                  borderColor: "divider",
                  borderRadius: 1,
                }}
              >
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  spacing={2}
                >
                  <Box sx={{ flex: 1, minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{ fontWeight: 500 }}
                      noWrap
                    >
                      {track.title || "Unknown Title"}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap>
                      {track.artist && <span>{track.artist}</span>}
                      {track.album && <span> • {track.album}</span>}
                      {track.tags?.find((t) => t.key === "genre") && (
                        <span>
                          {" "}
                          •{" "}
                          {track.tags.find((t) => t.key === "genre")?.value}
                        </span>
                      )}
                    </Typography>
                  </Box>

                  <Stack direction="row" spacing={1} alignItems="center">
                    {isNumeric && tagValue && (
                      <Chip
                        label={tagValue}
                        size="small"
                        sx={{ fontSize: "0.7rem" }}
                      />
                    )}
                    <Typography
                      variant="caption"
                      color="text.disabled"
                      sx={{ minWidth: 40, textAlign: "right" }}
                    >
                      {formatDuration(track.duration_seconds)}
                    </Typography>
                  </Stack>
                </Stack>
              </Box>
            );
          })}
        </Stack>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <Stack
          direction="row"
          justifyContent="center"
          alignItems="center"
          spacing={2}
          sx={{ mt: 2 }}
        >
          <Button
            size="small"
            variant="outlined"
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
          >
            Previous
          </Button>
          <Typography variant="body2" color="text.secondary">
            Page {page + 1} of {totalPages}
          </Typography>
          <Button
            size="small"
            variant="outlined"
            onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
            disabled={page >= totalPages - 1}
          >
            Next
          </Button>
        </Stack>
      )}
    </Box>
  );
}
