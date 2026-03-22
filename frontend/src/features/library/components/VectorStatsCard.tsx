import { Box, Chip, Typography } from "@mui/material";

import type { LibraryVectorStatsResponse } from "../../../shared/api/library";

interface VectorStatsCardProps {
  stats: LibraryVectorStatsResponse;
}

export function VectorStatsCard({ stats }: VectorStatsCardProps) {
  if (stats.stats.length === 0) {
    return (
      <Box sx={{ mt: 2 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
          Vector Statistics
        </Typography>
        <Typography variant="body2" color="text.secondary">
          No vector data available. Vectors are created during ML processing.
        </Typography>
      </Box>
    );
  }

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
        Vector Statistics
      </Typography>
      {stats.stats.map((s) => (
        <Box key={s.backbone_id} sx={{ display: "flex", alignItems: "center", gap: 1, mb: 0.5 }}>
          <Typography variant="body2" sx={{ minWidth: 80, fontWeight: 500 }}>
            {s.backbone_id}
          </Typography>
          <Chip
            label={`Hot: ${s.hot_count}`}
            size="small"
            color={s.hot_count > 0 ? "warning" : "default"}
          />
          <Chip label={`Cold: ${s.cold_count}`} size="small" color="primary" />
          <Chip
            label={s.index_exists ? "Index ready" : "No index"}
            size="small"
            color={s.index_exists ? "success" : "default"}
          />
        </Box>
      ))}
    </Box>
  );
}
