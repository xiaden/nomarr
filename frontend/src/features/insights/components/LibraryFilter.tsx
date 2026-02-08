/**
 * LibraryFilter - Dropdown to filter analytics by library.
 */

import {
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  type SelectChangeEvent,
} from "@mui/material";
import { useEffect, useState } from "react";

import { list as listLibraries } from "../../../shared/api/library";
import type { Library } from "../../../shared/types";

interface LibraryFilterProps {
  /** Currently selected library ID */
  value: string | undefined;
  /** Callback when selection changes */
  onChange: (libraryId: string | undefined) => void;
}

export function LibraryFilter({ value, onChange }: LibraryFilterProps) {
  const [libraries, setLibraries] = useState<Library[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const loadLibraries = async () => {
      try {
        const result = await listLibraries(true); // enabled only
        setLibraries(result);
      } catch (err) {
        console.error("[LibraryFilter] Failed to load libraries:", err);
      } finally {
        setLoading(false);
      }
    };

    loadLibraries();
  }, []);

  const handleChange = (event: SelectChangeEvent<string>) => {
    const newValue = event.target.value;
    onChange(newValue === "" ? undefined : newValue);
  };

  return (
    <FormControl size="small" sx={{ minWidth: 200 }}>
      <InputLabel id="library-filter-label">Library</InputLabel>
      <Select
        labelId="library-filter-label"
        id="library-filter"
        value={value ?? ""}
        label="Library"
        onChange={handleChange}
        disabled={loading}
      >
        <MenuItem value="">All Libraries</MenuItem>
        {libraries.map((lib) => (
          <MenuItem key={lib.library_id} value={lib.library_id}>
            {lib.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
