/**
 * Interactive playlist match table.
 *
 * Shows all matched tracks with controls to remove tracks,
 * pick alternative matches for ambiguous entries, search for
 * manual matches, add tracks, and generate a curated M3U file.
 */

import {
  Add,
  CheckCircle,
  Close,
  Download,
  ExpandLess,
  ExpandMore,
  HelpOutline,
  RadioButtonChecked,
  RadioButtonUnchecked,
  Search,
  Undo,
} from "@mui/icons-material";
import {
  Box,
  Button,
  Chip,
  Collapse,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useMemo, useState } from "react";

import type {
  ConvertPlaylistResponse,
  MatchedFileInfoResponse,
  MatchResultResponse,
  MatchStatus,
  MatchTier,
} from "../../shared/api/playlistImport";
import { statusToTier } from "../../shared/api/playlistImport";

import { TrackSearchDialog } from "./TrackSearchDialog";

// Color mapping for match tiers
const tierColors: Record<MatchTier, "success" | "info" | "warning" | "error" | "default"> = {
  isrc: "success",
  exact: "success",
  fuzzy_high: "info",
  fuzzy_low: "warning",
  none: "error",
};

const tierLabels: Record<MatchTier, string> = {
  isrc: "ISRC",
  exact: "Exact",
  fuzzy_high: "Fuzzy",
  fuzzy_low: "Ambiguous",
  none: "Not Found",
};

function statusIcon(status: MatchStatus) {
  switch (status) {
    case "exact_isrc":
    case "exact_metadata":
    case "fuzzy":
      return <CheckCircle fontSize="small" color="success" />;
    case "ambiguous":
      return <HelpOutline fontSize="small" color="warning" />;
    case "not_found":
      return <Close fontSize="small" color="error" />;
  }
}

/** Format file info as displayable text. */
function fileLabel(file: MatchedFileInfoResponse | null): string {
  if (!file) return "\u2014";
  const parts = [file.title || "Unknown"];
  if (file.artist) parts.push(file.artist);
  return parts.join(" \u2014 ");
}

// -------------------------------------------------------------------
// Types for local editor state
// -------------------------------------------------------------------

interface TrackEdit {
  /** If set, overrides the matched file for this track. */
  selectedFile: MatchedFileInfoResponse | null;
  /** Whether the user explicitly removed this track. */
  removed: boolean;
}

// -------------------------------------------------------------------
// Component
// -------------------------------------------------------------------

interface PlaylistMatchTableProps {
  result: ConvertPlaylistResponse;
}

