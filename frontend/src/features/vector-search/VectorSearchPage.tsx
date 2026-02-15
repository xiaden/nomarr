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
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageContainer, Panel, SectionHeader } from "@shared/components/ui";

import { useVectorSearch } from "./hooks/useVectorSearch";

// Known backbones (could be fetched from API in future)
const BACKBONES = ["discogs_effnet", "discogs_musicnn"];

export function VectorSearchPage() {
  const [searchParams] = useSearchParams();
  const [backboneId, setBackboneId] = useState(BACKBONES[0]);
  const [queryFileId, setQueryFileId] = useState("");
  const [limit, setLimit] = useState(10);
  const [minScore, setMinScore] = useState(0);

  // Initialize file ID from URL params (from "Find Similar" navigation)
  useEffect(() => {
    const fileIdParam = searchParams.get("fileId");
    if (fileIdParam && !queryFileId) {
      setQueryFileId(fileIdParam);
    }
  }, [searchParams, queryFileId]);

  const { loading, error, results, searchByFileId } =
    useVectorSearch();

  const handleSearch = useCallback(async () => {
    if (!queryFileId.trim()) return;
    await searchByFileId(backboneId, queryFileId.trim(), limit, minScore);
  }, [backboneId, queryFileId, limit, minScore, searchByFileId]);

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
                {BACKBONES.map((bb) => (
                  <MenuItem key={bb} value={bb}>
                    {bb}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            <TextField
              label="File ID"
              placeholder="library_files/12345"
              value={queryFileId}
              onChange={(e) => setQueryFileId(e.target.value)}
              size="small"
              fullWidth
              helperText="Enter a library file ID to find similar tracks"
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
              disabled={loading || !queryFileId.trim()}
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
