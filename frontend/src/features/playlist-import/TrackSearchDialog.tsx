/**
 * Dialog for searching and picking a library file.
 *
 * Used for manual match selection and adding tracks to the playlist.
 */

import { Search } from "@mui/icons-material";
import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  InputAdornment,
  List,
  ListItemButton,
  ListItemText,
  TextField,
  Typography,
} from "@mui/material";
import { useCallback, useRef, useState } from "react";

import { search } from "../../shared/api/files";
import type { MatchedFileInfoResponse } from "../../shared/api/playlistImport";

interface TrackSearchDialogProps {
  open: boolean;
  onClose: () => void;
  onSelect: (file: MatchedFileInfoResponse) => void;
  /** Pre-fill the search query (e.g. with the track title). */
  initialQuery?: string;
  title?: string;
}

export function TrackSearchDialog({
  open,
  onClose,
  onSelect,
  initialQuery = "",
  title = "Search Library",
}: TrackSearchDialogProps) {
  const [query, setQuery] = useState(initialQuery);
  const [results, setResults] = useState<MatchedFileInfoResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState<MatchedFileInfoResponse | null>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) {
      setResults([]);
      return;
    }
    setLoading(true);
    try {
      const resp = await search({ q: q.trim(), limit: 20 });
      setResults(
        resp.files.map((f) => ({
          path: f.path,
          file_id: f.file_id,
          title: f.title ?? "",
          artist: f.artist ?? "",
          album: f.album ?? null,
        })),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  const handleQueryChange = useCallback(
    (value: string) => {
      setQuery(value);
      setSelected(null);
      if (debounceRef.current) clearTimeout(debounceRef.current);
      debounceRef.current = setTimeout(() => doSearch(value), 300);
    },
    [doSearch],
  );

  const handleConfirm = useCallback(() => {
    if (selected) {
      onSelect(selected);
      onClose();
    }
  }, [selected, onSelect, onClose]);

  // Reset state when dialog opens with new initial query
  const handleEntered = useCallback(() => {
    setQuery(initialQuery);
    setSelected(null);
    setResults([]);
    if (initialQuery) doSearch(initialQuery);
  }, [initialQuery, doSearch]);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth="sm"
      fullWidth
      TransitionProps={{ onEntered: handleEntered }}
    >
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          size="small"
          placeholder="Search by title, artist, or album..."
          value={query}
          onChange={(e) => handleQueryChange(e.target.value)}
          sx={{ mt: 1, mb: 2 }}
          slotProps={{
            input: {
              startAdornment: (
                <InputAdornment position="start">
                  <Search fontSize="small" />
                </InputAdornment>
              ),
              endAdornment: loading ? (
                <InputAdornment position="end">
                  <CircularProgress size={18} />
                </InputAdornment>
              ) : undefined,
            },
          }}
        />

        {results.length === 0 && !loading && query.trim() && (
          <Typography variant="body2" color="text.secondary" sx={{ py: 2, textAlign: "center" }}>
            No results found
          </Typography>
        )}

        <List dense sx={{ maxHeight: 300, overflow: "auto" }}>
          {results.map((file) => (
            <ListItemButton
              key={file.file_id}
              selected={selected?.file_id === file.file_id}
              onClick={() => setSelected(file)}
            >
              <ListItemText
                primary={`${file.title || "Unknown"} — ${file.artist || "Unknown"}`}
                secondary={file.album || file.path}
              />
            </ListItemButton>
          ))}
        </List>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleConfirm} disabled={!selected}>
          Select
        </Button>
      </DialogActions>
    </Dialog>
  );
}
