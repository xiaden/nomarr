/**
 * VectorSearchPage - Search for similar tracks using vector similarity.
 *
 * Features:
 * - Backbone selector (effnet, yamnet, etc.)
 * - File selector to use as query (gets vector from selected track)
 * - Search parameters (limit, min_score)
 * - Results display with track links
 */

import { CloudUpload } from "@mui/icons-material";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Slider,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import type { LibraryFile } from "@shared/api/files";
import { getFilesByIds } from "@shared/api/files";
import { getNavidromeStatus, pushStaticPlaylist } from "@shared/api/navidrome";
import { listBackbones } from "@shared/api/vectors";
import { TrackSearchPicker } from "@shared/components/TrackSearchPicker";
import { PageContainer, Panel, SectionHeader } from "@shared/components/ui";

import { VectorMaintenance } from "../admin/components/VectorMaintenance";

import { useVectorSearch } from "./hooks/useVectorSearch";

export function VectorSearchPage() {
  const [searchParams] = useSearchParams();
  const [backbones, setBackbones] = useState<string[]>([]);
  const [backboneId, setBackboneId] = useState("");
  const [selectedTrack, setSelectedTrack] = useState<LibraryFile | null>(null);
  const [limit, setLimit] = useState(10);
  const [minScore, setMinScore] = useState(0);

  // Navidrome availability check
  const [ndConfigured, setNdConfigured] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const status = await getNavidromeStatus();
        setNdConfigured(status.configured);
      } catch {
        setNdConfigured(false);
      }
    })();
  }, []);

  // Fetch available backbones on mount
  useEffect(() => {
    (async () => {
      try {
        const response = await listBackbones();
        setBackbones(response.backbones);
        if (response.backbones.length > 0) {
          setBackboneId((prev) => prev || response.backbones[0]);
        }
      } catch (error) {
        console.error("Failed to fetch backbones:", error);
      }
    })();
  }, []);

  // pendingAutoSearchFileId tracks when we need to auto-search after URL navigation
  const [pendingAutoSearchFileId, setPendingAutoSearchFileId] = useState<string | null>(
    () => new URLSearchParams(window.location.search).get("fileId")
  );

  // Initialize track from URL params (from "Find Similar" navigation)
  // Runs whenever URL params change — no selectedTrack guard so clicking a result
  // title also loads the new track correctly.
  useEffect(() => {
    const fileIdParam = searchParams.get("fileId");
    if (!fileIdParam) return;

    setPendingAutoSearchFileId(fileIdParam);
    setSelectedTrack(null);

    (async () => {
      try {
        const response = await getFilesByIds([fileIdParam]);
        if (response.files && response.files.length > 0) {
          setSelectedTrack(response.files[0]);
        }
      } catch (error) {
        console.error("Failed to load track from fileId:", error);
        setPendingAutoSearchFileId(null);
      }
    })();
  }, [searchParams]); // Only re-run when URL params change

  const { loading, error, results, searchByFileId } =
    useVectorSearch();

  const [trackMeta, setTrackMeta] = useState<Record<string, LibraryFile>>({});

  // Fetch track metadata whenever results change
  useEffect(() => {
    if (!results || results.length === 0) return;
    (async () => {
      try {
        const ids = results.map((r) => r.file_id);
        const response = await getFilesByIds(ids);
        const meta: Record<string, LibraryFile> = {};
        for (const file of response.files) {
          meta[file.file_id] = file;
        }
        setTrackMeta(meta);
      } catch (err) {
        console.error("Failed to fetch track metadata:", err);
      }
    })();
  }, [results]);

  // Auto-search when navigated via "Find Similar" — fires once track + backbone both ready
  useEffect(() => {
    if (
      pendingAutoSearchFileId &&
      backboneId &&
      selectedTrack?.file_id === pendingAutoSearchFileId
    ) {
      setPendingAutoSearchFileId(null);
      searchByFileId(backboneId, pendingAutoSearchFileId, limit, minScore);
    }
  }, [pendingAutoSearchFileId, backboneId, selectedTrack, limit, minScore, searchByFileId]);

  const handleSearch = useCallback(async () => {
    if (!selectedTrack) return;
    await searchByFileId(backboneId, selectedTrack.file_id, limit, minScore);
  }, [backboneId, selectedTrack, limit, minScore, searchByFileId]);

  // ── Push playlist to Navidrome ──
  const [playlistLoading, setPlaylistLoading] = useState(false);
  const [playlistError, setPlaylistError] = useState<string | null>(null);
  const [playlistSuccess, setPlaylistSuccess] = useState<string | null>(null);

  const handlePushPlaylist = useCallback(async () => {
    if (!results || results.length === 0) return;
    setPlaylistLoading(true);
    setPlaylistError(null);
    setPlaylistSuccess(null);
    try {
      const fileIds = results.map((r) => r.file_id).slice(0, 200);
      const artist = selectedTrack?.artist ?? "Unknown";
      const title = selectedTrack?.title ?? "Unknown";
      const playlistName = `Songs like ${artist} - ${title}`;
      const response = await pushStaticPlaylist(fileIds, playlistName);
      setPlaylistSuccess(
        `Playlist "${response.playlist_name}" pushed to Navidrome (${response.track_count} tracks)`
      );
    } catch (err) {
      console.error("Failed to push playlist:", err);
      setPlaylistError(err instanceof Error ? err.message : "Failed to push playlist to Navidrome");
    } finally {
      setPlaylistLoading(false);
    }
  }, [results, selectedTrack]);

  return (
    <PageContainer title="Vector Search">
      <Stack spacing={3}>
        {/* Vector Store Maintenance */}
        <VectorMaintenance />

        {/* Search Controls */}
        <Panel>
          <SectionHeader title="Search Parameters" />
          <Stack spacing={2}>
            <FormControl fullWidth size="small">
              <InputLabel>Backbone</InputLabel>
              <Select
                value={backboneId}
                label="Backbone"
                onChange={(e) => setBackboneId(e.target.value)}
              >
                {backbones.map((bb) => (
                  <MenuItem key={bb} value={bb}>
                    {bb}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TrackSearchPicker
              onTrackSelect={setSelectedTrack}
              helperText="Search by artist, album, or title to find a track"
            />

            <Box>
              <Typography variant="body2" gutterBottom>
                Limit: {limit}
              </Typography>
              <Slider
                value={limit}
                onChange={(_, v) => setLimit(v as number)}
                min={1}
                max={100}
                valueLabelDisplay="auto"
              />
            </Box>

            <Box>
              <Typography variant="body2" gutterBottom>
                Minimum Similarity: {minScore.toFixed(1)}
              </Typography>
              <Typography variant="caption" color="text.secondary" sx={{ mb: 1, display: "block" }}>
                Filter out results below this threshold. Higher = stricter matching.
              </Typography>
              <Slider
                value={minScore}
                onChange={(_, v) => setMinScore(v as number)}
                min={0}
                max={100}
                step={0.5}
                valueLabelDisplay="auto"
              />
            </Box>

            <Button
              variant="contained"
              onClick={handleSearch}
              disabled={loading || !selectedTrack}
            >
              {loading ? <CircularProgress size={24} /> : "Search"}
            </Button>
          </Stack>
        </Panel>

        {/* Error Display */}
        {error && (
          <Alert severity="error">
            {error}
          </Alert>
        )}

        {/* Results */}
        {results && results.length > 0 && (
          <Panel>
            <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", mb: 1 }}>
              <SectionHeader title={`Results (${results.length})`} />
              <Tooltip title={ndConfigured ? "Push playlist to Navidrome" : "Navidrome not configured"}>
                <span>
                  <Button
                    variant="outlined"
                    size="small"
                    startIcon={playlistLoading ? <CircularProgress size={16} /> : <CloudUpload />}
                    onClick={handlePushPlaylist}
                    disabled={playlistLoading || !ndConfigured}
                  >
                    Push to Navidrome
                  </Button>
                </span>
              </Tooltip>
            </Box>
            {playlistSuccess && (
              <Alert severity="success" sx={{ mb: 1 }} onClose={() => setPlaylistSuccess(null)}>
                {playlistSuccess}
              </Alert>
            )}
            {playlistError && (
              <Alert severity="error" sx={{ mb: 1 }} onClose={() => setPlaylistError(null)}>
                {playlistError}
              </Alert>
            )}
            <Paper variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Title</TableCell>
                    <TableCell>Artist</TableCell>
                    <TableCell>Album</TableCell>
                    <TableCell align="right">Score</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {results.map((result, idx) => {
                    const meta = trackMeta[result.file_id];
                    const title = meta?.title ?? meta?.path?.split("/").pop() ?? result.file_id;
                    const artist = meta?.artist ?? "—";
                    const album = meta?.album ?? "—";
                    return (
                      <TableRow key={idx}>
                        <TableCell>
                          <Typography
                            component={Link}
                            to={`/vector-search?fileId=${encodeURIComponent(result.file_id)}`}
                            sx={{ textDecoration: "none", color: "primary.main", "&:hover": { textDecoration: "underline" } }}
                          >
                            {title}
                          </Typography>
                        </TableCell>
                        <TableCell>{artist}</TableCell>
                        <TableCell>{album}</TableCell>
                        <TableCell align="right">
                          {result.score.toFixed(4)}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Paper>
          </Panel>
        )}

        {/* Empty State */}
        {results && results.length === 0 && (
          <Alert severity="info">
            No similar tracks found. Try adjusting the search parameters.
          </Alert>
        )}
      </Stack>
    </PageContainer>
  );
}
