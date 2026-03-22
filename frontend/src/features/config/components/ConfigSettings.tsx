/**
 * ConfigSettings component.
 * Displays all configuration fields with save button, grouped by section.
 */

import { Box, Button, Divider, Stack, Typography } from "@mui/material";

import { Panel, SectionHeader } from "@shared/components/ui";

import { ConfigField } from "./ConfigField";

interface ConfigSettingsProps {
  config: Record<string, unknown>;
  hasChanges: boolean;
  saveLoading: boolean;
  onChange: (key: string, value: string) => void;
  onSaveAll: () => Promise<void>;
}

/** Partition config entries into general and personal-playlist groups. */
function partitionConfig(config: Record<string, unknown>) {
  const general: [string, unknown][] = [];
  const personalPlaylist: [string, unknown][] = [];

  for (const [key, value] of Object.entries(config)) {
    if (key.startsWith("pp_")) {
      personalPlaylist.push([key, value]);
    } else {
      general.push([key, value]);
    }
  }

  return { general, personalPlaylist };
}

export function ConfigSettings({
  config,
  hasChanges,
  saveLoading,
  onChange,
  onSaveAll,
}: ConfigSettingsProps) {
  const { general, personalPlaylist } = partitionConfig(config);

  return (
    <Panel>
      <SectionHeader title="Settings" />
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 2.5 }}
      >
        Changes are saved to the database and will take effect on server
        restart. Use &ldquo;Restart Server&rdquo; in the Admin section below to apply changes.
      </Typography>

      {/* General settings */}
      <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, mt: 1 }}>
        General
      </Typography>
      <Divider sx={{ mb: 1.5 }} />
      <Stack spacing={1.875}>
        {general.map(([key, value]) => (
          <ConfigField
            key={key}
            configKey={key}
            value={value}
            onChange={onChange}
            disabled={saveLoading}
          />
        ))}
      </Stack>

      {/* Personal playlists settings */}
      {personalPlaylist.length > 0 && (
        <>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, mt: 3 }}>
            Personal Playlists
          </Typography>
          <Divider sx={{ mb: 1.5 }} />
          <Stack spacing={1.875}>
            {personalPlaylist.map(([key, value]) => (
              <ConfigField
                key={key}
                configKey={key}
                value={value}
                onChange={onChange}
                disabled={saveLoading}
              />
            ))}
          </Stack>
        </>
      )}

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
