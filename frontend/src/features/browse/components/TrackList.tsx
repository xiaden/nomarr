/**
 * TrackList - Display tracks for a selected entity with tag exploration
 */

import { Box, Chip, Stack, Typography } from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { ErrorMessage, Panel } from "@shared/components/ui";

import { api } from "../../../shared/api";
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

  const loadTracks = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      const songResult = await api.metadata.listSongsForEntity(
        collection,
        entityId,
        relationType,
        { limit: 500 }
      );

      if (songResult.song_ids.length === 0) {
        setTracks([]);
        return;
      }

      const searchResult = await api.files.search({
        limit: 500,
      });

      const trackMap = new Map(
        searchResult.files.map((f) => [f.id, f])
      );

      const orderedTracks = songResult.song_ids
        .map((id) => trackMap.get(id))
        .filter((t) => t !== undefined) as LibraryFile[];

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
        <Typography variant="body2" color="text.secondary">
          {loading
            ? "Loading tracks..."
            : `${tracks.length} track${tracks.length !== 1 ? "s" : ""}`}
        </Typography>
      </Panel>

      {error && <ErrorMessage>{error}</ErrorMessage>}

      {!loading && tracks.length === 0 && (
        <Panel>
          <Typography color="text.secondary" textAlign="center">
            No tracks found for this {collection.slice(0, -1)}.
          </Typography>
        </Panel>
      )}

      <Stack spacing={1}>
        {tracks.map((track, index) => (
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
