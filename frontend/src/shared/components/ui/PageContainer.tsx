/**
 * PageContainer - Standard page wrapper with consistent padding and title
 */

import type { BoxProps } from "@mui/material";
import { Box, Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface PageContainerProps extends Omit<BoxProps, "children" | "title"> {
  children: ReactNode;
  title?: ReactNode;
}

export function PageContainer({ children, title, ...props }: PageContainerProps) {
  return (
    <Box
      {...props}
      sx={{
        p: 2.5,
        ...props.sx,
      }}
    >
      {title && (
        <Typography variant="h4" sx={{ mb: 2.5, fontWeight: 600 }}>
          {title}
        </Typography>
      )}
      {children}
    </Box>
  );
}
