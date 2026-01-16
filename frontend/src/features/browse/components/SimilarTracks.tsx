/**
 * SimilarTracks - Find and display tracks with similar tag values
 * - Strings: exact match
 * - Numbers: closest 25 by value
 */

import { Search } from "@mui/icons-material";
import { Box, Chip, IconButton, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorMessage } from "@shared/components/ui";

import { api } from "../../../shared/api";
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
  const [tracks, setTracks] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filterQuery, setFilterQuery] = useState("");
  const [sortBy, setSortBy] = useState<"title" | "artist" | "album">("title");

  const loadSimilarTracks = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      if (isNumeric) {
        const result = await api.files.search({
          tagKey: tag.key,
          limit: 500,
        });

        const targetValue = parseFloat(tag.value);
        const tracksWithTag = result.files
          .filter((f) => f.id !== currentTrackId)
          .map((track) => {
            const trackTag = track.tags?.find((t) => t.key === tag.key);
            const trackValue = trackTag ? parseFloat(trackTag.value) : null;
            return {
              track,
              value: trackValue,
              diff: trackValue !== null ? Math.abs(trackValue - targetValue) : Infinity,
            };
          })
          .filter((item) => item.value !== null)
          .sort((a, b) => a.diff - b.diff)
          .slice(0, 25)
          .map((item) => item.track);

        setTracks(tracksWithTag);
      } else {
        const result = await api.files.search({
          tagKey: tag.key,
          tagValue: tag.value,
          limit: 100,
        });

        const filteredTracks = result.files.filter(
          (f) => f.id !== currentTrackId
        );

        setTracks(filteredTracks);
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

  const filteredTracks = useMemo(() => {
    let result = tracks;
    
    if (filterQuery.trim()) {
      const query = filterQuery.toLowerCase();
      result = result.filter(
        (track) =>
          track.title?.toLowerCase().includes(query) ||
          track.artist?.toLowerCase().includes(query) ||
          track.album?.toLowerCase().includes(query)
      );
    }

    if (!isNumeric) {
      return [...result].sort((a, b) => {
        switch (sortBy) {
          case "title":
            return (a.title || "").localeCompare(b.title || "");
          case "artist":
            return (a.artist || "").localeCompare(b.artist || "");
          case "album":
            return (a.album || "").localeCompare(b.album || "");
          default:
            return 0;
        }
      });
    }

    return result;
  }, [tracks, filterQuery, isNumeric, sortBy]);

  return (
    <Box>
      <Typography variant="subtitle2" gutterBottom>
        Similar tracks with {tag.key}
        {isNumeric ? ` (closest 25 to ${tag.value})` : ` = "${tag.value}"`}
      </Typography>

      {tracks.length > 0 && (
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
            {filteredTracks.length} of {tracks.length} shown
          </Typography>
        </Box>
      )}

      {loading && (
        <Typography variant="body2" color="text.secondary">
          Loading...
        </Typography>
      )}

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {!loading && tracks.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No similar tracks found.
        </Typography>
      )}

      {!loading && tracks.length > 0 && filteredTracks.length === 0 && (
        <Typography variant="body2" color="text.secondary">
          No tracks matching "{filterQuery}".
        </Typography>
      )}

      {!loading && tracks.length > 0 && filteredTracks.length > 0 && (
        <Stack spacing={1} sx={{ mt: 2 }}>
          {filteredTracks.map((track) => {
            const tagValue = getTagValue(track);
            return (
              <Box
                key={track.id}
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
    </Box>
  );
}
