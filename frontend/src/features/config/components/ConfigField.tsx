/**
 * ConfigField component.
 * Renders a single configuration field with appropriate input type.
 */

import {
  Box,
  MenuItem,
  Select,
  TextField,
  Typography,
} from "@mui/material";

// Human-readable labels and field configurations for config keys
const CONFIG_METADATA: Record<string, {
  label: string;
  description?: string;
  type?: 'text' | 'password' | 'boolean' | 'select' | 'number';
  options?: { value: string; label: string }[];
}> = {
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
  calibrate_heads: {
    label: "Auto-Calibrate Heads",
    description: "Automatically calibrate tag thresholds for optimal results",
    type: "boolean",
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
  navidrome_api_url: {
    label: "Navidrome API URL",
    description: "Navidrome server URL (e.g. http://navidrome:4533)",
    type: "text",
  },
  navidrome_api_user: {
    label: "Navidrome Username",
    description: "Navidrome admin username for API access",
    type: "text",
  },
  navidrome_api_password: {
    label: "Navidrome Password",
    description: "Navidrome admin password for API access",
    type: "password",
  },
  navidrome_path_prefix_map: {
    label: "Path Prefix Map",
    description: "Comma-separated from:to path prefix pairs when Navidrome and Nomarr mount the same files at different paths",
    type: "text",
  },
  m3u_output_path: {
    label: "M3U Output Path",
    description: "Directory path (relative to library root) where M3U playlist files are saved",
    type: "text",
  },
  vector_group_size: {
    label: "Vector Group Size",
    description: "Songs per similarity neighborhood (5-100). Individual libraries can override this.",
    type: "number",
  },
  vector_search_thoroughness: {
    label: "Search Thoroughness",
    description: "Percentage of neighborhoods searched (1-50). Higher = more accurate, slower. Libraries can override.",
    type: "number",
  },
  // -- Personal playlists (algorithm tuning) --
  pp_enabled: {
    label: "Personal Playlists",
    description: "Enable personal playlist generation",
    type: "boolean",
  },
  pp_backbone_id: {
    label: "Backbone",
    description: "Embedding backbone model used for similarity calculations",
    type: "select",
  },
  pp_half_life_days: {
    label: "Recency Half-Life (days)",
    description: "Exponential decay rate for play-history weighting (server default)",
    type: "number",
  },
  pp_top_n: {
    label: "Top Plays to Fetch",
    description: "Number of top-played songs to consider when building taste profiles",
    type: "number",
  },
  pp_min_play_count: {
    label: "Min Play Count",
    description: "Minimum play count for a song to be included in taste profile calculation",
    type: "number",
  },
  pp_max_songs: {
    label: "Max Songs per Playlist",
    description: "Maximum number of songs in each generated playlist",
    type: "number",
  },
  pp_min_songs: {
    label: "Min Songs per Playlist",
    description: "Minimum number of songs required to create a playlist",
    type: "number",
  },
  pp_max_genre_playlists: {
    label: "Max Genre Playlists",
    description: "Maximum number of genre-focused playlists to generate per run",
    type: "number",
  },
  pp_max_clusters: {
    label: "Max Taste Clusters",
    description: "Maximum number of genre clusters per taste profile",
    type: "number",
  },
  pp_overwrite_playlists: {
    label: "Overwrite Playlists",
    description: "Replace existing playlists on each generation run instead of appending",
    type: "boolean",
  },
  pp_type_familiar: {
    label: "Generate Familiar",
    description: "Generate 'Familiar Favorites' playlists from highly-played songs",
    type: "boolean",
  },
  pp_type_discovery: {
    label: "Generate Discovery",
    description: "Generate 'Discovery' playlists with unheard songs similar to favorites",
    type: "boolean",
  },
  pp_type_hidden_gems: {
    label: "Generate Hidden Gems",
    description: "Generate 'Hidden Gems' playlists with rarely-played songs that match your taste",
    type: "boolean",
  },
  pp_type_genre: {
    label: "Generate Genre",
    description: "Generate genre-focused playlists based on top genre preferences",
    type: "boolean",
  },
  pp_type_universal: {
    label: "Generate Universal",
    description: "Generate a universal mix playlist blending all taste dimensions",
    type: "boolean",
  },
};

interface ConfigFieldProps {
  configKey: string;
  value: unknown;
  onChange: (key: string, value: string) => void;
  disabled: boolean;
  /** Dynamic select options — used for fields like backbone_id where options come from the API. */
  dynamicOptions?: { value: string; label: string }[];
}

export function ConfigField({
  configKey,
  value,
  onChange,
  disabled,
  dynamicOptions,
}: ConfigFieldProps) {
  const stringValue = value === null || value === undefined ? "" : String(value);
  const metadata = CONFIG_METADATA[configKey];
  
  // Get configuration or fall back to defaults
  const label = metadata?.label || configKey;
  const description = metadata?.description;
  const fieldType = metadata?.type || (typeof value === "boolean" ? "boolean" : "text");
  const options = dynamicOptions || metadata?.options || [];

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

    // Select field with no options yet — show disabled placeholder
    if (fieldType === "select") {
      return (
        <Select
          value={stringValue}
          disabled
          size="small"
          fullWidth
        >
          <MenuItem value={stringValue}>{stringValue || "Loading…"}</MenuItem>
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
    
    // Number and text fields
    return (
      <TextField
        type={fieldType === "password" ? "password" : fieldType === "number" ? "number" : "text"}
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
