/**
 * Sort picker — dropdown of valid sort columns with asc/desc toggle.
 * Returns a formatted sort string (e.g. "-artist") for the backend.
 */

import ArrowDownwardIcon from "@mui/icons-material/ArrowDownward";
import ArrowUpwardIcon from "@mui/icons-material/ArrowUpward";
import {
  FormControl,
  IconButton,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Tooltip,
  type SelectChangeEvent,
} from "@mui/material";

const SORT_COLUMNS = [
  { value: "title", label: "Title" },
  { value: "artist", label: "Artist" },
  { value: "album", label: "Album" },
  { value: "path", label: "Path" },
  { value: "random", label: "Random" },
] as const;

interface SortPickerProps {
  value: string;
  onChange: (value: string) => void;
}

/** Parse a sort string ("-artist") into column + direction. */
function parseSortValue(value: string): {
  column: string;
  descending: boolean;
} {
  if (value.startsWith("-")) {
    return { column: value.slice(1), descending: true };
  }
  return { column: value || "title", descending: false };
}

export function SortPicker({ value, onChange }: SortPickerProps) {
  const { column, descending } = parseSortValue(value);

  const handleColumnChange = (e: SelectChangeEvent) => {
    const col = e.target.value;
    onChange(descending ? `-${col}` : col);
  };

  const toggleDirection = () => {
    onChange(descending ? column : `-${column}`);
  };

  return (
    <Stack direction="row" spacing={1} alignItems="center">
      <FormControl size="small" sx={{ minWidth: 140 }}>
        <InputLabel>Sort by</InputLabel>
        <Select value={column} label="Sort by" onChange={handleColumnChange}>
          {SORT_COLUMNS.map((col) => (
            <MenuItem key={col.value} value={col.value}>
              {col.label}
            </MenuItem>
          ))}
        </Select>
      </FormControl>

      {column !== "random" && (
        <Tooltip title={descending ? "Descending" : "Ascending"}>
          <IconButton size="small" onClick={toggleDirection}>
            {descending ? <ArrowDownwardIcon /> : <ArrowUpwardIcon />}
          </IconButton>
        </Tooltip>
      )}
    </Stack>
  );
}
