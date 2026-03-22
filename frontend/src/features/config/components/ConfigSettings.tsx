/**
 * ConfigSettings component.
 * Displays all configuration fields with save button, grouped by section.
 */

import { Box, Button, Divider, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { listBackbones } from "@shared/api/vectors";
import { Panel, SectionHeader } from "@shared/components/ui";

import { ConfigField } from "./ConfigField";

interface ConfigSettingsProps {
  config: Record<string, unknown>;
  hasChanges: boolean;
  saveLoading: boolean;
  onChange: (key: string, value: string) => void;
  onSaveAll: () => Promise<void>;
}

/** Desired display order for personal playlist algorithm tuning settings. */
const PP_ORDER: string[] = [
  "pp_backbone_id",
  "pp_overwrite_playlists",
  "pp_top_n",
  "pp_min_play_count",
  "pp_half_life_days",
];

/** Partition config entries into general and sorted personal-playlist groups. */
function partitionConfig(config: Record<string, unknown>) {
  const general: [string, unknown][] = [];
  const ppMap = new Map<string, unknown>();

  for (const [key, value] of Object.entries(config)) {
    if (key.startsWith("pp_")) {
      ppMap.set(key, value);
    } else {
      general.push([key, value]);
    }
  }

  // Build ordered list — known keys first, then any unexpected extras
  const personalPlaylist: [string, unknown][] = [];
  for (const key of PP_ORDER) {
    if (ppMap.has(key)) {
      personalPlaylist.push([key, ppMap.get(key)]);
      ppMap.delete(key);
    }
  }
  // Append any remaining pp_ keys not in the explicit order
  for (const [key, value] of ppMap) {
    personalPlaylist.push([key, value]);
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

  // Fetch available backbones for the dropdown
  const [backboneOptions, setBackboneOptions] = useState<{ value: string; label: string }[]>([]);
  useEffect(() => {
    let cancelled = false;
    listBackbones()
      .then((resp) => {
        if (!cancelled) {
          setBackboneOptions(
            resp.backbones.map((b) => ({ value: b, label: b })),
          );
        }
      })
      .catch(() => {
        /* ignore — field falls back to showing the raw value */
      });
    return () => { cancelled = true; };
  }, []);


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

      {/* Playlist algorithm tuning settings */}
      {personalPlaylist.length > 0 && (
        <>
          <Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1, mt: 3 }}>
            Playlist Algorithm Tuning
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
                {...(key === "pp_backbone_id" ? { dynamicOptions: backboneOptions } : {})}
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
