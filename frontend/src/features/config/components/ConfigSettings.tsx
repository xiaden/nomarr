/**
 * ConfigSettings component.
 * Displays all configuration fields with save button.
 */

import { Box, Button, Stack, Typography } from "@mui/material";

import { Panel, SectionHeader } from "@shared/components/ui";

import { ConfigField } from "./ConfigField";

interface ConfigSettingsProps {
  config: Record<string, unknown>;
  hasChanges: boolean;
  saveLoading: boolean;
  onChange: (key: string, value: string) => void;
  onSaveAll: () => Promise<void>;
}

export function ConfigSettings({
  config,
  hasChanges,
  saveLoading,
  onChange,
  onSaveAll,
}: ConfigSettingsProps) {
  return (
    <Panel>
      <SectionHeader title="Settings" />
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 2.5 }}
      >
        Changes are saved to the database and will take effect on server
        restart. Use "Restart Server" in the Admin section below to apply changes.
      </Typography>
      <Stack spacing={1.875}>
        {Object.entries(config).map(([key, value]) => (
          <ConfigField
            key={key}
            configKey={key}
            value={value}
            onChange={onChange}
            disabled={saveLoading}
          />
        ))}
      </Stack>

      <Box
        sx={{
          mt: 3.75,
          display: "flex",
          gap: 1.25,
          alignItems: "center",
        }}
      >
        <Button
          onClick={onSaveAll}
          variant="contained"
          disabled={!hasChanges || saveLoading}
          sx={{
            whiteSpace: "nowrap",
          }}
        >
          {saveLoading ? "Saving..." : "Save All Changes"}
        </Button>
        {hasChanges && (
          <Typography variant="body2" color="warning.main">
            Unsaved changes
          </Typography>
        )}
      </Box>
    </Panel>
  );
}
