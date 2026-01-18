/**
 * InspectTags component - moved from separate Inspect page to Admin page.
 * Debug tool for viewing and removing tags from specific audio files.
 */

import {
    Alert,
    Box,
    Button,
    Stack,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableRow,
    TextField,
    Typography,
} from "@mui/material";
import { useState } from "react";

import { Panel, SectionHeader } from "@shared/components/ui";

import { useConfirmDialog } from "../../../hooks/useConfirmDialog";
import { removeTags, showTags } from "../../../shared/api/tags";
import { ServerFilePicker } from "../../../shared/components/ServerFilePicker";

interface TagsData {
  path: string;
  namespace: string;
  tags: Record<string, unknown>;
  count: number;
}

export function InspectTags() {
  const { confirm } = useConfirmDialog();
  
  const [filePath, setFilePath] = useState("");
  const [tagsData, setTagsData] = useState<TagsData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showPicker, setShowPicker] = useState(false);
  const [removing, setRemoving] = useState(false);
  const [removeSuccess, setRemoveSuccess] = useState<string | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!filePath.trim()) return;

    try {
      setLoading(true);
      setError(null);
      setRemoveSuccess(null);
      const data = await showTags(filePath);
      setTagsData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tags");
      setTagsData(null);
      console.error("[Inspect] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleRemoveTags = async () => {
    if (!filePath.trim()) return;
    if (!(await confirm({
      title: "Remove All Tags?",
      message: `Remove all tags from ${filePath}?\n\nThis cannot be undone!`,
      severity: "warning",
    }))) return;

    try {
      setRemoving(true);
      setError(null);
      setRemoveSuccess(null);
      const result = await removeTags(filePath);
      setRemoveSuccess(`Removed ${result.removed} tag(s) from ${result.path}`);
      // Refresh tags to show empty state
      const data = await showTags(filePath);
      setTagsData(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to remove tags");
      console.error("[Inspect] Remove error:", err);
    } finally {
      setRemoving(false);
    }
  };

  const renderValue = (value: unknown): string => {
    if (Array.isArray(value)) {
      return value.join(", ");
    }
    return String(value);
  };

  return (
    <Panel>
      <SectionHeader title="Inspect Tags" />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2.5 }}>
        Debug tool to view and remove tags from individual audio files.
      </Typography>

      <form onSubmit={handleSubmit}>
        <Stack spacing={2}>
          <Box sx={{ display: "flex", gap: 1.25, alignItems: "center" }}>
            <TextField
              label="File Path"
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              placeholder="/music/artist/album/track.flac"
              fullWidth
              size="small"
              disabled={loading || removing}
            />
            <Button
              type="button"
              variant="outlined"
              onClick={() => setShowPicker(true)}
              disabled={loading || removing}
              sx={{ whiteSpace: "nowrap", minWidth: "fit-content" }}
            >
              Browse Files
            </Button>
            <Button
              type="submit"
              variant="contained"
              disabled={!filePath.trim() || loading || removing}
              sx={{ whiteSpace: "nowrap", minWidth: "fit-content" }}
            >
              {loading ? "Loading..." : "Show Tags"}
            </Button>
          </Box>

          {error && <Alert severity="error">{error}</Alert>}
          {removeSuccess && <Alert severity="success">{removeSuccess}</Alert>}

          {showPicker && (
            <Box sx={{ mt: 2 }}>
              <ServerFilePicker
                value={filePath}
                onChange={(path: string) => {
                  setFilePath(path);
                  setShowPicker(false);
                }}
                mode="file"
                label="Select Audio File"
              />
            </Box>
          )}

          {tagsData && (
            <Stack spacing={2}>
              <Box
                sx={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  py: 1,
                  px: 2,
                  backgroundColor: "action.hover",
                  borderRadius: 1,
                }}
              >
                <Typography variant="body2">
                  <strong>File:</strong> {tagsData.path}
                </Typography>
                <Typography variant="body2">
                  <strong>Tags:</strong> {tagsData.count}
                </Typography>
              </Box>

              {tagsData.count > 0 && (
                <>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell><strong>Key</strong></TableCell>
                        <TableCell><strong>Value</strong></TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {Object.entries(tagsData.tags).map(([key, value]) => (
                        <TableRow key={key}>
                          <TableCell sx={{ fontFamily: "monospace" }}>{key}</TableCell>
                          <TableCell sx={{ wordBreak: "break-all" }}>
                            {renderValue(value)}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>

                  <Box sx={{ display: "flex", justifyContent: "flex-end" }}>
                    <Button
                      onClick={handleRemoveTags}
                      variant="outlined"
                      color="error"
                      disabled={removing}
                      sx={{ textTransform: "none" }}
                    >
                      {removing ? "Removing..." : "Remove All Tags"}
                    </Button>
                  </Box>
                </>
              )}

              {tagsData.count === 0 && (
                <Alert severity="info">No tags found in this file.</Alert>
              )}
            </Stack>
          )}
        </Stack>
      </form>
    </Panel>
  );
}