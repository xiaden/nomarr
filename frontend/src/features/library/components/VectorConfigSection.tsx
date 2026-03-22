import { Box, FormControlLabel, Slider, Switch, Typography } from "@mui/material";
import { useCallback } from "react";

import type { VectorConfigResponse, VectorConfigUpdate } from "../../../shared/api/library";

import { VectorConfigExplainer } from "./VectorConfigExplainer";

interface VectorConfigSectionProps {
  config: VectorConfigResponse;
  totalTracks: number;
  onUpdate: (update: VectorConfigUpdate) => void;
  disabled?: boolean;
}

export function VectorConfigSection({
  config,
  totalTracks,
  onUpdate,
  disabled = false,
}: VectorConfigSectionProps) {
  const isUsingGlobalDefaults = config.is_group_size_inherited && config.is_thoroughness_inherited;

  const handleToggleGlobal = useCallback(
    (_: React.ChangeEvent<HTMLInputElement>, checked: boolean) => {
      if (checked) {
        // Clear overrides → inherit global
        onUpdate({ vector_group_size: null, vector_search_thoroughness: null });
      } else {
        // Start overriding with current effective values
        onUpdate({
          vector_group_size: config.vector_group_size,
          vector_search_thoroughness: config.vector_search_thoroughness,
        });
      }
    },
    [config, onUpdate],
  );

  const handleGroupSizeChange = useCallback(
    (_: Event, value: number | number[]) => {
      const v = Array.isArray(value) ? value[0] : value;
      onUpdate({
        vector_group_size: v,
        vector_search_thoroughness: config.is_thoroughness_inherited
          ? null
          : config.vector_search_thoroughness,
      });
    },
    [config, onUpdate],
  );

  const handleThoroughnessChange = useCallback(
    (_: Event, value: number | number[]) => {
      const v = Array.isArray(value) ? value[0] : value;
      onUpdate({
        vector_group_size: config.is_group_size_inherited ? null : config.vector_group_size,
        vector_search_thoroughness: v,
      });
    },
    [config, onUpdate],
  );

  return (
    <Box sx={{ mt: 2 }}>
      <Typography variant="subtitle1" sx={{ mb: 1, fontWeight: 600 }}>
        Vector Search Configuration
      </Typography>

      <FormControlLabel
        control={
          <Switch checked={isUsingGlobalDefaults} onChange={handleToggleGlobal} disabled={disabled} />
        }
        label="Use global defaults"
      />

      <Box sx={{ mt: 2, opacity: isUsingGlobalDefaults ? 0.5 : 1 }}>
        <Typography variant="body2" gutterBottom>
          Songs per Neighborhood: <strong>{config.vector_group_size}</strong>
        </Typography>
        <Slider
          value={config.vector_group_size}
          min={5}
          max={100}
          step={5}
          onChange={handleGroupSizeChange}
          disabled={disabled || isUsingGlobalDefaults}
          valueLabelDisplay="auto"
          sx={{ maxWidth: 400 }}
        />

        <Typography variant="body2" gutterBottom sx={{ mt: 2 }}>
          Search Thoroughness: <strong>{config.vector_search_thoroughness}%</strong>
        </Typography>
        <Slider
          value={config.vector_search_thoroughness}
          min={1}
          max={50}
          step={1}
          onChange={handleThoroughnessChange}
          disabled={disabled || isUsingGlobalDefaults}
          valueLabelDisplay="auto"
          sx={{ maxWidth: 400 }}
        />
      </Box>

      <VectorConfigExplainer
        totalTracks={totalTracks}
        groupSize={config.vector_group_size}
        thoroughness={config.vector_search_thoroughness}
      />
    </Box>
  );
}
