/**
 * Navidrome Config Generator tab.
 * Allows loading tag preview and generating TOML configuration.
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
} from "@mui/material";

import { ErrorMessage, Panel, SectionHeader } from "@shared/components/ui";

interface TagPreview {
  tag_key: string;
  type: string;
  is_multivalue: boolean;
  summary: string;
  total_count: number;
}

interface ConfigTabProps {
  preview: TagPreview[] | null;
  configText: string | null;
  loading: boolean;
  error: string | null;
  onLoadPreview: () => void;
  onGenerateConfig: () => void;
}

export function ConfigTab({
  preview,
  configText,
  loading,
  error,
  onLoadPreview,
  onGenerateConfig,
}: ConfigTabProps) {
  const handleCopyToClipboard = () => {
    if (configText) {
      navigator.clipboard.writeText(configText);
      alert("Copied to clipboard!");
    }
  };

  return (
    <Stack spacing={2.5}>
      <Panel>
        <SectionHeader title="Navidrome TOML Configuration" />
        <Stack spacing={1.25}>
          <Button
            onClick={onLoadPreview}
            disabled={loading}
            variant="contained"
            fullWidth
          >
            {loading ? "Loading..." : "Load Tag Preview"}
          </Button>
          <Button
            onClick={onGenerateConfig}
            disabled={loading}
            variant="contained"
            fullWidth
          >
            {loading ? "Generating..." : "Generate Config"}
          </Button>
        </Stack>
        {error && <ErrorMessage>Error: {error}</ErrorMessage>}
      </Panel>

      {preview && (
        <Panel>
          <SectionHeader title="Tag Preview" />
          <Box sx={{ overflowX: "auto" }}>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                    Tag
                  </TableCell>
                  <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                    Type
                  </TableCell>
                  <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                    Multivalue
                  </TableCell>
                  <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                    Count
                  </TableCell>
                  <TableCell sx={{ bgcolor: "background.default", borderBottom: 2 }}>
                    Summary
                  </TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.map((tag) => (
                  <TableRow key={tag.tag_key}>
                    <TableCell sx={{ borderColor: "divider" }}>{tag.tag_key}</TableCell>
                    <TableCell sx={{ borderColor: "divider" }}>{tag.type}</TableCell>
                    <TableCell sx={{ borderColor: "divider" }}>
                      {tag.is_multivalue ? "Yes" : "No"}
                    </TableCell>
                    <TableCell sx={{ borderColor: "divider" }}>{tag.total_count}</TableCell>
                    <TableCell sx={{ borderColor: "divider" }}>{tag.summary}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Box>
        </Panel>
      )}

      {configText && (
        <Panel>
          <SectionHeader title="Generated Config" />
          <TextField
            multiline
            rows={20}
            value={configText}
            fullWidth
            InputProps={{
              readOnly: true,
              sx: { fontFamily: "monospace", fontSize: "0.875rem" },
            }}
          />
          <Button
            onClick={handleCopyToClipboard}
            variant="contained"
            sx={{ mt: 1.25 }}
          >
            Copy to Clipboard
          </Button>
        </Panel>
      )}
    </Stack>
  );
}
