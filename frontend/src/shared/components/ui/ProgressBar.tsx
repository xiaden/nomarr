/**
 * ProgressBar - Visual progress bar with label and percentage
 * Used for mood distribution, tag frequencies, etc.
 */

import type { BoxProps } from "@mui/material";
import { Box, Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface ProgressBarProps extends Omit<BoxProps, "children"> {
  label: ReactNode;
  value: number;
  total?: number;
  percentage?: number;
  barColor?: string;
  barOpacity?: number;
}

export function ProgressBar({
  label,
  value,
  total,
  percentage,
  barColor = "primary.main",
  barOpacity = 0.2,
  ...props
}: ProgressBarProps) {
  const calculatedPercentage = percentage ?? (total ? (value / total) * 100 : 0);

  return (
    <Box
      {...props}
      sx={{
        position: "relative",
        display: "flex",
        justifyContent: "space-between",
        p: 1.25,
        bgcolor: "background.default",
        borderRadius: 1,
        overflow: "hidden",
        ...props.sx,
      }}
    >
      <Typography component="span" sx={{ zIndex: 1, position: "relative" }}>
        {label}
      </Typography>
      <Typography
        component="span"
        sx={{
          zIndex: 1,
          position: "relative",
          color: "text.secondary",
        }}
      >
        {value} ({calculatedPercentage.toFixed(1)}%)
      </Typography>
      <Box
        sx={{
          position: "absolute",
          top: 0,
          left: 0,
          height: "100%",
          width: `${calculatedPercentage}%`,
          bgcolor: barColor,
          opacity: barOpacity,
          transition: "width 0.3s ease",
        }}
      />
    </Box>
  );
}
