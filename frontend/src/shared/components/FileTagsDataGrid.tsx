/**
 * FileTagsDataGrid - Display file tags in grouped accordions
 *
 * Features:
 * - Tags grouped into 4 categories: Metadata, Nomarr Tags, Raw Head Outputs, Extended Metadata
 * - Accordion expand/collapse per group
 * - Quick filter search across all groups
 * - Toggle to show only Nomarr tags
 * - Compact key-value table layout within each group
 */

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
    Accordion,
    AccordionDetails,
    AccordionSummary,
    Box,
    FormControlLabel,
    Stack,
    Switch,
    Table,
    TableBody,
    TableCell,
    TableRow,
    TextField,
    Tooltip,
    Typography,
} from "@mui/material";
import { useMemo, useState } from "react";

interface FileTag {
  key: string;
  value: string;
  type: string;
  is_nomarr: boolean;
}

interface FileTagsDataGridProps {
  tags: FileTag[];
}

// ──────────────────────────────────────────────────────────────────────
// Tag Grouping
// ──────────────────────────────────────────────────────────────────────

type TagGroupId = "metadata" | "nomarr" | "rawHeads" | "extended";

interface TagGroup {
  id: TagGroupId;
  label: string;
  defaultExpanded: boolean;
  tags: FileTag[];
}

const METADATA_WHITELIST = new Set([
  "title",
  "artist",
  "artists",
  "album",
  "album_artist",
  "genre",
  "year",
  "date",
]);

const GROUP_DEFS: Omit<TagGroup, "tags">[] = [
  { id: "metadata", label: "Metadata", defaultExpanded: true },
  { id: "nomarr", label: "Nomarr Tags", defaultExpanded: true },
  { id: "rawHeads", label: "Raw Head Outputs", defaultExpanded: false },
  { id: "extended", label: "Extended Metadata", defaultExpanded: false },
];

function classifyTag(tag: FileTag): TagGroupId {
  if (tag.key.startsWith("nom:")) {
    return tag.key.includes("_essentia") ? "rawHeads" : "nomarr";
  }
  return METADATA_WHITELIST.has(tag.key) ? "metadata" : "extended";
}

function groupTags(tags: FileTag[]): TagGroup[] {
  const buckets: Record<TagGroupId, FileTag[]> = {
    metadata: [],
    nomarr: [],
    rawHeads: [],
    extended: [],
  };

  for (const tag of tags) {
    buckets[classifyTag(tag)].push(tag);
  }

  // Sort each bucket alphabetically by key
  for (const bucket of Object.values(buckets)) {
    bucket.sort((a, b) => a.key.localeCompare(b.key));
  }

  return GROUP_DEFS.map((def) => ({ ...def, tags: buckets[def.id] }));
}

// ──────────────────────────────────────────────────────────────────────
// Value Display
// ──────────────────────────────────────────────────────────────────────

const MAX_VALUE_LENGTH = 120;

function TagValue({ value }: { value: string }): React.JSX.Element {
  if (value.length <= MAX_VALUE_LENGTH) {
    return <Typography variant="body2">{value}</Typography>;
  }
  return (
    <Tooltip title={value} arrow>
      <Typography variant="body2" sx={{ cursor: "help" }}>
        {value.substring(0, MAX_VALUE_LENGTH) + "..."}
      </Typography>
    </Tooltip>
  );
}

// ──────────────────────────────────────────────────────────────────────
// Component
// ──────────────────────────────────────────────────────────────────────

export function FileTagsDataGrid({ tags }: FileTagsDataGridProps): React.JSX.Element {
  const [showNomarrOnly, setShowNomarrOnly] = useState(false);
  const [quickFilter, setQuickFilter] = useState("");

  const groups = useMemo(() => {
    let filtered = tags;

    // Nomarr-only toggle: keep only nom: tags
    if (showNomarrOnly) {
      filtered = filtered.filter((tag) => tag.is_nomarr);
    }

    // Quick filter: match against key or value
    if (quickFilter) {
      const lower = quickFilter.toLowerCase();
      filtered = filtered.filter(
        (tag) =>
          tag.key.toLowerCase().includes(lower) ||
          tag.value.toLowerCase().includes(lower),
      );
    }

    return groupTags(filtered);
  }, [tags, showNomarrOnly, quickFilter]);

  // Only render non-empty groups
  const visibleGroups = groups.filter((g) => g.tags.length > 0);

  return (
    <Box sx={{ mt: 2 }}>
      {/* Header with controls */}
      <Stack
        direction="row"
        spacing={2}
        alignItems="center"
        justifyContent="space-between"
        sx={{ mb: 2 }}
      >
        <Typography variant="h6" component="div">
          Tags ({tags.length})
        </Typography>

        <Stack direction="row" spacing={2} alignItems="center">
          <TextField
            size="small"
            placeholder="Filter tags..."
            value={quickFilter}
            onChange={(e) => setQuickFilter(e.target.value)}
            sx={{ width: 250 }}
          />

          <FormControlLabel
            control={
              <Switch
                checked={showNomarrOnly}
                onChange={(e) => setShowNomarrOnly(e.target.checked)}
                size="small"
              />
            }
            label="Nomarr only"
          />
        </Stack>
      </Stack>

      {/* Tag Groups */}
      {tags.length === 0 ? (
        <Box
          sx={{
            p: 3,
            textAlign: "center",
            color: "text.secondary",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
          }}
        >
          No tags found
        </Box>
      ) : visibleGroups.length === 0 ? (
        <Box
          sx={{
            p: 3,
            textAlign: "center",
            color: "text.secondary",
            border: 1,
            borderColor: "divider",
            borderRadius: 1,
          }}
        >
          No tags match the current filter
        </Box>
      ) : (
        <Stack spacing={0.5}>
          {visibleGroups.map((group) => (
            <Accordion
              key={group.id}
              defaultExpanded={group.defaultExpanded}
              disableGutters
              sx={{
                border: 1,
                borderColor: "divider",
                "&:before": { display: "none" },
                boxShadow: "none",
              }}
            >
              <AccordionSummary
                expandIcon={<ExpandMoreIcon />}
                sx={{
                  bgcolor: "background.paper",
                  minHeight: 40,
                  "& .MuiAccordionSummary-content": { my: 0.5 },
                }}
              >
                <Typography variant="subtitle2">
                  {group.label}
                  <Typography
                    component="span"
                    variant="subtitle2"
                    color="text.secondary"
                    sx={{ ml: 1 }}
                  >
                    ({group.tags.length})
                  </Typography>
                </Typography>
              </AccordionSummary>
              <AccordionDetails sx={{ p: 0 }}>
                <Table size="small">
                  <TableBody>
                    {group.tags.map((tag, idx) => (
                      <TableRow
                        key={`${tag.key}-${idx}`}
                        sx={{
                          "&:last-child td": { borderBottom: 0 },
                        }}
                      >
                        <TableCell
                          sx={{
                            width: "30%",
                            fontWeight: tag.is_nomarr ? 600 : 400,
                            color: tag.is_nomarr
                              ? "primary.main"
                              : "text.primary",
                            verticalAlign: "top",
                            py: 0.5,
                          }}
                        >
                          {tag.key}
                        </TableCell>
                        <TableCell sx={{ py: 0.5 }}>
                          <TagValue value={tag.value} />
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </AccordionDetails>
            </Accordion>
          ))}
        </Stack>
      )}
    </Box>
  );
}