export function PlaylistMatchTable({ result }: PlaylistMatchTableProps) {
  // Local mutable list — starts from backend results, can grow via "Add Track"
  const [matches, setMatches] = useState<MatchResultResponse[]>(result.all_matches);

  // Local edit state keyed by position (index in matches)
  const [edits, setEdits] = useState<Record<number, TrackEdit>>({});
  // Which rows are expanded (for ambiguous alternatives)
  const [expanded, setExpanded] = useState<Record<number, boolean>>({});

  // Search dialog state
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTarget, setSearchTarget] = useState<{ idx: number; mode: "pick" | "add" } | null>(null);
  const [searchInitialQuery, setSearchInitialQuery] = useState("");

  // ---- helpers ----

  const getEdit = useCallback(
    (idx: number): TrackEdit => edits[idx] ?? { selectedFile: null, removed: false },
    [edits],
  );

  const setEdit = useCallback((idx: number, patch: Partial<TrackEdit>) => {
    setEdits((prev) => ({
      ...prev,
      [idx]: { ...(prev[idx] ?? { selectedFile: null, removed: false }), ...patch },
    }));
  }, []);

  const toggleExpand = useCallback((idx: number) => {
    setExpanded((prev) => ({ ...prev, [idx]: !prev[idx] }));
  }, []);

  // Effective file for a row (user override or original)
  const effectiveFile = useCallback(
    (idx: number, match: MatchResultResponse): MatchedFileInfoResponse | null => {
      const edit = getEdit(idx);
      if (edit.selectedFile !== null) return edit.selectedFile;
      return match.matched_file;
    },
    [getEdit],
  );

  // ---- Search dialog handlers ----

  const openSearchForRow = useCallback((idx: number) => {
    setSearchTarget({ idx, mode: "pick" });
    setSearchInitialQuery("");
    setSearchOpen(true);
  }, []);

  const openSearchForAdd = useCallback(() => {
    setSearchTarget({ idx: -1, mode: "add" });
    setSearchInitialQuery("");
    setSearchOpen(true);
  }, []);

  const handleSearchSelect = useCallback(
    (file: MatchedFileInfoResponse) => {
      if (!searchTarget) return;
      if (searchTarget.mode === "pick") {
        setEdit(searchTarget.idx, { selectedFile: file });
      } else {
        // Add mode: append a synthetic match entry
        const newMatch: MatchResultResponse = {
          input_track: {
            title: file.title,
            artist: file.artist,
            album: file.album,
            isrc: null,
            position: matches.length,
          },
          status: "exact_metadata",
          confidence: 1.0,
          matched_file: file,
          alternatives: [],
        };
        setMatches((prev) => [...prev, newMatch]);
      }
    },
    [searchTarget, setEdit, matches.length],
  );

  // ---- M3U generation ----

  const generateM3U = useCallback(() => {
    const lines: string[] = ["#EXTM3U", `#PLAYLIST:${result.playlist_metadata.name}`];

    for (let i = 0; i < matches.length; i++) {
      const match = matches[i];
      const edit = getEdit(i);
      if (edit.removed) continue;

      const file = effectiveFile(i, match);
      if (!file) continue; // skip not-found without override

      const artist = file.artist || match.input_track.artist;
      const title = file.title || match.input_track.title;
      lines.push(`#EXTINF:-1,${artist} - ${title}`);
      lines.push(file.path);
    }

    const blob = new Blob([lines.join("\n")], { type: "audio/x-mpegurl" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${result.playlist_metadata.name}.m3u`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, [matches, getEdit, effectiveFile, result.playlist_metadata.name]);

  // ---- stats ----

  const stats = useMemo(() => {
    let included = 0;
    let removed = 0;
    let modified = 0;
    for (let i = 0; i < matches.length; i++) {
      const edit = getEdit(i);
      if (edit.removed) {
        removed++;
        continue;
      }
      const file = effectiveFile(i, matches[i]);
      if (file) included++;
      if (edit.selectedFile !== null) modified++;
    }
    return { included, removed, modified, total: matches.length };
  }, [matches, getEdit, effectiveFile]);

  // ---- render ----

  return (
    <Stack spacing={2}>
      {/* Header with stats + actions */}
      <Box sx={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Box>
          <Typography variant="h6">{result.playlist_metadata.name}</Typography>
          <Typography variant="body2" color="text.secondary">
            {stats.included} of {stats.total} tracks included
            {stats.removed > 0 && ` (${stats.removed} removed)`}
            {stats.modified > 0 && ` (${stats.modified} modified)`}
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button variant="outlined" startIcon={<Add />} onClick={openSearchForAdd}>
            Add Track
          </Button>
          <Button
            variant="contained"
            startIcon={<Download />}
            onClick={generateM3U}
            disabled={stats.included === 0}
          >
            Generate M3U
          </Button>
        </Stack>
      </Box>

      {/* Match statistics chips */}
      <Box sx={{ display: "flex", gap: 1, flexWrap: "wrap" }}>
        <Chip label={`${result.exact_matches} exact`} color="success" variant="outlined" size="small" />
        {result.fuzzy_matches > 0 && (
          <Chip label={`${result.fuzzy_matches} fuzzy`} color="info" variant="outlined" size="small" />
        )}
        {result.ambiguous_count > 0 && (
          <Chip label={`${result.ambiguous_count} ambiguous`} color="warning" variant="outlined" size="small" />
        )}
        {result.not_found_count > 0 && (
          <Chip label={`${result.not_found_count} not found`} color="error" variant="outlined" size="small" />
        )}
        <Chip label={`${Math.round(result.match_rate * 100)}% matched`} variant="outlined" size="small" />
      </Box>

      {/* Table */}
      <TableContainer sx={{ maxHeight: 600 }}>
        <Table size="small" stickyHeader>
          <TableHead>
            <TableRow>
              <TableCell sx={{ width: 40 }}>#</TableCell>
              <TableCell>Track</TableCell>
              <TableCell>Artist</TableCell>
              <TableCell>Album</TableCell>
              <TableCell sx={{ width: 110 }}>Status</TableCell>
              <TableCell>Matched File</TableCell>
              <TableCell sx={{ width: 120 }} align="right">
                Actions
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {matches.map((match, idx) => {
              const edit = getEdit(idx);
              const tier = statusToTier(match.status);
              const file = effectiveFile(idx, match);
              const hasAlternatives = match.alternatives.length > 0;
              const isExpanded = expanded[idx] ?? false;

              return (
                <>
                  {/* Main row */}
                  <TableRow
                    key={idx}
                    sx={{
                      opacity: edit.removed ? 0.4 : 1,
                      textDecoration: edit.removed ? "line-through" : "none",
                      bgcolor: edit.selectedFile !== null ? "action.selected" : undefined,
                    }}
                  >
                    <TableCell>{match.input_track.position}</TableCell>
                    <TableCell>{match.input_track.title}</TableCell>
                    <TableCell>{match.input_track.artist}</TableCell>
                    <TableCell>{match.input_track.album || "\u2014"}</TableCell>
                    <TableCell>
                      <Chip
                        icon={statusIcon(match.status)}
                        label={tierLabels[tier]}
                        color={tierColors[tier]}
                        size="small"
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell
                      sx={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
                    >
                      <Tooltip title={file ? `${file.title} \u2014 ${file.artist}${file.album ? ` (${file.album})` : ""}` : "No match"} placement="top-start">
                        <span>{fileLabel(file)}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell align="right">
                      <Box sx={{ display: "flex", justifyContent: "flex-end", gap: 0.5 }}>
                        {/* Search & Pick */}
                        <Tooltip title="Search & pick a match">
                          <IconButton size="small" onClick={() => openSearchForRow(idx)}>
                            <Search fontSize="small" />
                          </IconButton>
                        </Tooltip>
                        {/* Expand alternatives */}
                        {hasAlternatives && (
                          <Tooltip title={isExpanded ? "Collapse alternatives" : "Show alternatives"}>
                            <IconButton size="small" onClick={() => toggleExpand(idx)}>
                              {isExpanded ? <ExpandLess fontSize="small" /> : <ExpandMore fontSize="small" />}
                            </IconButton>
                          </Tooltip>
                        )}
                        {/* Remove / Restore */}
                        {edit.removed ? (
                          <Tooltip title="Restore track">
                            <IconButton size="small" onClick={() => setEdit(idx, { removed: false })}>
                              <Undo fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        ) : (
                          <Tooltip title="Remove from playlist">
                            <IconButton size="small" onClick={() => setEdit(idx, { removed: true })}>
                              <Close fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        )}
                      </Box>
                    </TableCell>
                  </TableRow>

                  {/* Expandable alternatives sub-rows */}
                  {hasAlternatives && (
                    <TableRow key={`${idx}-alt`}>
                      <TableCell colSpan={7} sx={{ py: 0, borderBottom: isExpanded ? undefined : "none" }}>
                        <Collapse in={isExpanded} timeout="auto" unmountOnExit>
                          <Box sx={{ py: 1, pl: 4 }}>
                            <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5, display: "block" }}>
                              Choose alternative match:
                            </Typography>
                            {/* Current match as option */}
                            {match.matched_file && (
                              <AlternativeRow
                                file={match.matched_file}
                                selected={file?.file_id === match.matched_file.file_id && edit.selectedFile === null}
                                onSelect={() => setEdit(idx, { selectedFile: null })}
                                label="(current)"
                              />
                            )}
                            {/* Alternative options */}
                            {match.alternatives.map((alt) => (
                              <AlternativeRow
                                key={alt.file_id}
                                file={alt}
                                selected={file?.file_id === alt.file_id}
                                onSelect={() => setEdit(idx, { selectedFile: alt })}
                              />
                            ))}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  )}
                </>
              );
            })}
          </TableBody>
        </Table>
      </TableContainer>

      {/* Search dialog */}
      <TrackSearchDialog
        open={searchOpen}
        onClose={() => setSearchOpen(false)}
        onSelect={handleSearchSelect}
        initialQuery={searchInitialQuery}
        title={searchTarget?.mode === "add" ? "Add Track from Library" : "Search & Pick Match"}
      />
    </Stack>
  );
}

// -------------------------------------------------------------------
// Sub-component: single alternative row
// -------------------------------------------------------------------

interface AlternativeRowProps {
  file: MatchedFileInfoResponse;
  selected: boolean;
  onSelect: () => void;
  label?: string;
}

function AlternativeRow({ file, selected, onSelect, label }: AlternativeRowProps) {
  return (
    <Box
      onClick={onSelect}
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1,
        py: 0.5,
        px: 1,
        cursor: "pointer",
        borderRadius: 1,
        "&:hover": { bgcolor: "action.hover" },
        bgcolor: selected ? "action.selected" : undefined,
      }}
    >
      {selected ? (
        <RadioButtonChecked fontSize="small" color="primary" />
      ) : (
        <RadioButtonUnchecked fontSize="small" color="disabled" />
      )}
      <Tooltip title={`${file.title} \u2014 ${file.artist}${file.album ? ` (${file.album})` : ""}`} placement="top-start">
        <Typography variant="body2" noWrap sx={{ maxWidth: 500 }}>
          {file.title || "Unknown"} \u2014 {file.artist || "Unknown"}
          {file.album && <em> ({file.album})</em>}
          {label && <em> {label}</em>}
        </Typography>
      </Tooltip>
    </Box>
  );
}
