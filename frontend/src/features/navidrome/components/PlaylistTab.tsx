/**
 * Navidrome Playlist Generator tab.
 * Allows building Smart Playlist queries and generating .nsp files.
 */

import {
    Box,
    Button,
    Stack,
    TextField,
    Typography,
} from "@mui/material";

import { ErrorMessage, Panel, SectionHeader } from "@shared/components/ui";

interface PlaylistTabProps {
  query: string;
  name: string;
  comment: string;
  limit: number | undefined;
  sort: string;
  preview: Record<string, unknown> | null;
  content: string | null;
  loading: boolean;
  error: string | null;
  onQueryChange: (value: string) => void;
  onNameChange: (value: string) => void;
  onCommentChange: (value: string) => void;
  onLimitChange: (value: number | undefined) => void;
  onSortChange: (value: string) => void;
  onPreview: (e: React.FormEvent) => void;
  onGenerate: () => void;
}

export function PlaylistTab({
  query,
  name,
  comment,
  limit,
  sort,
  preview,
  content,
  loading,
  error,
  onQueryChange,
  onNameChange,
  onCommentChange,
  onLimitChange,
  onSortChange,
  onPreview,
  onGenerate,
}: PlaylistTabProps) {
  const handleDownload = () => {
    if (content) {
      const blob = new Blob([content], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${name}.nsp`;
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  return (
    <Stack spacing={2.5}>
      <Panel>
        <SectionHeader title="Smart Playlist Generator" />
        <Box component="form" onSubmit={onPreview}>
          <Stack spacing={2}>
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                Query *
              </Typography>
              <TextField
                value={query}
                onChange={(e) => onQueryChange(e.target.value)}
                placeholder="e.g., tag:nom_happy > 0.8"
                multiline
                rows={3}
                disabled={loading}
                required
                fullWidth
                InputProps={{
                  sx: { fontFamily: "monospace", fontSize: "0.875rem" },
                }}
              />
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                Playlist Name *
              </Typography>
              <TextField
                value={name}
                onChange={(e) => onNameChange(e.target.value)}
                disabled={loading}
                required
                fullWidth
              />
            </Box>
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                Comment
              </Typography>
              <TextField
                value={comment}
                onChange={(e) => onCommentChange(e.target.value)}
                disabled={loading}
                fullWidth
              />
            </Box>
            <Box sx={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 1.25 }}>
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                  Limit
                </Typography>
                <TextField
                  type="number"
                  value={limit ?? ""}
                  onChange={(e) =>
                    onLimitChange(e.target.value ? parseInt(e.target.value) : undefined)
                  }
                  disabled={loading}
                  placeholder="Optional"
                  fullWidth
                />
              </Box>
              <Box>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                  Sort
                </Typography>
                <TextField
                  value={sort}
                  onChange={(e) => onSortChange(e.target.value)}
                  disabled={loading}
                  placeholder="Optional"
                  fullWidth
                />
              </Box>
            </Box>
            <Stack direction="row" spacing={1.25}>
              <Button type="submit" variant="contained" disabled={loading} fullWidth>
                {loading ? "Loading..." : "Preview Query"}
              </Button>
              <Button
                type="button"
                onClick={onGenerate}
                variant="contained"
                disabled={loading}
                fullWidth
              >
                {loading ? "Generating..." : "Generate .nsp"}
              </Button>
            </Stack>
          </Stack>
        </Box>
        {error && <ErrorMessage>Error: {error}</ErrorMessage>}
      </Panel>

      {preview && (
        <Panel>
          <SectionHeader title="Query Preview" />
          <Box
            component="pre"
            sx={{
              p: 2,
              bgcolor: "background.default",
              border: 1,
              borderColor: "divider",
              borderRadius: 1,
              overflow: "auto",
              fontSize: "0.875rem",
              fontFamily: "monospace",
            }}
          >
            {JSON.stringify(preview, null, 2)}
          </Box>
        </Panel>
      )}

      {content && (
        <Panel>
          <SectionHeader title="Generated Playlist (.nsp)" />
          <TextField
            multiline
            rows={15}
            value={content}
            fullWidth
            InputProps={{
              readOnly: true,
              sx: { fontFamily: "monospace", fontSize: "0.875rem" },
            }}
          />
          <Button onClick={handleDownload} variant="contained" sx={{ mt: 1.25 }}>
            Download .nsp File
          </Button>
        </Panel>
      )}
    </Stack>
  );
}
