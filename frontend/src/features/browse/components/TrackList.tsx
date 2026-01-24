/**
 * TrackList - Display tracks for a selected entity with tag exploration
 */

import { Search } from "@mui/icons-material";
import { Box, Chip, IconButton, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ErrorMessage, Panel } from "@shared/components/ui";

import { getFilesByIds } from "../../../shared/api/files";
import { listSongsForEntity } from "../../../shared/api/metadata";
import type { EntityCollection, LibraryFile } from "../../../shared/types";

import { TagExplorer } from "./TagExplorer";

interface TrackListProps {
  entityId: string;
  entityName: string;
  collection: EntityCollection;
  relationType: string;
}

export function TrackList({
  entityId,
  entityName,
  collection,
  relationType,
}: TrackListProps) {
  const [tracks, setTracks] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedTrackId, setExpandedTrackId] = useState<string | null>(null);
  const [filterQuery, setFilterQuery] = useState("");
  const [sortBy, setSortBy] = useState<"title" | "artist" | "album" | "duration">("title");

  const loadTracks = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Get song IDs for this entity
      const songResult = await listSongsForEntity(
        collection,
        entityId,
        relationType,
        { limit: 500 }
      );

      if (songResult.song_ids.length === 0) {
        setTracks([]);
        return;
      }

      // Fetch full file details for these song IDs
      const filesResult = await getFilesByIds(songResult.song_ids);

      // Preserve order from song_ids
      const trackMap = new Map(
        filesResult.files.map((f: LibraryFile) => [f.id, f])
      );

      const orderedTracks = songResult.song_ids
        .map((id: string) => trackMap.get(id))
        .filter((t: LibraryFile | undefined) => t !== undefined) as LibraryFile[];

      setTracks(orderedTracks);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tracks");
      console.error("[TrackList] Load error:", err);
    } finally {
      setLoading(false);
    }
  }, [entityId, collection, relationType]);

  useEffect(() => {
    loadTracks();
  }, [loadTracks]);

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

    return [...result].sort((a, b) => {
      switch (sortBy) {
        case "title":
          return (a.title || "").localeCompare(b.title || "");
        case "artist":
          return (a.artist || "").localeCompare(b.artist || "");
        case "album":
          return (a.album || "").localeCompare(b.album || "");
        case "duration":
          return (a.duration_seconds || 0) - (b.duration_seconds || 0);
        default:
          return 0;
      }
    });
  }, [tracks, filterQuery, sortBy]);

  const toggleTrackDetails = (trackId: string) => {
    setExpandedTrackId(expandedTrackId === trackId ? null : trackId);
  };

  const formatDuration = (seconds: number | null | undefined): string => {
    if (!seconds || seconds <= 0) return "-";
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, "0")}`;
  };

  return (
    <Box>
      <Panel sx={{ mb: 2 }}>
        <Typography variant="h6" gutterBottom>
          {entityName}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {loading
            ? "Loading tracks..."
            : `${tracks.length} track${tracks.length !== 1 ? "s" : ""}`}
          {filterQuery && ` (${filteredTracks.length} matching)`}
        </Typography>
        
        <Stack direction="row" spacing={1}>
          <TextField
            placeholder="Filter tracks by title, artist, or album..."
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
          <Select
            value={sortBy}
            onChange={(e) => setSortBy(e.target.value as "title" | "artist" | "album" | "duration")}
            size="small"
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="title">Sort by Title</MenuItem>
            <MenuItem value="artist">Sort by Artist</MenuItem>
            <MenuItem value="album">Sort by Album</MenuItem>
            <MenuItem value="duration">Sort by Duration</MenuItem>
          </Select>
        </Stack>
      </Panel>

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {!loading && filteredTracks.length === 0 && (
        <Panel>
          <Typography color="text.secondary" textAlign="center">
            {filterQuery
              ? `No tracks matching "${filterQuery}".`
              : `No tracks found for this ${collection.slice(0, -1)}.`}
          </Typography>
        </Panel>
      )}

      <Stack spacing={1}>
        {filteredTracks.map((track, index) => (
          <Box
            key={track.id}
            sx={{
              bgcolor: "background.paper",
              border: 1,
              borderColor: "divider",
              borderRadius: 1,
              overflow: "hidden",
            }}
          >
            <Box
              onClick={() => toggleTrackDetails(track.id)}
              sx={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                p: 1.5,
                cursor: "pointer",
                "&:hover": { bgcolor: "action.hover" },
              }}
            >
              <Box sx={{ flex: 1, display: "flex", alignItems: "center", gap: 2 }}>
                <Typography
                  variant="body2"
                  color="text.disabled"
                  sx={{ minWidth: 30, textAlign: "right" }}
                >
                  {index + 1}
                </Typography>

                <Box sx={{ flex: 1 }}>
                  <Typography variant="body1" sx={{ fontWeight: 500 }}>
                    {track.title || "Unknown Title"}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    {track.artist && <span>{track.artist}</span>}
                    {track.album && <span> • {track.album}</span>}
                  </Typography>
                </Box>

                <Typography variant="body2" color="text.disabled">
                  {formatDuration(track.duration_seconds)}
                </Typography>

                {track.tagged && (
                  <Chip
                    label={`${track.tags?.length || 0} tags`}
                    size="small"
                    color="primary"
                  />
                )}
              </Box>

              <Typography color="text.disabled" sx={{ ml: 1 }}>
                {expandedTrackId === track.id ? "▼" : "▶"}
              </Typography>
            </Box>

            {expandedTrackId === track.id && (
              <Box
                sx={{
                  p: 2,
                  borderTop: 1,
                  borderColor: "divider",
                  bgcolor: "background.default",
                }}
              >
                <TagExplorer track={track} />
              </Box>
            )}
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
