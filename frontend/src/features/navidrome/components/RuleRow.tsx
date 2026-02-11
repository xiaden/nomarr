/**
 * A single rule row in the playlist rule builder.
 *
 * Renders tag select (grouped by type with labels), operator select (context-sensitive),
 * value combobox (autocomplete from DB values + free text), and remove button.
 */

import CloseIcon from "@mui/icons-material/Close";
import {
  Autocomplete,
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
import { useCallback, useEffect, useState } from "react";

import { getTagValues } from "@shared/api/navidrome";

import type { TagMetaEntry } from "../hooks/useTagMetadata";

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
] as const;

const STRING_OPERATORS = [
  { value: "contains", label: "contains" },
  { value: "notcontains", label: "not contains" },
  { value: "=", label: "=" },
  { value: "!=", label: "\u2260" },
] as const;

interface RuleRowProps {
  rule: Rule;
  numericTags: TagMetaEntry[];
  stringTags: TagMetaEntry[];
  onChange: (updated: Rule) => void;
  onRemove: () => void;
  onMoveToGroup?: (ruleId: string, targetGroupId: string) => void; // Future: drag-and-drop
}

export function RuleRow({
  rule,
  numericTags,
  stringTags,
  onChange,
  onRemove,
}: RuleRowProps) {
  const allTags = [...numericTags, ...stringTags];

  // Determine if the selected tag is numeric
  const selectedTag = allTags.find((t) => t.key === rule.tagKey);
  const isNumeric =
    selectedTag?.type === "float" || selectedTag?.type === "integer";
  const operators = isNumeric ? NUMERIC_OPERATORS : STRING_OPERATORS;

  // Fetch distinct values for the selected tag
  const [tagOptions, setTagOptions] = useState<string[]>([]);
  const [optionsLoading, setOptionsLoading] = useState(false);

  const fetchValues = useCallback(async (tagKey: string) => {
    if (!tagKey) {
      setTagOptions([]);
      return;
    }
    try {
      setOptionsLoading(true);
      const values = await getTagValues(tagKey);
      setTagOptions(values);
    } catch {
      setTagOptions([]);
    } finally {
      setOptionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchValues(rule.tagKey);
  }, [rule.tagKey, fetchValues]);

  const handleTagChange = (e: SelectChangeEvent) => {
    const newKey = e.target.value;
    const newTag = allTags.find((t) => t.key === newKey);
    const wasNumeric = isNumeric;
    const nowNumeric =
      newTag?.type === "float" || newTag?.type === "integer";

    // Reset operator if switching between numeric/string
    const keepOperator =
      wasNumeric === nowNumeric &&
      operators.some((op) => op.value === rule.operator);

    // Default operator: "=" for numeric, "contains" for string
    const defaultOp = nowNumeric ? "=" : "contains";

    onChange({
      ...rule,
      tagKey: newKey,
      operator: keepOperator ? rule.operator : defaultOp,
      value: wasNumeric !== nowNumeric ? "" : rule.value,
    });
  };

  const handleOperatorChange = (e: SelectChangeEvent) => {
    onChange({ ...rule, operator: e.target.value });
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center">
      {/* Tag selector */}
      <FormControl size="small" sx={{ minWidth: 180, flex: 2 }}>
        <InputLabel>Tag</InputLabel>
        <Select
          value={rule.tagKey}
          label="Tag"
          onChange={handleTagChange}
        >
          {numericTags.length > 0 && (
            <ListSubheader>Numeric</ListSubheader>
          )}
          {numericTags.map((tag) => (
            <MenuItem key={tag.key} value={tag.key}>
              {tag.label}
            </MenuItem>
          ))}
          {stringTags.length > 0 && (
            <ListSubheader>Text</ListSubheader>
          )}
          {stringTags.map((tag) => (
            <MenuItem key={tag.key} value={tag.key}>
              {tag.label}
            </MenuItem>
          ))}
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

      {/* Value combobox */}
      <Autocomplete
        size="small"
        freeSolo
        options={tagOptions}
        loading={optionsLoading}
        value={rule.value || null}
        inputValue={rule.value}
        onInputChange={(_, newValue) => {
          onChange({ ...rule, value: newValue });
        }}
        onChange={(_, newValue) => {
          onChange({ ...rule, value: newValue ?? "" });
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            label="Value"
            type={isNumeric ? "number" : "text"}
            inputProps={{
              ...params.inputProps,
              ...(isNumeric ? { step: "any" } : {}),
            }}
          />
        )}
        sx={{ flex: 2, minWidth: 160 }}
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
