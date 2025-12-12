/**
 * ResponsiveGrid - Responsive grid layout for metric cards and content
 * Uses CSS Grid with auto-fit columns
 */

import type { BoxProps } from "@mui/material";
import { Box } from "@mui/material";
import type { ReactNode } from "react";

export interface ResponsiveGridProps extends Omit<BoxProps, "children"> {
  children: ReactNode;
  minColumnWidth?: number;
  gap?: number;
}

export function ResponsiveGrid({
  children,
  minColumnWidth = 200,
  gap = 2,
  ...props
}: ResponsiveGridProps) {
  return (
    <Box
      {...props}
      sx={{
        display: "grid",
        gridTemplateColumns: `repeat(auto-fit, minmax(${minColumnWidth}px, 1fr))`,
        gap,
        ...props.sx,
      }}
    >
      {children}
    </Box>
  );
}
