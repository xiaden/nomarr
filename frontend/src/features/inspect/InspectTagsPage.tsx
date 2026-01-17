/**
 * Inspect Tags page.
 *
 * Features:
 * - View tags from a specific audio file
 * - Display namespace and tag count
 * - Show all tags with their values
 * - Browse filesystem to select file
 */

import {
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

import { ConfirmDialog, ErrorMessage, PageContainer, Panel, SectionHeader } from "@shared/components/ui";
import { useConfirmDialog } from "../../hooks/useConfirmDialog";

import { removeTags, showTags } from "../../shared/api/tags";
import { ServerFilePicker } from "../../shared/components/ServerFilePicker";

interface TagsData {
  path: string;
  namespace: string;
  tags: Record<string, unknown>;
  count: number;
}

export function InspectTagsPage() {
  const { confirm, isOpen, options, handleConfirm, handleCancel } = useConfirmDialog();

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
    <PageContainer title="Inspect Tags">
      <Panel>
        <SectionHeader title="File Path" />
        <Box component="form" onSubmit={handleSubmit}>
          <Stack direction="row" spacing={1.25}>
            <TextField
              value={filePath}
              onChange={(e) => setFilePath(e.target.value)}
              placeholder="Enter relative path to audio file"
              disabled={loading}
              fullWidth
            />
            <Button
              onClick={() => setShowPicker(!showPicker)}
              variant="outlined"
              disabled={loading}
              sx={{ minWidth: 100 }}
            >
              {showPicker ? "Hide" : "Browse..."}
            </Button>
            <Button
              type="submit"
              variant="contained"
              disabled={loading || !filePath.trim()}
              sx={{ minWidth: 100 }}
            >
              {loading ? "Loading..." : "Inspect"}
            </Button>
          </Stack>
        </Box>
        {showPicker && (
          <Box sx={{ mt: 2 }}>
            <ServerFilePicker
              value={filePath}
              onChange={(newPath) => {
                setFilePath(newPath);
                setShowPicker(false);
              }}
              mode="file"
              label="Select Audio File"
            />
          </Box>
        )}
      </Panel>

      {error && (
        <Panel>
          <ErrorMessage>Error: {error}</ErrorMessage>
        </Panel>
      )}

      {removeSuccess && (
        <Panel>
          <Typography color="primary">{removeSuccess}</Typography>
        </Panel>
      )}

      {tagsData && (
        <Stack spacing={2.5}>
          {/* Metadata */}
          <Panel>
            <SectionHeader
              title="File Metadata"
              action={
                tagsData.count > 0 ? (
                  <Button
                    onClick={handleRemoveTags}
                    disabled={removing}
                    variant="contained"
                    color="error"
                    size="small"
                    title="Remove all tags from this file"
                  >
                    {removing ? "Removing..." : "Remove All Tags"}
                  </Button>
                ) : undefined
              }
            />
            <Stack spacing={1.25}>
              <Box>
                <Typography component="span" fontWeight="bold" color="text.secondary" sx={{ mr: 1.25 }}>
                  Path:
                </Typography>
                <Typography component="span">{tagsData.path}</Typography>
              </Box>
              <Box>
                <Typography component="span" fontWeight="bold" color="text.secondary" sx={{ mr: 1.25 }}>
                  Namespace:
                </Typography>
                <Typography component="span">{tagsData.namespace}</Typography>
              </Box>
              <Box>
                <Typography component="span" fontWeight="bold" color="text.secondary" sx={{ mr: 1.25 }}>
                  Tag Count:
                </Typography>
                <Typography component="span">{tagsData.count}</Typography>
              </Box>
            </Stack>
          </Panel>

          {/* Tags */}
          <Panel>
            <SectionHeader title="Tags" />
            {tagsData.count === 0 ? (
              <Typography color="text.secondary" fontStyle="italic">
                No tags found in this file.
              </Typography>
            ) : (
              <Box sx={{ overflowX: "auto" }}>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                        Tag Key
                      </TableCell>
                      <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                        Value
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {Object.entries(tagsData.tags).map(([key, value]) => (
                      <TableRow key={key}>
                        <TableCell sx={{ borderColor: "divider", wordBreak: "break-word" }}>
                          {key}
                        </TableCell>
                        <TableCell sx={{ borderColor: "divider", wordBreak: "break-word" }}>
                          {renderValue(value)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </Panel>
        </Stack>
      )}

      {!tagsData && !error && (
        <Panel>
          <Typography color="text.secondary" fontStyle="italic">
            Enter a file path above to inspect its tags.
          </Typography>
        </Panel>
      )}

      {/* Confirm dialog for remove tags action */}
      <ConfirmDialog
        open={isOpen}
        title={options.title}
        message={options.message}
        confirmLabel={options.confirmLabel}
        cancelLabel={options.cancelLabel}
        severity={options.severity}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    </PageContainer>
  );
}
