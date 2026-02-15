/**
 * Type definitions for the Tag Co-Occurrence Grid component.
 * 
 * Defines preset metadata, axis state management, and fetch strategies
 * for the redesigned co-occurrence visualization.
 */

import type { TagSpec } from "../../../../shared/api/analytics";

// ────────────────────────────────────────────────────────────────────────────
// Preset Definitions
// ────────────────────────────────────────────────────────────────────────────

/** Identifiers for built-in presets */
export type PresetId = "genre" | "mood" | "year" | "manual";

/** Fetch strategy for loading preset values */
export interface PresetFetchStrategy {
  /** Tag key to query (e.g., "genre", "year") or null for mood (multi-key) */
  tagKey: string | null;
  /** Whether to filter to nomarr-only tags */
  nomarrOnly: boolean;
  /** For mood preset: explicit list of keys to treat as boolean presence */
  explicitKeys?: string[];
}

/** Metadata describing a preset option */
export interface PresetMetadata {
  id: PresetId;
  label: string;
  description: string;
  /** How to fetch values for this preset */
  fetchStrategy: PresetFetchStrategy;
  /** Maximum values to include (API limit is 16 per axis) */
  maxValues: number;
  /** Transform function for display labels (e.g., mood key → friendly name) */
  labelTransform?: (value: string) => string;
}

/** All available presets with their metadata */
export const PRESET_METADATA: Record<PresetId, PresetMetadata> = {
  genre: {
    id: "genre",
    label: "Genre",
    description: "All unique genre tag values from your library",
    fetchStrategy: {
      tagKey: "genre",
      nomarrOnly: false,
    },
    maxValues: 16,
  },
  mood: {
    id: "mood",
    label: "Mood",
    description: "nom:mood-* tags (presence/absence per file)",
    fetchStrategy: {
      tagKey: null,
      nomarrOnly: true,
      explicitKeys: ["nom:mood-loose", "nom:mood-regular", "nom:mood-strict"],
    },
    maxValues: 16,
    labelTransform: (key: string) => {
      const labels: Record<string, string> = {
        "nom:mood-loose": "Mood (Loose)",
        "nom:mood-regular": "Mood (Regular)",
        "nom:mood-strict": "Mood (Strict)",
      };
      return labels[key] ?? key;
    },
  },
  year: {
    id: "year",
    label: "Year",
    description: "Release year values from your library",
    fetchStrategy: {
      tagKey: "year",
      nomarrOnly: false,
    },
    maxValues: 16,
  },
  manual: {
    id: "manual",
    label: "Manual",
    description: "Select individual tag key/value pairs",
    fetchStrategy: {
      tagKey: null,
      nomarrOnly: false,
    },
    maxValues: 16,
  },
};

// ────────────────────────────────────────────────────────────────────────────
// Axis State Model
// ────────────────────────────────────────────────────────────────────────────

/** State for a single axis (X or Y) */
export interface AxisState {
  /** Currently selected preset */
  preset: PresetId;
  /** Resolved tag specs for this axis (from preset or manual selection) */
  tags: TagSpec[];
  /** Loading state for preset data */
  loading: boolean;
  /** Error message if preset fetch failed */
  error: string | null;
}

/** Combined state for both axes */
export interface GridAxesState {
  x: AxisState;
  y: AxisState;
}

/** Initial axis state */
export const INITIAL_AXIS_STATE: AxisState = {
  preset: "genre",
  tags: [],
  loading: false,
  error: null,
};

// ────────────────────────────────────────────────────────────────────────────
// State Transitions
// ────────────────────────────────────────────────────────────────────────────

/**
 * Axis state transitions:
 * 
 * 1. SELECT_PRESET(axis, presetId)
 *    - Sets axis.preset = presetId
 *    - Sets axis.loading = true
 *    - Triggers fetch for preset values
 *    - On success: axis.tags = resolved specs, axis.loading = false
 *    - On error: axis.error = message, axis.loading = false
 * 
 * 2. SWAP_AXES
 *    - Swaps x and y states entirely (preset + tags)
 *    - No refetch needed since data is already loaded
 * 
 * 3. ADD_MANUAL_TAG(axis, tagSpec)
 *    - Only valid when axis.preset === "manual"
 *    - Appends tagSpec to axis.tags if not duplicate and under maxValues
 * 
 * 4. REMOVE_TAG(axis, index)
 *    - Removes tag at index from axis.tags
 *    - Only valid when axis.preset === "manual"
 * 
 * 5. CLEAR_AXIS(axis)
 *    - Resets axis.tags = []
 *    - Keeps preset selection
 * 
 * Constraints:
 * - Maximum 16 tags per axis (API limit)
 * - Same tag cannot appear on both axes simultaneously
 * - Presets auto-populate tags; manual mode allows individual selection
 */

export type AxisAction =
  | { type: "SELECT_PRESET"; axis: "x" | "y"; presetId: PresetId }
  | { type: "SET_TAGS"; axis: "x" | "y"; tags: TagSpec[] }
  | { type: "SET_LOADING"; axis: "x" | "y"; loading: boolean }
  | { type: "SET_ERROR"; axis: "x" | "y"; error: string | null }
  | { type: "SWAP_AXES" }
  | { type: "ADD_MANUAL_TAG"; axis: "x" | "y"; tag: TagSpec }
  | { type: "REMOVE_TAG"; axis: "x" | "y"; index: number }
  | { type: "CLEAR_AXIS"; axis: "x" | "y" };

// ────────────────────────────────────────────────────────────────────────────
// Helper Types
// ────────────────────────────────────────────────────────────────────────────

/** Props for the main grid component */
export interface TagCoOccurrenceGridProps {
  /** Optional library ID to filter results */
  libraryId?: string;
}

/** Matrix data from API */
export interface MatrixData {
  x: TagSpec[];
  y: TagSpec[];
  matrix: number[][];
}

/** Cell tooltip data */
export interface CellTooltipData {
  xTag: TagSpec;
  yTag: TagSpec;
  count: number;
  maxCount: number;
  percentage: number;
}
