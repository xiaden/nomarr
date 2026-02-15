/**
 * Individual heatmap cell with tooltip.
 */

import { Box, Tooltip, Typography } from "@mui/material";
import type { JSX } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";

interface HeatmapCellProps {
  /** X-axis tag */
  xTag: TagSpec;
  /** Y-axis tag */
  yTag: TagSpec;
  /** Co-occurrence count */
  count: number;
  /** Maximum count in matrix */
  maxCount: number;
  /** Background color */
  bgcolor: string;
}

export function HeatmapCell({
  xTag,
  yTag,
  count,
  maxCount,
  bgcolor,
}: HeatmapCellProps): JSX.Element {
  const percentage = Math.round((count / maxCount) * 100);

  const tooltipContent = (
    <Box sx={{ p: 0.5 }}>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {xTag.key}: {xTag.value}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600 }}>
        {yTag.key}: {yTag.value}
      </Typography>
      <Box
        sx={{
          borderTop: 1,
          borderColor: "divider",
          mt: 0.5,
          pt: 0.5,
        }}
      >
        <Typography variant="body2">
          {count} file{count !== 1 ? "s" : ""}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {percentage}% of max ({maxCount})
        </Typography>
      </Box>
    </Box>
  );

  return (
    <Tooltip title={tooltipContent} arrow placement="top">
      <Box
        component="td"
        sx={{
          bgcolor,
          p: 1,
          textAlign: "center",
          fontWeight: count > 0 ? 600 : "normal",
          color: count > 0 ? "#fff" : "text.secondary",
          cursor: "default",
          transition: "transform 0.1s, box-shadow 0.1s",
          "&:hover": {
            transform: "scale(1.1)",
            zIndex: 10,
            boxShadow: 4,
          },
        }}
      >
        {count}
      </Box>
    </Tooltip>
  );
}
