/**
 * Preset selector component for axis configuration.
 * Renders toggle buttons for Genre, Mood, Year, and Manual presets.
 */

import SwapHorizIcon from "@mui/icons-material/SwapHoriz";
import {
  Box,
  IconButton,
  ToggleButton,
  ToggleButtonGroup,
  Tooltip,
  Typography,
} from "@mui/material";
import type { JSX } from "react";

import { PRESET_METADATA, type PresetId } from "./types";

const PRESET_OPTIONS: PresetId[] = ["genre", "mood", "year", "manual"];

interface PresetSelectorProps {
  /** Label for the axis (e.g., "X Axis", "Y Axis") */
  label: string;
  /** Currently selected preset */
  value: PresetId;
  /** Callback when preset changes */
  onChange: (presetId: PresetId) => void;
  /** Whether to show the swap button (only on Y axis row) */
  showSwap?: boolean;
  /** Callback for swap button */
  onSwap?: () => void;
  /** Whether loading */
  loading?: boolean;
}

export function PresetSelector({
  label,
  value,
  onChange,
  showSwap = false,
  onSwap,
  loading = false,
}: PresetSelectorProps): JSX.Element {
  const handleChange = (
    _event: React.MouseEvent<HTMLElement>,
    newValue: PresetId | null
  ) => {
    if (newValue !== null) {
      onChange(newValue);
    }
  };

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
      <Typography
        variant="body2"
        sx={{ fontWeight: 500, minWidth: 60 }}
      >
        {label}
      </Typography>

      <ToggleButtonGroup
        value={value}
        exclusive
        onChange={handleChange}
        size="small"
        disabled={loading}
        sx={{ flexGrow: 1 }}
      >
        {PRESET_OPTIONS.map((presetId) => {
          const preset = PRESET_METADATA[presetId];
          return (
            <ToggleButton
              key={presetId}
              value={presetId}
              sx={{ px: 2, py: 0.5, textTransform: "none" }}
            >
              <Tooltip title={preset.description} arrow>
                <span>{preset.label}</span>
              </Tooltip>
            </ToggleButton>
          );
        })}
      </ToggleButtonGroup>

      {showSwap && (
        <Tooltip title="Swap X and Y axes" arrow>
          <IconButton
            onClick={onSwap}
            size="small"
            disabled={loading}
            sx={{ ml: 1 }}
          >
            <SwapHorizIcon />
          </IconButton>
        </Tooltip>
      )}
    </Box>
  );
}
