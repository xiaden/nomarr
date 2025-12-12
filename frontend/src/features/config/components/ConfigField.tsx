/**
 * ConfigField component.
 * Renders a single configuration field with appropriate input type.
 */

import { Box, MenuItem, Select, TextField, Typography } from "@mui/material";

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

  return (
    <Box sx={{ display: "grid", gap: 1 }}>
      <Typography variant="body2" color="text.secondary" sx={{ fontWeight: "bold" }}>
        {configKey}
      </Typography>
      <Box sx={{ display: "flex", gap: 1.25, alignItems: "center" }}>
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
