/**
 * VectorSearchPage - Search for similar tracks using vector similarity.
 *
 * Features:
 * - Backbone selector (effnet, yamnet, etc.)
 * - File selector to use as query (gets vector from selected track)
 * - Search parameters (limit, min_score)
 * - Results display with track links
 */

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
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import type { LibraryFile } from "@shared/api/files";
import { getFilesByIds } from "@shared/api/files";
import { listBackbones } from "@shared/api/vectors";
import { PageContainer, Panel, SectionHeader } from "@shared/components/ui";

import { useVectorSearch } from "./hooks/useVectorSearch";
import { TrackSearchPicker } from "./TrackSearchPicker";

export function VectorSearchPage() {
  const [searchParams] = useSearchParams();
  const [backbones, setBackbones] = useState<string[]>([]);
  const [backboneId, setBackboneId] = useState("");
  const [selectedTrack, setSelectedTrack] = useState<LibraryFile | null>(null);
  const [limit, setLimit] = useState(10);
  const [minScore, setMinScore] = useState(0);

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

  // Initialize track from URL params (from "Find Similar" navigation)
  useEffect(() => {
    const fileIdParam = searchParams.get("fileId");
    if (fileIdParam && !selectedTrack) {
      // Prefetch track metadata by file ID
      (async () => {
        try {
          const response = await getFilesByIds([fileIdParam]);
          if (response.files && response.files.length > 0) {
            setSelectedTrack(response.files[0]);
          }
        } catch (error) {
          console.error("Failed to load track from fileId:", error);
        }
      })();
    }
  }, [searchParams, selectedTrack]);

  const { loading, error, results, searchByFileId } =
    useVectorSearch();

  const handleSearch = useCallback(async () => {
    if (!selectedTrack) return;
    await searchByFileId(backboneId, selectedTrack.file_id, limit, minScore);
  }, [backboneId, selectedTrack, limit, minScore, searchByFileId]);

  return (
    <PageContainer title="Vector Search">
      <Stack spacing={3}>
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
                Min Score: {minScore.toFixed(2)}
              </Typography>
              <Slider
                value={minScore}
                onChange={(_, v) => setMinScore(v as number)}
                min={0}
                max={1}
                step={0.01}
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
            <SectionHeader title={`Results (${results.length})`} />
            <Paper variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>File ID</TableCell>
                    <TableCell align="right">Score</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {results.map((result, idx) => (
                    <TableRow key={idx}>
                      <TableCell>
                        <Typography
                          component="a"
                          href={`#/browse?file=${encodeURIComponent(result.file_id)}`}
                          sx={{ textDecoration: "none", color: "primary.main" }}
                        >
                          {result.file_id}
                        </Typography>
                      </TableCell>
                      <TableCell align="right">
                        {result.score.toFixed(4)}
                      </TableCell>
                    </TableRow>
                  ))}
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
