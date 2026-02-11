/**
 * Playlist Import page.
 *
 * Allows users to paste Spotify or Deezer playlist URLs and convert them
 * to M3U playlists by matching against the local library.
 */

import { ContentPaste, MusicNote } from "@mui/icons-material";
import {
  Alert,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { PageContainer } from "@shared/components/ui";

import { list as getLibraries } from "../../shared/api/library";
import {
  type ConvertPlaylistResponse,
  convertPlaylist,
  getSpotifyStatus,
} from "../../shared/api/playlistImport";
import type { Library } from "../../shared/types";

import { PlaylistMatchTable } from "./PlaylistMatchTable";


export function PlaylistImportPage() {
  // Form state
  const [url, setUrl] = useState("");
  const [selectedLibrary, setSelectedLibrary] = useState("");
  const [libraries, setLibraries] = useState<Library[]>([]);

  // Result state
  const [result, setResult] = useState<ConvertPlaylistResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Feature availability
  const [spotifyEnabled, setSpotifyEnabled] = useState<boolean | null>(null);

  // Load libraries and Spotify status on mount
  useEffect(() => {
    getLibraries()
      .then((libs) => {
        setLibraries(libs);
        if (libs.length > 0) {
          setSelectedLibrary(libs[0].library_id);
        }
      })
      .catch(() => setLibraries([]));

    getSpotifyStatus()
      .then((status) => setSpotifyEnabled(status.configured))
      .catch(() => setSpotifyEnabled(false));
  }, []);

  const handleConvert = useCallback(async () => {
    if (!url.trim() || !selectedLibrary) return;

    setLoading(true);
    setError(null);
    setResult(null);

    try {
      const response = await convertPlaylist({
        playlist_url: url.trim(),
        library_id: selectedLibrary,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to convert playlist");
    } finally {
      setLoading(false);
    }
  }, [url, selectedLibrary]);

  const isSpotifyUrl = url.includes("spotify");
  const spotifyDisabled = isSpotifyUrl && spotifyEnabled === false;

  return (
    <PageContainer title="Playlist Import">
      <Stack spacing={3}>
        {/* Info alert */}
        <Alert severity="info" icon={<MusicNote />}>
          Paste a Spotify or Deezer playlist URL to convert it to an M3U playlist by matching
          tracks against your local library.
        </Alert>

        {/* Spotify warning if not configured */}
        {spotifyEnabled === false && (
          <Alert severity="warning">
            Spotify credentials not configured. Add <code>spotify_client_id</code> and{" "}
            <code>spotify_client_secret</code> to your config to enable Spotify playlists.
          </Alert>
        )}

        {/* Input form */}
        <Paper sx={{ p: 3 }}>
          <Stack spacing={2}>
            <TextField
              label="Playlist URL"
              placeholder="https://open.spotify.com/playlist/... or https://deezer.com/playlist/..."
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              fullWidth
              InputProps={{
                startAdornment: <ContentPaste sx={{ mr: 1, color: "text.secondary" }} />,
              }}
            />

            <FormControl fullWidth>
              <InputLabel>Library</InputLabel>
              <Select
                value={selectedLibrary}
                label="Library"
                onChange={(e) => setSelectedLibrary(e.target.value)}
              >
                {libraries.map((lib) => (
                  <MenuItem key={lib.library_id} value={lib.library_id}>
                    {lib.name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <Button
              variant="contained"
              onClick={handleConvert}
              disabled={!url.trim() || !selectedLibrary || loading || spotifyDisabled}
              startIcon={loading ? <CircularProgress size={20} /> : <MusicNote />}
            >
              {loading ? "Converting..." : "Convert Playlist"}
            </Button>
          </Stack>
        </Paper>

        {/* Error display */}
        {error && <Alert severity="error">{error}</Alert>}

        {/* Results */}
        {result && (
          <Paper sx={{ p: 3 }}>
            <PlaylistMatchTable result={result} />
          </Paper>
        )}
      </Stack>
    </PageContainer>
  );
}
