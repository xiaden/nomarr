/**
 * ErrorMessage - Consistent error display component
 */

import type { TypographyProps } from "@mui/material";
import { Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface ErrorMessageProps extends Omit<TypographyProps, "children"> {
  children: ReactNode;
}

export function ErrorMessage({ children, ...props }: ErrorMessageProps) {
  return (
    <Typography
      {...props}
      color="error"
      sx={{
        mb: 2,
        ...props.sx,
      }}
    >
      {children}
    </Typography>
  );
}
