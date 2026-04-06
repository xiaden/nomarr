/**
 * SearchResults - Renders library search results grouped by artist, album, and track.
 *
 * Groups are collapsible. Clicking an artist or album navigates into the
 * LibraryBrowser at that level. Clicking a track shows its detail.
 */

import {
  Album as AlbumIcon,
  ExpandLess,
  ExpandMore,
  MusicNote,
  Person,
} from "@mui/icons-material";
import {
  Box,
  Chip,
  Collapse,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useState } from "react";

import type { LibraryFile } from "@shared/api/files";
import { listEntities } from "@shared/api/metadata";
import { Panel } from "@shared/components/ui";
import type { Entity } from "@shared/types";

import type { GroupedSearchResults } from "../hooks/useLibrarySearch";

import type { NavigationStep } from "./LibraryBrowser";

interface SearchResultsProps {
  results: GroupedSearchResults;
  /** Called when user wants to drill into an artist/album/track in the LibraryBrowser. */
  onNavigate: (step: NavigationStep) => void;
}

/**
 * Collapsible group header that shows a title and item count.
 */
function GroupHeader({
  title,
  count,
  icon,
  open,
  onToggle,
}: {
  title: string;
  count: number;
  icon: React.ReactNode;
  open: boolean;
  onToggle: () => void;
}) {
  return (
    <ListItemButton onClick={onToggle} sx={{ py: 1 }}>
      <ListItemIcon>{icon}</ListItemIcon>
      <ListItemText
        primary={
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="subtitle1" fontWeight={600}>
              {title}
            </Typography>
            <Chip label={count} size="small" variant="outlined" />
          </Stack>
        }
      />
      {open ? <ExpandLess /> : <ExpandMore />}
    </ListItemButton>
  );
}

