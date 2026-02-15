import {
  Autocomplete,
  Box,
  CircularProgress,
  TextField,
  Typography,
} from "@mui/material";
import type { AutocompleteProps } from "@mui/material";
import { useCallback, useMemo, useState } from "react";

import type { LibraryFile } from "@shared/api/files";
import { search } from "@shared/api/files";

interface TrackSearchPickerProps
  extends Omit<AutocompleteProps<LibraryFile, false, false, false>, "options" | "renderInput"> {
  onTrackSelect?: (track: LibraryFile | null) => void;
  helperText?: string;
}

/**
 * TrackSearchPicker component provides fuzzy search autocomplete for library tracks.
 * Uses debounced search to find tracks by artist, album, or title.
 */
export function TrackSearchPicker({
  onTrackSelect,
  helperText = "Search by artist, album, or title",
  ...props
}: TrackSearchPickerProps) {
  const [inputValue, setInputValue] = useState("");
  const [options, setOptions] = useState<LibraryFile[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTrack, setSelectedTrack] = useState<LibraryFile | null>(null);

  /**
   * Debounced search function with 300ms delay
   */
  const searchTracks = useCallback(async (query: string) => {
    if (!query.trim()) {
      setOptions([]);
      return;
    }

    setLoading(true);
    try {
      const response = await search({ q: query.trim() });
      setOptions(response.files || []);
    } catch (error) {
      console.error("Failed to search tracks:", error);
      setOptions([]);
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Debounce search with 300ms delay
   */
  const debouncedSearch = useMemo(() => {
    let timeoutId: NodeJS.Timeout;

    return (query: string) => {
      clearTimeout(timeoutId);
      if (!query.trim()) {
        setOptions([]);
        return;
      }
      timeoutId = setTimeout(() => {
        searchTracks(query);
      }, 300);
    };
  }, [searchTracks]);

  const handleInputChange = useCallback(
    (_event: React.SyntheticEvent, value: string) => {
      setInputValue(value);
      debouncedSearch(value);
    },
    [debouncedSearch]
  );

  const handleChange = useCallback(
    (_event: React.SyntheticEvent, value: LibraryFile | null) => {
      setSelectedTrack(value);
      onTrackSelect?.(value);
    },
    [onTrackSelect]
  );

  const getOptionLabel = (option: LibraryFile): string => {
    const parts = [option.artist || "Unknown Artist", option.album || "Unknown Album", option.title || "Unknown Title"];
    return parts.filter(Boolean).join(" - ");
  };

  const isOptionEqualToValue = (option: LibraryFile, value: LibraryFile): boolean => {
    return option.file_id === value.file_id;
  };

  return (
    <Autocomplete<LibraryFile, false, false, false>
      options={options}
      loading={loading}
      inputValue={inputValue}
      onInputChange={handleInputChange}
      value={selectedTrack}
      onChange={handleChange}
      getOptionLabel={getOptionLabel}
      isOptionEqualToValue={isOptionEqualToValue}
      renderOption={(props, option) => (
        <Box component="li" {...props}>
          <Box sx={{ display: "flex", flexDirection: "column", width: "100%" }}>
            <Typography variant="body2" sx={{ fontWeight: 500 }}>
              {getOptionLabel(option)}
            </Typography>
            <Typography variant="caption" sx={{ color: "text.secondary" }}>
              {option.path}
            </Typography>
          </Box>
        </Box>
      )}
      renderInput={(params) => (
        <TextField
          {...params}
          label="Track Search"
          placeholder="Search by artist, album, or title..."
          size="small"
          helperText={helperText}
          slotProps={{
            input: {
              ...params.InputProps,
              endAdornment: (
                <>
                  {loading ? <CircularProgress color="inherit" size={20} /> : null}
                  {params.InputProps.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
      noOptionsText="No tracks found"
      {...props}
    />
  );
}
