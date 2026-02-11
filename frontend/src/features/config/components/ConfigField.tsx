/**
 * ConfigField component.
 * Renders a single configuration field with appropriate input type.
 */

import { Box, MenuItem, Select, TextField, Typography } from "@mui/material";

// Human-readable labels and field configurations for config keys
const CONFIG_METADATA: Record<string, {
  label: string;
  description?: string;
  type?: 'text' | 'password' | 'boolean' | 'select';
  options?: { value: string; label: string }[];
}> = {
  file_write_mode: {
    label: "Tag Writing Mode",
    description: "Controls which tags are written to audio files",
    type: "select",
    options: [
      { value: "none", label: "None - Tags stored in database only" },
      { value: "minimal", label: "Minimal - Essential tags only (artist, album, title, genre)" },
      { value: "full", label: "Full - All generated tags written to files" },
    ],
  },
  overwrite_tags: {
    label: "Overwrite Existing Tags",
    description: "Whether to overwrite existing tags in audio files",
    type: "boolean",
  },
  library_auto_tag: {
    label: "Auto-Tag New Files",
    description: "Automatically process new files found during library scans",
    type: "boolean",
  },
  library_ignore_patterns: {
    label: "Ignore Patterns",
    description: "Comma-separated patterns to ignore during scanning (e.g., */Audiobooks/*,*.tmp)",
    type: "text",
  },
  tagger_worker_count: {
    label: "Worker Threads",
    description: "Number of parallel worker processes for tagging (0 = auto-detect)",
    type: "text",
  },
  cache_idle_timeout: {
    label: "Cache Timeout (seconds)",
    description: "How long to keep ML models in memory when idle",
    type: "text",
  },
  calibrate_heads: {
    label: "Auto-Calibrate Heads",
    description: "Automatically calibrate tag thresholds for optimal results",
    type: "boolean",
  },
  calibration_repo: {
    label: "Calibration Repository",
    description: "Git repository URL for calibration data downloads",
    type: "text",
  },
  spotify_client_id: {
    label: "Spotify Client ID",
    description: "From https://developer.spotify.com/dashboard - for playlist import",
    type: "text",
  },
  spotify_client_secret: {
    label: "Spotify Client Secret",
    description: "From https://developer.spotify.com/dashboard - keep this private",
    type: "password",
  },
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
  const metadata = CONFIG_METADATA[configKey];
  
  // Get configuration or fall back to defaults
  const label = metadata?.label || configKey;
  const description = metadata?.description;
  const fieldType = metadata?.type || (typeof value === "boolean" ? "boolean" : "text");
  const options = metadata?.options || [];

  const renderField = () => {
    if (fieldType === "select" && options.length > 0) {
      return (
        <Select
          value={stringValue}
          onChange={(e) => onChange(configKey, e.target.value)}
          disabled={disabled}
          size="small"
          fullWidth
        >
          {options.map(({ value: optionValue, label: optionLabel }) => (
            <MenuItem key={optionValue} value={optionValue}>
              {optionLabel}
            </MenuItem>
          ))}
        </Select>
      );
    }
    
    if (fieldType === "boolean") {
      return (
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
      );
    }
    
    // Default to text field
    return (
      <TextField
        type={fieldType === "password" ? "password" : "text"}
        value={stringValue}
        onChange={(e) => onChange(configKey, e.target.value)}
        disabled={disabled}
        size="small"
        fullWidth
        placeholder={description}
      />
    );
  };

  return (
    <Box sx={{ display: "flex", gap: 2, alignItems: "flex-start", py: 1 }}>
      <Box sx={{ minWidth: "280px", flexShrink: 0 }}>
        <Typography
          variant="body2"
          color="text.primary"
          sx={{ fontWeight: 500, mb: description ? 0.5 : 0 }}
        >
          {label}
        </Typography>
        {description && (
          <Typography
            variant="caption"
            color="text.secondary"
            sx={{ display: "block" }}
          >
            {description}
          </Typography>
        )}
      </Box>
      <Box sx={{ flex: 1, maxWidth: "400px" }}>
        {renderField()}
      </Box>
    </Box>
  );
}
