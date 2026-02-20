/**
 * LibraryStats - Display library aggregate statistics.
 *
 * Shows file count, total duration, file size, average track length.
 */

import { Box, Typography } from "@mui/material";

import { AccordionSubsection } from "@shared/components/ui";
import { formatTotalDuration, formatTrackDuration } from "@shared/utils/format";

import type { LibraryStats as LibraryStatsType } from "../../../shared/api/analytics";


interface LibraryStatsProps {
  stats: LibraryStatsType;
  parentId: string;
}

/**
 * Format bytes to human-readable string.
 */
function formatBytes(bytes: number): string {
  if (bytes >= 1e12) {
    return `${(bytes / 1e12).toFixed(1)} TB`;
  }
  if (bytes >= 1e9) {
    return `${(bytes / 1e9).toFixed(1)} GB`;
  }
  if (bytes >= 1e6) {
    return `${(bytes / 1e6).toFixed(1)} MB`;
  }
  return `${(bytes / 1e3).toFixed(1)} KB`;
}

interface StatItemProps {
  label: string;
  value: string;
}

function StatItem({ label, value }: StatItemProps) {
  return (
    <Box sx={{ textAlign: "center", py: 1, flex: "1 1 25%", minWidth: 100 }}>
      <Typography variant="h5" color="primary">
        {value}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
    </Box>
  );
}

export function LibraryStats({ stats, parentId }: LibraryStatsProps) {
  return (
    <AccordionSubsection
      subsectionId="stats"
      parentId={parentId}
      title="Library Statistics"
    >
      <Box sx={{ display: "flex", flexWrap: "wrap", gap: 2 }}>
        <StatItem label="Tracks" value={stats.file_count.toLocaleString()} />
        <StatItem
          label="Total Duration"
          value={formatTotalDuration(stats.total_duration_ms / 1000)}
        />
        <StatItem
          label="Total Size"
          value={formatBytes(stats.total_file_size_bytes)}
        />
        <StatItem
          label="Avg Track"
          value={formatTrackDuration(stats.avg_track_length_ms / 1000)}
        />
      </Box>
    </AccordionSubsection>
  );
}
