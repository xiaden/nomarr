/**
 * A single rule row in the playlist rule builder.
 *
 * Renders tag select (grouped by type), operator select (context-sensitive),
 * value input (number for numeric tags, text for string), and remove button.
 */

import CloseIcon from "@mui/icons-material/Close";
import {
  FormControl,
  IconButton,
  InputLabel,
  ListSubheader,
  MenuItem,
  Select,
  Stack,
  TextField,
  Tooltip,
  type SelectChangeEvent,
} from "@mui/material";

import type { TagStatEntry } from "@shared/api/navidrome";

export interface Rule {
  id: string;
  tagKey: string;
  operator: string;
  value: string;
}

const NUMERIC_OPERATORS = [
  { value: "=", label: "=" },
  { value: "!=", label: "\u2260" },
  { value: ">", label: ">" },
  { value: "<", label: "<" },
  { value: ">=", label: "\u2265" },
  { value: "<=", label: "\u2264" },
] as const;

const STRING_OPERATORS = [
  { value: "=", label: "=" },
  { value: "!=", label: "\u2260" },
  { value: "contains", label: "contains" },
] as const;

/** Extract hint text from tag summary, e.g. "min=0, max=100, unique=5" → "0 – 100" */
function rangeHint(tag: TagStatEntry): string {
  if (tag.type === "string") {
    const m = tag.summary.match(/unique=(\d+)/);
    return m ? `${m[1]} values` : "";
  }
  const minMatch = tag.summary.match(/min=([\d.]+)/);
  const maxMatch = tag.summary.match(/max=([\d.]+)/);
  if (minMatch && maxMatch) return `${minMatch[1]} – ${maxMatch[1]}`;
  return "";
}

interface RuleRowProps {
  rule: Rule;
  numericTags: TagStatEntry[];
  stringTags: TagStatEntry[];
  onChange: (updated: Rule) => void;
  onRemove: () => void;
}

export function RuleRow({
  rule,
  numericTags,
  stringTags,
  onChange,
  onRemove,
}: RuleRowProps) {
  // Determine if the selected tag is numeric
  const selectedTag = [...numericTags, ...stringTags].find(
    (t) => t.key === rule.tagKey,
  );
  const isNumeric =
    selectedTag?.type === "float" || selectedTag?.type === "integer";
  const operators = isNumeric ? NUMERIC_OPERATORS : STRING_OPERATORS;

  const handleTagChange = (e: SelectChangeEvent) => {
    const newKey = e.target.value;
    const newTag = [...numericTags, ...stringTags].find(
      (t) => t.key === newKey,
    );
    const wasNumeric = isNumeric;
    const nowNumeric =
      newTag?.type === "float" || newTag?.type === "integer";

    // Reset operator if switching between numeric/string
    const keepOperator =
      wasNumeric === nowNumeric &&
      operators.some((op) => op.value === rule.operator);

    onChange({
      ...rule,
      tagKey: newKey,
      operator: keepOperator ? rule.operator : "=",
      value: wasNumeric !== nowNumeric ? "" : rule.value,
    });
  };

  const handleOperatorChange = (e: SelectChangeEvent) => {
    onChange({ ...rule, operator: e.target.value });
  };

  const handleValueChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({ ...rule, value: e.target.value });
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {/* Tag selector */}
      <FormControl size="small" sx={{ minWidth: 200, flex: 2 }}>
        <InputLabel>Tag</InputLabel>
        <Select
          value={rule.tagKey}
          label="Tag"
          onChange={handleTagChange}
        >
          {numericTags.length > 0 && (
            <ListSubheader>Numeric</ListSubheader>
          )}
          {numericTags.map((tag) => {
            const hint = rangeHint(tag);
            return (
              <MenuItem key={tag.key} value={tag.key}>
                {tag.key}{hint && ` (${hint})`}
              </MenuItem>
            );
          })}
          {stringTags.length > 0 && (
            <ListSubheader>Text</ListSubheader>
          )}
          {stringTags.map((tag) => {
            const hint = rangeHint(tag);
            return (
              <MenuItem key={tag.key} value={tag.key}>
                {tag.key}{hint && ` (${hint})`}
              </MenuItem>
            );
          })}
        </Select>
      </FormControl>

      {/* Operator selector */}
      <FormControl size="small" sx={{ minWidth: 90, flex: 0 }}>
        <InputLabel>Op</InputLabel>
        <Select
          value={rule.operator}
          label="Op"
          onChange={handleOperatorChange}
        >
          {operators.map((op) => (
            <MenuItem key={op.value} value={op.value}>
              {op.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {/* Value input */}
      <TextField
        size="small"
        label="Value"
        type={isNumeric ? "number" : "text"}
        value={rule.value}
        onChange={handleValueChange}
        slotProps={isNumeric ? { htmlInput: { step: "any" } } : undefined}
        sx={{ flex: 2 }}
      />

      {/* Remove button */}
      <Tooltip title="Remove rule">
        <IconButton size="small" onClick={onRemove} color="error">
          <CloseIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    </Stack>
  );
}
