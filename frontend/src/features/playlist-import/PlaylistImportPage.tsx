/**
 * Playlist Import page.
 *
 * Allows users to paste Spotify or Deezer playlist URLs and convert them
 * to M3U playlists by matching against the local library.
 */

import { ContentPaste, Download, MusicNote } from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

import { PageContainer } from "@shared/components/ui";

import { list as getLibraries } from "../../shared/api/library";
import {
  type ConvertPlaylistResponse,
  type MatchTier,
  convertPlaylist,
  getSpotifyStatus,
} from "../../shared/api/playlistImport";
import type { Library } from "../../shared/types";

// Color mapping for match tiers
const tierColors: Record<MatchTier, "success" | "info" | "warning" | "error" | "default"> = {
  isrc: "success",
  exact: "success",
  fuzzy_high: "info",
  fuzzy_low: "warning",
  none: "error",
};

const tierLabels: Record<MatchTier, string> = {
  isrc: "ISRC Match",
  exact: "Exact",
  fuzzy_high: "High Fuzzy",
  fuzzy_low: "Low Fuzzy",
  none: "Not Found",
};

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
        url: url.trim(),
        library_id: selectedLibrary,
      });
      setResult(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to convert playlist");
    } finally {
      setLoading(false);
    }
  }, [url, selectedLibrary]);

  const handleDownload = useCallback(() => {
    if (!result) return;

    const blob = new Blob([result.m3u_content], { type: "audio/x-mpegurl" });
    const downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `${result.playlist.name}.m3u`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(downloadUrl);
  }, [result]);

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
            <Stack spacing={2}>
              {/* Playlist info header */}
              <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <Box>
                  <Typography variant="h6">{result.playlist.name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {result.playlist.track_count} tracks from {result.playlist.platform}
                  </Typography>
                </Box>
                <Button
                  variant="outlined"
                  startIcon={<Download />}
                  onClick={handleDownload}
                >
                  Download M3U
                </Button>
              </Box>

              {/* Match statistics */}
              <Box sx={{ display: "flex", gap: 2 }}>
                <Chip
                  label={`${result.matched_count} matched`}
                  color="success"
                  variant="outlined"
                />
                <Chip
                  label={`${result.unmatched_count} not found`}
                  color="error"
                  variant="outlined"
                />
                <Chip
                  label={`${Math.round((result.matched_count / result.playlist.track_count) * 100)}% success`}
                  variant="outlined"
                />
              </Box>

              {/* Results table */}
              <TableContainer sx={{ maxHeight: 400 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>Track</TableCell>
                      <TableCell>Artist</TableCell>
                      <TableCell>Match</TableCell>
                      <TableCell align="right">Confidence</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {result.results.map((row, idx) => (
                      <TableRow key={idx} sx={{ opacity: row.matched ? 1 : 0.6 }}>
                        <TableCell>{row.input_title}</TableCell>
                        <TableCell>{row.input_artist}</TableCell>
                        <TableCell>
                          <Chip
                            label={tierLabels[row.tier]}
                            color={tierColors[row.tier]}
                            size="small"
                          />
                        </TableCell>
                        <TableCell align="right">
                          {row.matched ? `${Math.round(row.confidence * 100)}%` : "-"}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Stack>
          </Paper>
        )}
      </Stack>
    </PageContainer>
  );
}
