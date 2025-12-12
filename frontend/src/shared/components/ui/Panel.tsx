/**
 * Panel - Standard container for sections/content areas
 * Wraps MUI Card with consistent padding, border, and background from theme
 */

import type { CardProps } from "@mui/material";
import { Card } from "@mui/material";
import type { ReactNode } from "react";

export interface PanelProps extends Omit<CardProps, "children"> {
  children: ReactNode;
}

export function Panel({ children, ...props }: PanelProps) {
  return (
    <Card
      {...props}
      sx={{
        p: 2.5,
        ...props.sx,
      }}
    >
      {children}
    </Card>
  );
}
