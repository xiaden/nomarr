/**
 * ConfigField component.
 * Renders a single configuration field with appropriate input type.
 */

import { Box, MenuItem, Select, TextField, Typography } from "@mui/material";

// Human-readable labels for config keys
const CONFIG_LABELS: Record<string, string> = {
  library_root: "Library Root Directory",
  scan_recursive: "Scan Subdirectories",
  scan_ignore_patterns: "Ignore Patterns",
  tagging_enabled: "Auto-Tagging Enabled",
  tagging_version_tag_key: "Version Tag Key",
  processing_batch_size: "Processing Batch Size",
  processing_max_workers: "Max Worker Threads",
  gpu_enabled: "GPU Acceleration",
  gpu_device_id: "GPU Device ID",
  cache_size_mb: "Cache Size (MB)",
  log_level: "Log Level",
};

interface ConfigFieldProps {
  configKey: string;
  value: unknown;
  onChange: (key: string, value: string) => void;
  disabled: boolean;
}

export function ConfigField({
  configKey,
  value,
  onChange,
  disabled,
}: ConfigFieldProps) {
  const stringValue = value === null || value === undefined ? "" : String(value);
  const isBool = typeof value === "boolean";

  // Get human-readable label or fall back to key
  const label = CONFIG_LABELS[configKey] || configKey;

  return (
    <Box sx={{ display: "flex", gap: 2, alignItems: "center" }}>
      <Typography
        variant="body2"
        color="text.primary"
        sx={{ fontWeight: 500, minWidth: "240px", flexShrink: 0 }}
      >
        {label}
      </Typography>
      <Box sx={{ flex: 1, maxWidth: "400px" }}>
        {isBool ? (
          <Select
            value={stringValue}
            onChange={(e) => onChange(configKey, e.target.value)}
            disabled={disabled}
            size="small"
            fullWidth
          >
            <MenuItem value="true">true</MenuItem>
            <MenuItem value="false">false</MenuItem>
          </Select>
        ) : (
          <TextField
            type="text"
            value={stringValue}
            onChange={(e) => onChange(configKey, e.target.value)}
            disabled={disabled}
            size="small"
            fullWidth
          />
        )}
      </Box>
    </Box>
  );
}
