/**
 * SectionHeader - Standard section title with optional subtitle
 * Uses Typography with consistent spacing
 */

import type { TypographyProps } from "@mui/material";
import { Box, Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface SectionHeaderProps {
  title: ReactNode;
  subtitle?: ReactNode;
  titleVariant?: TypographyProps["variant"];
  action?: ReactNode;
}

export function SectionHeader({
  title,
  subtitle,
  titleVariant = "h6",
  action,
}: SectionHeaderProps) {
  return (
    <Box sx={{ mb: 2, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <Box>
        <Typography variant={titleVariant}>{title}</Typography>
        {subtitle && (
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
            {subtitle}
          </Typography>
        )}
      </Box>
      {action && <Box>{action}</Box>}
    </Box>
  );
}
