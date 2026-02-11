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
  statusToTier,
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

  const handleDownload = useCallback(() => {
    if (!result) return;

    const blob = new Blob([result.m3u_content], { type: "audio/x-mpegurl" });
    const downloadUrl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = downloadUrl;
    a.download = `${result.playlist_metadata.name}.m3u`;
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
                  <Typography variant="h6">{result.playlist_metadata.name}</Typography>
                  <Typography variant="body2" color="text.secondary">
                    {result.total_tracks} tracks from {result.playlist_metadata.source_platform}
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
              <Box sx={{ display: "flex", gap: 2, flexWrap: "wrap" }}>
                <Chip
                  label={`${result.exact_matches} exact`}
                  color="success"
                  variant="outlined"
                />
                {result.fuzzy_matches > 0 && (
                  <Chip
                    label={`${result.fuzzy_matches} fuzzy`}
                    color="info"
                    variant="outlined"
                  />
                )}
                {result.ambiguous_count > 0 && (
                  <Chip
                    label={`${result.ambiguous_count} ambiguous`}
                    color="warning"
                    variant="outlined"
                  />
                )}
                {result.not_found_count > 0 && (
                  <Chip
                    label={`${result.not_found_count} not found`}
                    color="error"
                    variant="outlined"
                  />
                )}
                <Chip
                  label={`${Math.round(result.match_rate * 100)}% matched`}
                  variant="outlined"
                />
              </Box>

              {/* Ambiguous matches needing review */}
              {result.ambiguous_matches.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                    Ambiguous matches (need review)
                  </Typography>
                  <TableContainer sx={{ maxHeight: 300 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>Track</TableCell>
                          <TableCell>Artist</TableCell>
                          <TableCell>Matched To</TableCell>
                          <TableCell align="right">Confidence</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {result.ambiguous_matches.map((match, idx) => (
                          <TableRow key={idx}>
                            <TableCell>{match.input_track.title}</TableCell>
                            <TableCell>{match.input_track.artist}</TableCell>
                            <TableCell sx={{ maxWidth: 300, overflow: "hidden", textOverflow: "ellipsis" }}>
                              {match.matched_path?.split("/").pop() || "-"}
                            </TableCell>
                            <TableCell align="right">
                              <Chip
                                label={`${Math.round(match.confidence * 100)}%`}
                                color={tierColors[statusToTier(match.status)]}
                                size="small"
                              />
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}

              {/* Unmatched tracks */}
              {result.unmatched_tracks.length > 0 && (
                <Box>
                  <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>
                    Not found in library
                  </Typography>
                  <TableContainer sx={{ maxHeight: 300 }}>
                    <Table size="small" stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>Track</TableCell>
                          <TableCell>Artist</TableCell>
                          <TableCell>Album</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {result.unmatched_tracks.map((track, idx) => (
                          <TableRow key={idx}>
                            <TableCell>{track.title}</TableCell>
                            <TableCell>{track.artist}</TableCell>
                            <TableCell>{track.album || "-"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              )}
            </Stack>
          </Paper>
        )}
      </Stack>
    </PageContainer>
  );
}
