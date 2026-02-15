/**
 * Color legend explaining the heatmap gradient scale.
 */

import { Box, Typography } from "@mui/material";
import type { JSX } from "react";

interface ColorLegendProps {
  /** Maximum value in the matrix */
  maxValue: number;
}

export function ColorLegend({ maxValue }: ColorLegendProps): JSX.Element {
  return (
    <Box
      sx={{
        mt: 2,
        pt: 2,
        borderTop: 1,
        borderColor: "divider",
        display: "flex",
        flexDirection: "column",
        gap: 0.5,
      }}
    >
      <Typography variant="caption" color="text.secondary">
        Files matching both tags
      </Typography>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1 }}>
        <Box
          sx={{
            width: 200,
            height: 12,
            background: `linear-gradient(to right, #1a1a1a, rgb(74, 158, 255))`,
            borderRadius: 1,
            border: 1,
            borderColor: "divider",
          }}
        />
        <Box
          sx={{
            display: "flex",
            justifyContent: "space-between",
            width: 60,
            fontSize: "0.75rem",
            color: "text.secondary",
          }}
        >
          <span>0</span>
          <span>{maxValue}</span>
        </Box>
      </Box>
    </Box>
  );
}
