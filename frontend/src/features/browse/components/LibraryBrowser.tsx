/**
 * LibraryBrowser - Hierarchical music library browser
 *
 * Navigation flow:
 * Artist → Albums → Tracks → Tags → Tag-search → Tracks (repeatable)
 *
 * Breadcrumb behavior:
 * - Always shows "Artists" as root
 * - Shows "..." if history > 5 items, then last 4 items
 * - Clicking a breadcrumb truncates history to that point
 * - Full history is preserved, just visually truncated
 *
 * - Float tags: Sort by distance from clicked value
 * - String tags: Filter by exact match
 */

import {
    AudioFile,
    ArrowForward as DrillIcon,
    MusicNote,
    Person,
    Label as TagIcon,
} from "@mui/icons-material";
import {
    Box,
    Button,
    Chip,
    List,
    ListItemButton,
    ListItemIcon,
    ListItemText,
    Paper,
    Stack,
    Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { getFilesByIds, searchByTag, type FileTag, type LibraryFile } from "../../../shared/api/files";
import { listAlbumsForArtist, listEntities, listSongsForEntity, type Album } from "../../../shared/api/metadata";
import type { Entity } from "../../../shared/types";

import { BreadcrumbNav, type BreadcrumbItem } from "./BreadcrumbNav";

// Navigation step types
type NavigationStep =
  | { type: "artists" }
  | { type: "albums"; artist: Entity }
  | { type: "tracks"; artist: Entity; album: Album }
  | { type: "tags"; artist: Entity; album: Album; track: LibraryFile }
  | { type: "tag-search"; tagKey: string; targetValue: number | string; label: string };

/** Get display label for a navigation step */
function getStepLabel(step: NavigationStep): string {
  switch (step.type) {
    case "artists":
      return "Artists";
    case "albums":
      return step.artist.display_name;
    case "tracks":
      return step.album.display_name;
    case "tags":
      return step.track.title ?? step.track.path.split("/").pop() ?? "Track";
    case "tag-search":
      return step.label;
  }
}

interface LibraryBrowserProps {
  initialStep?: NavigationStep;
}

export function LibraryBrowser({ initialStep }: LibraryBrowserProps) {
  // Navigation history stack - step is always history[history.length - 1]
  const [history, setHistory] = useState<NavigationStep[]>(
    initialStep ? [{ type: "artists" }, initialStep] : [{ type: "artists" }]
  );

  // Current step is derived from history
  const step = history[history.length - 1];

  // Data
  const [artists, setArtists] = useState<Entity[]>([]);
  const [albums, setAlbums] = useState<Album[]>([]);
  const [tracks, setTracks] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Pagination for artists
  const [artistsTotal, setArtistsTotal] = useState(0);
  const [artistsOffset, setArtistsOffset] = useState(0);
  const artistsLimit = 50;

  // Load artists with pagination
  const loadArtists = useCallback(async (offset: number = 0) => {
    try {
      setLoading(true);
      setError(null);
      const result = await listEntities("artists", { limit: artistsLimit, offset });
      setArtists(result.entities.sort((a, b) => a.display_name.localeCompare(b.display_name)));
      setArtistsTotal(result.total);
      setArtistsOffset(offset);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load artists");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load albums for artist
  const loadAlbums = useCallback(async (artistId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await listAlbumsForArtist(artistId);
      setAlbums(result.sort((a, b) => a.display_name.localeCompare(b.display_name)));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load albums");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load tracks for album
  const loadTracks = useCallback(async (albumId: string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await listSongsForEntity("albums", albumId, "album", { limit: 500 });
      // Get file details for songs (song_ids are actually library_files _ids)
      if (result.song_ids.length > 0) {
        const filesResult = await getFilesByIds(result.song_ids);
        setTracks(filesResult.files);
      } else {
        setTracks([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tracks");
    } finally {
      setLoading(false);
    }
  }, []);

  // Search by tag
  const loadTracksByTag = useCallback(async (tagKey: string, targetValue: number | string) => {
    try {
      setLoading(true);
      setError(null);
      const result = await searchByTag({ tag_key: tagKey, target_value: targetValue, limit: 100 });
      setTracks(result.files);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to search by tag");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load data based on current step
  useEffect(() => {
    switch (step.type) {
      case "artists":
        loadArtists(0);
        break;
      case "albums":
        loadAlbums(step.artist.entity_id);
        break;
      case "tracks":
        loadTracks(step.album.entity_id);
        break;
      case "tags":
        // Tags are already available on the track
        break;
      case "tag-search":
        loadTracksByTag(step.tagKey, step.targetValue);
        break;
    }
  }, [step, loadArtists, loadAlbums, loadTracks, loadTracksByTag]);

  // Navigation: push new step onto history
  const navigateTo = useCallback((newStep: NavigationStep) => {
    setHistory(prev => [...prev, newStep]);
  }, []);

  // Navigation: truncate history to index (clicking a breadcrumb)
  const navigateToIndex = useCallback((index: number) => {
    setHistory(prev => prev.slice(0, index + 1));
  }, []);

  // Navigation handlers
  const handleArtistClick = (artist: Entity) => {
    navigateTo({ type: "albums", artist });
  };

  const handleAlbumClick = (album: Album) => {
    if (step.type === "albums") {
      navigateTo({ type: "tracks", artist: step.artist, album });
    }
  };

  const handleTrackClick = (track: LibraryFile) => {
    if (step.type === "tracks") {
      navigateTo({ type: "tags", artist: step.artist, album: step.album, track });
    } else if (step.type === "tag-search") {
      // From tag-search results, create artist/album context from track metadata
      const artistName = track.artist ?? "Unknown Artist";
      const albumName = track.album ?? "Unknown Album";
      navigateTo({
        type: "tags",
        artist: { entity_id: "", key: "", display_name: artistName },
        album: { entity_id: "", display_name: albumName },
        track,
      });
    }
  };

  const handleTagClick = (tag: FileTag) => {
    // Parse value for display and search
    let value: number | string = tag.value;
    try {
      const parsed = JSON.parse(tag.value);
      if (Array.isArray(parsed) && parsed.length === 1) {
        value = parsed[0];
      } else if (typeof parsed === "number" || typeof parsed === "string") {
        value = parsed;
      }
    } catch {
      // Keep as string
    }

    // Create label for breadcrumb
    const label = `${tag.key}: ${typeof value === "number" ? value.toFixed(2) : value}`;

    navigateTo({
      type: "tag-search",
      tagKey: tag.key,
      targetValue: value,
      label,
    });
  };

  // Build breadcrumb items with smart truncation
  // Shows: Artists > [... if needed] > last N items
  const breadcrumbs = useMemo((): BreadcrumbItem[] => {
    const maxVisible = 5; // Total max visible breadcrumbs
    const crumbs: BreadcrumbItem[] = [];

    // Always show "Artists" (index 0)
    crumbs.push({
      label: "Artists",
      onClick: () => navigateToIndex(0),
    });

    if (history.length <= maxVisible) {
      // Show all items
      for (let i = 1; i < history.length; i++) {
        const historyStep = history[i];
        const index = i;
        crumbs.push({
          label: getStepLabel(historyStep),
          onClick: index === history.length - 1 ? () => {} : () => navigateToIndex(index),
        });
      }
    } else {
      // Show: Artists > ... > last (maxVisible - 2) items
      // Ellipsis takes one slot, Artists takes one slot
      crumbs.push({
        label: "...",
        onClick: () => {}, // Could expand to show full history in a menu
      });

      const startIndex = history.length - (maxVisible - 2);
      for (let i = startIndex; i < history.length; i++) {
        const historyStep = history[i];
        const index = i;
        crumbs.push({
          label: getStepLabel(historyStep),
          onClick: index === history.length - 1 ? () => {} : () => navigateToIndex(index),
        });
      }
    }

    return crumbs;
  }, [history, navigateToIndex]);

  // Render the current view
  const renderContent = () => {
    if (loading) {
      return (
        <Box sx={{ p: 3, textAlign: "center" }}>
          <Typography color="text.secondary">Loading...</Typography>
        </Box>
      );
    }

    if (error) {
      return (
        <Box sx={{ p: 3, textAlign: "center" }}>
          <Typography color="error">{error}</Typography>
        </Box>
      );
    }

    switch (step.type) {
      case "artists": {
        const currentPage = Math.floor(artistsOffset / artistsLimit) + 1;
        const totalPages = Math.ceil(artistsTotal / artistsLimit);
        const hasPrev = artistsOffset > 0;
        const hasNext = artistsOffset + artistsLimit < artistsTotal;

        return (
          <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
            <List dense sx={{ flex: 1, overflow: "auto" }}>
              {artists.map(artist => (
                <ListItemButton key={artist.entity_id} onClick={() => handleArtistClick(artist)}>
                  <ListItemIcon><Person /></ListItemIcon>
                  <ListItemText
                    primary={artist.display_name}
                    secondary={artist.song_count !== undefined ? `${artist.song_count} songs` : undefined}
                  />
                  <DrillIcon color="action" />
                </ListItemButton>
              ))}
            </List>

            {totalPages > 1 && (
              <Box sx={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 2, p: 1, borderTop: 1, borderColor: "divider" }}>
                <Button size="small" disabled={!hasPrev} onClick={() => loadArtists(artistsOffset - artistsLimit)}>
                  Previous
                </Button>
                <Typography variant="body2" color="text.secondary">
                  Page {currentPage} of {totalPages}
                </Typography>
                <Button size="small" disabled={!hasNext} onClick={() => loadArtists(artistsOffset + artistsLimit)}>
                  Next
                </Button>
              </Box>
            )}
          </Box>
        );
      }

      case "albums": {
        return (
          <List dense>
            {albums.map(album => (
              <ListItemButton key={album.entity_id} onClick={() => handleAlbumClick(album)}>
                <ListItemIcon><AudioFile /></ListItemIcon>
                <ListItemText
                  primary={album.display_name}
                  secondary={album.song_count !== undefined ? `${album.song_count} tracks` : undefined}
                />
                <DrillIcon color="action" />
              </ListItemButton>
            ))}
            {albums.length === 0 && (
              <Box sx={{ p: 2, textAlign: "center" }}>
                <Typography color="text.secondary">No albums found</Typography>
              </Box>
            )}
          </List>
        );
      }

      case "tracks":
      case "tag-search": {
        return (
          <List dense>
            {tracks.map(track => (
              <ListItemButton key={track.file_id} onClick={() => handleTrackClick(track)}>
                <ListItemIcon><MusicNote /></ListItemIcon>
                <ListItemText
                  primary={track.title ?? track.path.split("/").pop()}
                  secondary={`${track.artist ?? "Unknown"} - ${track.album ?? "Unknown"}`}
                />
                <DrillIcon color="action" />
              </ListItemButton>
            ))}
            {tracks.length === 0 && (
              <Box sx={{ p: 2, textAlign: "center" }}>
                <Typography color="text.secondary">
                  {step.type === "tag-search" ? "No matching tracks found" : "No tracks found"}
                </Typography>
              </Box>
            )}
          </List>
        );
      }

      case "tags": {
        const nomarrTags = step.track.tags?.filter(t => t.is_nomarr) ?? [];
        const otherTags = step.track.tags?.filter(t => !t.is_nomarr) ?? [];

        return (
          <Box sx={{ p: 2 }}>
            <Typography variant="h6" gutterBottom>
              {step.track.title ?? step.track.path.split("/").pop()}
            </Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              {step.track.artist} - {step.track.album}
            </Typography>

            {nomarrTags.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Nomarr Tags (click to find similar)
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1}>
                  {nomarrTags.map((tag, idx) => {
                    // Parse and format value
                    let displayValue = tag.value;
                    try {
                      const parsed = JSON.parse(tag.value);
                      if (Array.isArray(parsed) && parsed.length === 1) {
                        displayValue = typeof parsed[0] === "number" 
                          ? parsed[0].toFixed(2) 
                          : String(parsed[0]);
                      } else if (typeof parsed === "number") {
                        displayValue = parsed.toFixed(2);
                      } else {
                        displayValue = String(parsed);
                      }
                    } catch {
                      // Keep as-is
                    }

                    return (
                      <Chip
                        key={idx}
                        icon={<TagIcon />}
                        label={`${tag.key}: ${displayValue}`}
                        onClick={() => handleTagClick(tag)}
                        variant="outlined"
                        color="primary"
                        size="small"
                        sx={{ cursor: "pointer" }}
                      />
                    );
                  })}
                </Stack>
              </Box>
            )}

            {otherTags.length > 0 && (
              <Box sx={{ mt: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Metadata Tags
                </Typography>
                <Stack direction="row" flexWrap="wrap" gap={1}>
                  {otherTags.slice(0, 20).map((tag, idx) => {
                    let displayValue = tag.value;
                    try {
                      const parsed = JSON.parse(tag.value);
                      if (Array.isArray(parsed) && parsed.length === 1) {
                        displayValue = String(parsed[0]);
                      }
                    } catch {
                      // Keep as-is
                    }

                    return (
                      <Chip
                        key={idx}
                        label={`${tag.key}: ${displayValue}`}
                        onClick={() => handleTagClick(tag)}
                        variant="outlined"
                        size="small"
                        sx={{ cursor: "pointer" }}
                      />
                    );
                  })}
                </Stack>
              </Box>
            )}
          </Box>
        );
      }
    }
  };

  return (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <BreadcrumbNav items={breadcrumbs} />
      
      <Paper sx={{ flex: 1, overflow: "auto", mt: 1 }}>
        {renderContent()}
      </Paper>
    </Box>
  );
}