export function SearchResults({ results, onNavigate }: SearchResultsProps) {
  const [openSections, setOpenSections] = useState<Record<string, boolean>>({
    artists: true,
    albums: true,
    tracks: true,
  });

  const toggleSection = useCallback((section: string) => {
    setOpenSections((prev) => ({ ...prev, [section]: !prev[section] }));
  }, []);

  const handleArtistClick = useCallback(
    async (artistName: string) => {
      let artist: Entity = { entity_id: "", key: "", display_name: artistName };
      try {
        const result = await listEntities("artist", { search: artistName, limit: 5 });
        const match = result.entities.find(
          (e) => e.display_name.toLowerCase() === artistName.toLowerCase()
        ) ?? result.entities[0];
        if (match) artist = match;
      } catch {
        // Fall through with empty entity_id — LibraryBrowser will show an error
      }
      onNavigate({ type: "albums", artist });
    },
    [onNavigate],
  );

  const handleAlbumClick = useCallback(
    async (albumName: string, artistName: string) => {
      let artist: Entity = { entity_id: "", key: "", display_name: artistName };
      let album = { entity_id: "", display_name: albumName };
      try {
        const [artistResult, albumResult] = await Promise.all([
          listEntities("artist", { search: artistName, limit: 5 }),
          listEntities("album", { search: albumName, limit: 5 }),
        ]);
        const artistMatch =
          artistResult.entities.find(
            (e) => e.display_name.toLowerCase() === artistName.toLowerCase()
          ) ?? artistResult.entities[0];
        if (artistMatch) artist = artistMatch;
        const albumMatch =
          albumResult.entities.find(
            (e) => e.display_name.toLowerCase() === albumName.toLowerCase()
          ) ?? albumResult.entities[0];
        if (albumMatch) album = { entity_id: albumMatch.entity_id, display_name: albumMatch.display_name };
      } catch {
        // Fall through
      }
      onNavigate({ type: "tracks", artist, album });
    },
    [onNavigate],
  );

  const handleTrackClick = useCallback(
    (track: LibraryFile) => {
      const artistName = track.artist ?? "Unknown Artist";
      const albumName = track.album ?? "Unknown Album";
      onNavigate({
        type: "tags",
        artist: { entity_id: "", key: "", display_name: artistName },
        album: { entity_id: "", display_name: albumName },
        track,
      });
    },
    [onNavigate],
  );

  const { artists, albums, tracks } = results;

  // Sort groups by number of tracks (descending) for relevance
  const sortedArtists = [...artists.entries()].sort(
    (a, b) => b[1].length - a[1].length,
  );
  const sortedAlbums = [...albums.entries()].sort(
    (a, b) => b[1].length - a[1].length,
  );

  const hasResults =
    artists.size > 0 || albums.size > 0 || tracks.length > 0;

  if (!hasResults) {
    return (
      <Panel>
        <Typography color="text.secondary" textAlign="center" sx={{ py: 4 }}>
          No results found. Try a different search term.
        </Typography>
      </Panel>
    );
  }

  return (
    <Stack spacing={2}>
      {/* Artists Group */}
      {sortedArtists.length > 0 && (
        <Panel>
          <List disablePadding>
            <GroupHeader
              title="Artists"
              count={sortedArtists.length}
              icon={<Person color="primary" />}
              open={openSections.artists ?? true}
              onToggle={() => toggleSection("artists")}
            />
            <Collapse in={openSections.artists ?? true}>
              <List component="div" disablePadding dense>
                {sortedArtists.slice(0, 20).map(([name, files]) => (
                  <ListItemButton
                    key={name}
                    sx={{ pl: 4 }}
                    onClick={() => handleArtistClick(name)}
                  >
                    <ListItemText
                      primary={name}
                      secondary={`${files.length} track${files.length !== 1 ? "s" : ""}`}
                    />
                  </ListItemButton>
                ))}
                {sortedArtists.length > 20 && (
                  <Box sx={{ pl: 4, py: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      + {sortedArtists.length - 20} more artists
                    </Typography>
                  </Box>
                )}
              </List>
            </Collapse>
          </List>
        </Panel>
      )}

      {/* Albums Group */}
      {sortedAlbums.length > 0 && (
        <Panel>
          <List disablePadding>
            <GroupHeader
              title="Albums"
              count={sortedAlbums.length}
              icon={<AlbumIcon color="secondary" />}
              open={openSections.albums ?? true}
              onToggle={() => toggleSection("albums")}
            />
            <Collapse in={openSections.albums ?? true}>
              <List component="div" disablePadding dense>
                {sortedAlbums.slice(0, 20).map(([name, files]) => {
                  // Use the first track's artist as context
                  const artistName = files[0]?.artist ?? "Unknown Artist";
                  return (
                    <ListItemButton
                      key={name}
                      sx={{ pl: 4 }}
                      onClick={() => handleAlbumClick(name, artistName)}
                    >
                      <ListItemText
                        primary={name}
                        secondary={`${artistName} \u00B7 ${files.length} track${files.length !== 1 ? "s" : ""}`}
                      />
                    </ListItemButton>
                  );
                })}
                {sortedAlbums.length > 20 && (
                  <Box sx={{ pl: 4, py: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      + {sortedAlbums.length - 20} more albums
                    </Typography>
                  </Box>
                )}
              </List>
            </Collapse>
          </List>
        </Panel>
      )}

      {/* Tracks Group */}
      {tracks.length > 0 && (
        <Panel>
          <List disablePadding>
            <GroupHeader
              title="Tracks"
              count={tracks.length}
              icon={<MusicNote color="action" />}
              open={openSections.tracks ?? true}
              onToggle={() => toggleSection("tracks")}
            />
            <Collapse in={openSections.tracks ?? true}>
              <List component="div" disablePadding dense>
                {tracks.slice(0, 50).map((track) => (
                  <ListItemButton
                    key={track.file_id}
                    sx={{ pl: 4 }}
                    onClick={() => handleTrackClick(track)}
                  >
                    <ListItemIcon>
                      <MusicNote fontSize="small" />
                    </ListItemIcon>
                    <ListItemText
                      primary={track.title ?? track.path.split("/").pop()}
                      secondary={`${track.artist ?? "Unknown"} \u2014 ${track.album ?? "Unknown"}`}
                    />
                  </ListItemButton>
                ))}
                {tracks.length > 50 && (
                  <Box sx={{ pl: 4, py: 1 }}>
                    <Typography variant="body2" color="text.secondary">
                      + {tracks.length - 50} more tracks
                    </Typography>
                  </Box>
                )}
              </List>
            </Collapse>
          </List>
        </Panel>
      )}
    </Stack>
  );
}
