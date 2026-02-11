/**
 * Navidrome Playlist Generator tab.
 * Visual rule builder for Smart Playlist queries with .nsp generation.
 */

import {
  Box,
  Button,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import type { PlaylistPreviewResponse } from "@shared/api/navidrome";
import { ErrorMessage, Panel, SectionHeader } from "@shared/components/ui";

import { useTagMetadata } from "../hooks/useTagMetadata";

import { PreviewTable } from "./PreviewTable";
import { RuleBuilder } from "./RuleBuilder";
import type { RuleGroup } from "./ruleUtils";
import { buildQueryString } from "./ruleUtils";
import { SortPicker } from "./SortPicker";

interface PlaylistTabProps {
  rootGroup: RuleGroup;
  name: string;
  comment: string;
  limit: number | undefined;
  sort: string;
  preview: PlaylistPreviewResponse | null;
  content: string | null;
  loading: boolean;
  error: string | null;
  onGroupChange: (group: RuleGroup) => void;
  onNameChange: (value: string) => void;
  onCommentChange: (value: string) => void;
  onLimitChange: (value: number | undefined) => void;
  onSortChange: (value: string) => void;
  onPreview: () => void;
  onGenerate: () => void;
}

export function PlaylistTab({
  rootGroup,
  name,
  comment,
  limit,
  sort,
  preview,
  content,
  loading,
  error,
  onGroupChange,
  onNameChange,
  onCommentChange,
  onLimitChange,
  onSortChange,
  onPreview,
  onGenerate,
}: PlaylistTabProps) {
  const { numericTags, stringTags, loading: tagsLoading } = useTagMetadata();

  const assembledQuery = buildQueryString(rootGroup);
  const hasValidRules = assembledQuery.length > 0;

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
        <Stack spacing={2}>
          {/* Rule builder */}
          <RuleBuilder
            rootGroup={rootGroup}
            numericTags={numericTags}
            stringTags={stringTags}
            onGroupChange={onGroupChange}
          />

          {tagsLoading && (
            <Typography variant="caption" color="text.secondary">
              Loading tag metadata…
            </Typography>
          )}

          {/* Assembled query (read-only) */}
          {assembledQuery && (
            <TextField
              value={assembledQuery}
              label="Generated query"
              size="small"
              fullWidth
              slotProps={{
                input: {
                  readOnly: true,
                  sx: { fontFamily: "monospace", fontSize: "0.8rem" },
                },
              }}
            />
          )}

          {/* Playlist metadata */}
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
              size="small"
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
              size="small"
            />
          </Box>

          {/* Sort + Limit row */}
          <Stack direction="row" spacing={2} alignItems="flex-end">
            <Box>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5, fontWeight: 600 }}>
                Sort
              </Typography>
              <SortPicker value={sort} onChange={onSortChange} />
            </Box>
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
                size="small"
                sx={{ width: 120 }}
              />
            </Box>
          </Stack>

          {/* Action buttons */}
          <Stack direction="row" spacing={1.25}>
            <Button
              variant="contained"
              disabled={loading || !hasValidRules}
              onClick={onPreview}
              fullWidth
            >
              {loading ? "Loading…" : "Preview Query"}
            </Button>
            <Button
              variant="contained"
              disabled={loading || !hasValidRules}
              onClick={onGenerate}
              fullWidth
            >
              {loading ? "Generating…" : "Generate .nsp"}
            </Button>
          </Stack>
        </Stack>
        {error && <ErrorMessage>Error: {error}</ErrorMessage>}
      </Panel>

      {/* Preview results */}
      {preview && (
        <Panel>
          <SectionHeader title="Query Preview" />
          <PreviewTable data={preview} />
        </Panel>
      )}

      {/* Generated playlist content */}
      {content && (
        <Panel>
          <SectionHeader title="Generated Playlist (.nsp)" />
          <TextField
            multiline
            rows={15}
            value={content}
            fullWidth
            slotProps={{
              input: {
                readOnly: true,
                sx: { fontFamily: "monospace", fontSize: "0.875rem" },
              },
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
