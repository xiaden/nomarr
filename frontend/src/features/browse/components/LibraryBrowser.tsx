/**
 * LibraryBrowser - Hierarchical music library browser
 *
 * Navigation flow:
 * Artist → Albums → Tracks → Tags → Tag-search → Tracks (repeatable)
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
    Chip,
    List,
    ListItemButton,
    ListItemIcon,
    ListItemText,
    Paper,
    Stack,
    Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

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
  | { type: "tag-search"; tagKey: string; targetValue: number | string; breadcrumb: BreadcrumbItem[] };

interface LibraryBrowserProps {
  initialStep?: NavigationStep;
}

export function LibraryBrowser({ initialStep }: LibraryBrowserProps) {
  // Navigation state
  const [step, setStep] = useState<NavigationStep>(initialStep ?? { type: "artists" });
  const [tagBreadcrumbs, setTagBreadcrumbs] = useState<BreadcrumbItem[]>([]);

  // Data
  const [artists, setArtists] = useState<Entity[]>([]);
  const [albums, setAlbums] = useState<Album[]>([]);
  const [tracks, setTracks] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Load artists
  const loadArtists = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const result = await listEntities("artists", { limit: 500 });
      setArtists(result.entities.sort((a, b) => a.display_name.localeCompare(b.display_name)));
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
        loadArtists();
        setTagBreadcrumbs([]);
        break;
      case "albums":
        loadAlbums(step.artist.id);
        setTagBreadcrumbs([]);
        break;
      case "tracks":
        loadTracks(step.album.id);
        setTagBreadcrumbs([]);
        break;
      case "tags":
        // Tags are already available on the track
        break;
      case "tag-search":
        loadTracksByTag(step.tagKey, step.targetValue);
        break;
    }
  }, [step, loadArtists, loadAlbums, loadTracks, loadTracksByTag]);

  // Navigation handlers
  const handleArtistClick = (artist: Entity) => {
    setStep({ type: "albums", artist });
  };

  const handleAlbumClick = (album: Album) => {
    if (step.type === "albums") {
      setStep({ type: "tracks", artist: step.artist, album });
    }
  };

  const handleTrackClick = (track: LibraryFile) => {
    if (step.type === "tracks") {
      setStep({ type: "tags", artist: step.artist, album: step.album, track });
    } else if (step.type === "tag-search") {
      // Find or create artist/album context from track
      const artistName = track.artist ?? "Unknown Artist";
      const albumName = track.album ?? "Unknown Album";
      // For tag-search results, we show tags but keep the tag breadcrumbs
      setStep({
        type: "tags",
        artist: { id: "", key: "", display_name: artistName },
        album: { id: "", display_name: albumName },
        track,
      });
    }
  };

  const handleTagClick = (tag: FileTag) => {
    // Parse value
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

    // Build breadcrumb for this tag hop
    const newCrumb: BreadcrumbItem = {
      label: `${tag.key}: ${typeof value === "number" ? value.toFixed(2) : value}`,
      onClick: () => handleTagClick(tag),
    };

    // Keep only last 3 tag hops
    const newBreadcrumbs = [...tagBreadcrumbs, newCrumb].slice(-3);
    setTagBreadcrumbs(newBreadcrumbs);

    setStep({
      type: "tag-search",
      tagKey: tag.key,
      targetValue: value,
      breadcrumb: newBreadcrumbs,
    });
  };

  // Build breadcrumb items
  const buildBreadcrumbs = (): BreadcrumbItem[] => {
    const crumbs: BreadcrumbItem[] = [];

    // Always start with Artists
    crumbs.push({
      label: "Artists",
      onClick: () => setStep({ type: "artists" }),
    });

    if (step.type === "albums" || step.type === "tracks" || step.type === "tags") {
      crumbs.push({
        label: step.artist.display_name,
        onClick: () => setStep({ type: "albums", artist: step.artist }),
      });
    }

    if (step.type === "tracks" || step.type === "tags") {
      crumbs.push({
        label: step.album.display_name,
        onClick: () => setStep({ type: "tracks", artist: step.artist, album: step.album }),
      });
    }

    if (step.type === "tags") {
      crumbs.push({
        label: step.track.title ?? step.track.path.split("/").pop() ?? "Track",
        onClick: () => {}, // Current item, no action
      });
    }

    if (step.type === "tag-search") {
      // Add tag breadcrumbs
      crumbs.push(...tagBreadcrumbs);
    }

    return crumbs;
  };

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
      case "artists":
        return (
          <List dense>
            {artists.map((artist) => (
              <ListItemButton key={artist.id} onClick={() => handleArtistClick(artist)}>
                <ListItemIcon>
                  <Person />
                </ListItemIcon>
                <ListItemText
                  primary={artist.display_name}
                  secondary={artist.song_count ? `${artist.song_count} songs` : undefined}
                />
                <DrillIcon color="action" />
              </ListItemButton>
            ))}
          </List>
        );

      case "albums":
        return (
          <List dense>
            {albums.map((album) => (
              <ListItemButton key={album.id} onClick={() => handleAlbumClick(album)}>
                <ListItemIcon>
                  <AudioFile />
                </ListItemIcon>
                <ListItemText
                  primary={album.display_name}
                  secondary={album.song_count ? `${album.song_count} songs` : undefined}
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

      case "tracks":
      case "tag-search":
        return (
          <List dense>
            {tracks.map((track) => (
              <ListItemButton key={track.id} onClick={() => handleTrackClick(track)}>
                <ListItemIcon>
                  <MusicNote />
                </ListItemIcon>
                <ListItemText
                  primary={track.title ?? track.path.split("/").pop()}
                  secondary={
                    step.type === "tag-search" 
                      ? `${track.artist} - ${track.album}`
                      : track.artist
                  }
                />
                <DrillIcon color="action" />
              </ListItemButton>
            ))}
            {tracks.length === 0 && (
              <Box sx={{ p: 2, textAlign: "center" }}>
                <Typography color="text.secondary">No tracks found</Typography>
              </Box>
            )}
          </List>
        );

      case "tags": {
        const nomarrTags = step.track.tags.filter((t) => t.is_nomarr);
        const otherTags = step.track.tags.filter((t) => !t.is_nomarr);
        
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
      <BreadcrumbNav items={buildBreadcrumbs()} />
      
      <Paper sx={{ flex: 1, overflow: "auto", mt: 1 }}>
        {renderContent()}
      </Paper>
    </Box>
  );
}
