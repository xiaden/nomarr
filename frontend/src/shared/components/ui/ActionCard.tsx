/**
 * ActionCard - Card wrapper for action buttons with descriptions
 * Used for calibration actions, admin controls, etc.
 */

import type { ButtonProps } from "@mui/material";
import { Box, Button, Typography } from "@mui/material";
import type { ReactNode } from "react";

export interface ActionCardProps {
  label: ReactNode;
  description?: ReactNode;
  onClick: () => void | Promise<void>;
  disabled?: boolean;
  variant?: ButtonProps["variant"];
  color?: ButtonProps["color"];
  fullWidth?: boolean;
}

export function ActionCard({
  label,
  description,
  onClick,
  disabled = false,
  variant = "contained",
  color = "primary",
  fullWidth = true,
}: ActionCardProps) {
  return (
    <Box>
      <Button
        onClick={onClick}
        disabled={disabled}
        variant={variant}
        color={color}
        fullWidth={fullWidth}
        sx={{ mb: description ? 1 : 0 }}
      >
        {label}
      </Button>
      {description && (
        <Typography variant="body2" color="text.secondary">
          {description}
        </Typography>
      )}
    </Box>
  );
}
