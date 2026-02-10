/**
 * Preview table — renders playlist preview results as a formatted table
 * with Title, Artist, Album columns and a total count badge.
 */

import {
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

import type { PlaylistPreviewResponse } from "@shared/api/navidrome";

interface PreviewTableProps {
  data: PlaylistPreviewResponse;
}

export function PreviewTable({ data }: PreviewTableProps) {
  const { total_count, sample_tracks } = data;

  return (
    <Stack spacing={1.5}>
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="body2" color="text.secondary">
          Matching tracks
        </Typography>
        <Chip label={total_count} size="small" color="primary" />
      </Stack>

      {sample_tracks.length > 0 ? (
        <TableContainer>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Title</TableCell>
                <TableCell>Artist</TableCell>
                <TableCell>Album</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sample_tracks.map((track, i) => (
                <TableRow key={i}>
                  <TableCell>{track.title ?? "—"}</TableCell>
                  <TableCell>{track.artist ?? "—"}</TableCell>
                  <TableCell>{track.album ?? "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography variant="body2" color="text.secondary">
          No tracks match the current rules.
        </Typography>
      )}

      {sample_tracks.length > 0 && sample_tracks.length < total_count && (
        <Typography variant="caption" color="text.secondary">
          Showing {sample_tracks.length} of {total_count} matches
        </Typography>
      )}
    </Stack>
  );
}
