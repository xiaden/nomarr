/**
 * PipelineStateBadge component.
 * Displays the current pipeline state for a library.
 */
import { Chip } from "@mui/material";

interface PipelineStateBadgeProps {
  state: string;
}

interface PipelineStateConfig {
  label: string;
  color: "default" | "primary" | "secondary" | "error" | "info" | "success" | "warning";
  sx?: Record<string, unknown>;
}

const PIPELINE_STATE_CONFIG: Record<string, PipelineStateConfig> = {
  idle: {
    label: "Idle",
    color: "default",
  },
  scanning: {
    label: "Scanning",
    color: "info",
  },
  ml_running: {
    label: "ML running",
    color: "info",
  },
  too_small: {
    label: "Too small",
    color: "warning",
  },
  awaiting_calibration: {
    label: "Awaiting calibration",
    color: "info",
  },
  calibrating: {
    label: "Calibrating",
    color: "info",
  },
  applying: {
    label: "Applying",
    color: "info",
  },
  write_ready: {
    label: "Write ready",
    color: "warning",
    sx: {
      bgcolor: "warning.light",
      color: "warning.contrastText",
    },
  },
  writing: {
    label: "Writing",
    color: "info",
  },
  done: {
    label: "Done",
    color: "success",
  },
};

function formatUnknownStateLabel(state: string): string {
  if (!state) {
    return "Unknown";
  }

  return state
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

export function PipelineStateBadge({ state }: PipelineStateBadgeProps) {
  const config = PIPELINE_STATE_CONFIG[state] ?? {
    label: formatUnknownStateLabel(state),
    color: "default",
  };

  return (
    <Chip
      label={config.label}
      size="small"
      color={config.color}
      sx={config.sx}
      data-testid="pipeline-state-badge"
    />
  );
}