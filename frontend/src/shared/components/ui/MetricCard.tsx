/**
 * MetricCard - Display a labeled metric/stat value
 * Used for library stats, calibration status, etc.
 */

import type { BoxProps } from "@mui/material";
import { Box, Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface MetricCardProps extends Omit<BoxProps, "children"> {
  label: ReactNode;
  value: ReactNode;
  valueColor?: string;
  valueVariant?: "h4" | "h5" | "h6";
  centered?: boolean;
}

export function MetricCard({
  label,
  value,
  valueColor = "primary.main",
  valueVariant = "h4",
  centered = false,
  ...props
}: MetricCardProps) {
  return (
    <Box
      {...props}
      sx={{
        bgcolor: "background.default",
        p: 2,
        borderRadius: 1,
        border: 1,
        borderColor: "divider",
        ...(centered && { textAlign: "center" }),
        ...props.sx,
      }}
    >
      <Typography variant="body2" color="text.secondary" sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      <Typography
        variant={valueVariant}
        sx={{
          fontWeight: "bold",
          color: valueColor,
        }}
      >
        {value}
      </Typography>
    </Box>
  );
}
