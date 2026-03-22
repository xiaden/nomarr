/**
 * VectorMaintenance - Admin controls for vector store management.
 *
 * Features:
 * - Display hot/cold stats per backbone per library
 * - Promote vectors from hot to cold store
 * - Rebuild vector indexes
 */

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
  TableHead,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError } from "@shared/api/client";
import {
  getVectorStats,
  listBackbones,
  promoteVectors,
  rebuildVectorIndex,
  type VectorHotColdStats,
} from "@shared/api/vectors";
import { Panel, SectionHeader } from "@shared/components/ui";

export function VectorMaintenance() {
  const [backbones, setBackbones] = useState<string[]>([]);
  const [stats, setStats] = useState<VectorHotColdStats[] | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  const [rebuildingKey, setRebuildingKey] = useState<string | null>(null);
  const [rebuildError, setRebuildError] = useState<string | null>(null);

  const [promoteBackbone, setPromoteBackbone] = useState("");
  const [promoteLibrary, setPromoteLibrary] = useState("");
  const [promoteNlists, setPromoteNlists] = useState<string>("");
  const [promoteLoading, setPromoteLoading] = useState(false);
  const [promoteResult, setPromoteResult] = useState<string | null>(null);
  const [promoteError, setPromoteError] = useState<string | null>(null);

  // Derive unique library keys from stats
  const libraryKeys = useMemo(() => {
    if (!stats) return [];
    return [...new Set(stats.map((s) => s.library_key))];
  }, [stats]);

  // Auto-select first library when available
  useEffect(() => {
    if (libraryKeys.length > 0 && !promoteLibrary) {
      setPromoteLibrary(libraryKeys[0]);
    }
  }, [libraryKeys, promoteLibrary]);

  // Fetch stats on mount
  const fetchStats = useCallback(async () => {
    setStatsLoading(true);
    setStatsError(null);
    try {
      const response = await getVectorStats();
      setStats(response.stats);
    } catch (err) {
      if (err instanceof ApiError) {
        setStatsError(`API Error (${err.status}): ${err.message}`);
      } else if (err instanceof Error) {
        setStatsError(err.message);
      } else {
        setStatsError("Unknown error");
      }
    } finally {
      setStatsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  // Fetch available backbones on mount
  useEffect(() => {
    (async () => {
      try {
        const response = await listBackbones();
        setBackbones(response.backbones);
        if (response.backbones.length > 0) {
          setPromoteBackbone((prev) => prev || response.backbones[0]);
        }
      } catch (error) {
        console.error("Failed to fetch backbones:", error);
      }
    })();
  }, []);

  // Promote vectors
  const handlePromote = useCallback(async () => {
    setPromoteLoading(true);
    setPromoteError(null);
    setPromoteResult(null);
    try {
      const nlists = promoteNlists ? parseInt(promoteNlists, 10) : null;
      const response = await promoteVectors(promoteBackbone, promoteLibrary, nlists);
      setPromoteResult(response.message);
      // Refresh stats after promote
      void fetchStats();
    } catch (err) {
      if (err instanceof ApiError) {
        setPromoteError(`API Error (${err.status}): ${err.message}`);
      } else if (err instanceof Error) {
        setPromoteError(err.message);
      } else {
        setPromoteError("Unknown error");
      }
    } finally {
      setPromoteLoading(false);
    }
  }, [promoteBackbone, promoteLibrary, promoteNlists, fetchStats]);

  const handleRebuildIndex = useCallback(
    async (backboneId: string, libraryKey: string) => {
      const key = `${backboneId}:${libraryKey}`;
      setRebuildingKey(key);
      setRebuildError(null);
      try {
        await rebuildVectorIndex(backboneId, libraryKey);
        void fetchStats();
      } catch (err) {
        if (err instanceof ApiError) {
          setRebuildError(`API Error (${err.status}): ${err.message}`);
        } else if (err instanceof Error) {
          setRebuildError(err.message);
        } else {
          setRebuildError("Rebuild failed");
        }
      } finally {
        setRebuildingKey(null);
      }
    },
    [fetchStats]
  );

  return (
    <Panel>
      <SectionHeader title="Vector Store" />
      <Stack spacing={3}>
        {/* Stats Section */}
        <Box>
          <Box
            sx={{
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              mb: 1,
            }}
          >
            <Typography variant="subtitle2">Hot/Cold Stats</Typography>
            <Button
              size="small"
              onClick={() => void fetchStats()}
              disabled={statsLoading}
            >
              {statsLoading ? <CircularProgress size={16} /> : "Refresh"}
            </Button>
          </Box>

          {statsError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {statsError}
            </Alert>
          )}

          {rebuildError && (
            <Alert severity="error" sx={{ mb: 1 }}>
              {rebuildError}
            </Alert>
          )}

          {stats && (
            <Paper variant="outlined">
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Backbone</TableCell>
                    {libraryKeys.length > 1 && <TableCell>Library</TableCell>}
                    <TableCell align="right">Hot</TableCell>
                    <TableCell align="right">Cold</TableCell>
                    <TableCell align="center">Index</TableCell>
                    <TableCell align="right">Action</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {stats.map((s) => {
                    const rowKey = `${s.backbone_id}:${s.library_key}`;
                    return (
                      <TableRow key={rowKey}>
                        <TableCell>{s.backbone_id}</TableCell>
                        {libraryKeys.length > 1 && (
                          <TableCell>{s.library_key}</TableCell>
                        )}
                        <TableCell align="right">
                          {s.hot_count.toLocaleString()}
                        </TableCell>
                        <TableCell align="right">
                          {s.cold_count.toLocaleString()}
                        </TableCell>
                        <TableCell align="center">
                          <Chip
                            label={s.index_exists ? "exists" : "missing"}
                            color={s.index_exists ? "success" : "warning"}
                            size="small"
                          />
                        </TableCell>
                        <TableCell align="right">
                          <Button
                            size="small"
                            variant="outlined"
                            disabled={rebuildingKey !== null}
                            onClick={() =>
                              void handleRebuildIndex(
                                s.backbone_id,
                                s.library_key
                              )
                            }
                          >
                            {rebuildingKey === rowKey ? (
                              <CircularProgress size={16} />
                            ) : (
                              "Rebuild Index"
                            )}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </Paper>
          )}
        </Box>

        {/* Promote Section */}
        <Box>
          <Typography variant="subtitle2" gutterBottom>
            Promote Vectors
          </Typography>
          <Stack spacing={1.5}>
            <FormControl fullWidth size="small">
              <InputLabel>Backbone</InputLabel>
              <Select
                value={promoteBackbone}
                label="Backbone"
                onChange={(e) => setPromoteBackbone(e.target.value)}
              >
                {backbones.map((bb) => (
                  <MenuItem key={bb} value={bb}>
                    {bb}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>

            {libraryKeys.length > 1 && (
              <FormControl fullWidth size="small">
                <InputLabel>Library</InputLabel>
                <Select
                  value={promoteLibrary}
                  label="Library"
                  onChange={(e) => setPromoteLibrary(e.target.value)}
                >
                  {libraryKeys.map((lk) => (
                    <MenuItem key={lk} value={lk}>
                      {lk}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            )}

            <TextField
              label="HNSW nlists (optional)"
              placeholder="Auto-calculated if empty"
              value={promoteNlists}
              onChange={(e) => setPromoteNlists(e.target.value)}
              size="small"
              fullWidth
              type="number"
              inputProps={{ min: 1 }}
              helperText="Number of HNSW graph lists. Leave empty for auto."
            />

            <Button
              variant="contained"
              onClick={() => void handlePromote()}
              disabled={promoteLoading || !promoteBackbone || !promoteLibrary}
            >
              {promoteLoading ? (
                <CircularProgress size={24} />
              ) : (
                "Promote & Rebuild"
              )}
            </Button>

            {promoteError && (
              <Alert severity="error">{promoteError}</Alert>
            )}
            {promoteResult && (
              <Alert severity="success">{promoteResult}</Alert>
            )}
          </Stack>
        </Box>
      </Stack>
    </Panel>
  );
}
