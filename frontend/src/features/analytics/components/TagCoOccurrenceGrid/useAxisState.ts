/**
 * Hook for managing axis state with reducer pattern.
 * Handles preset selection, tag management, and axis swapping.
 */

import { useReducer, useCallback, useEffect } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";

import type { GridAxesState, AxisAction, PresetId } from "./types";
import { INITIAL_AXIS_STATE, PRESET_METADATA } from "./types";
import { usePresetData } from "./usePresetData";

const initialState: GridAxesState = {
  x: { ...INITIAL_AXIS_STATE, preset: "genre" },
  y: { ...INITIAL_AXIS_STATE, preset: "year" },
};

function axisReducer(state: GridAxesState, action: AxisAction): GridAxesState {
  switch (action.type) {
    case "SELECT_PRESET": {
      const axis = state[action.axis];
      return {
        ...state,
        [action.axis]: {
          ...axis,
          preset: action.presetId,
          tags: [], // Clear tags when preset changes
          loading: action.presetId !== "manual", // Manual doesn't load
          error: null,
        },
      };
    }

    case "SET_TAGS": {
      const axis = state[action.axis];
      return {
        ...state,
        [action.axis]: {
          ...axis,
          tags: action.tags,
          loading: false,
        },
      };
    }

    case "SET_LOADING": {
      const axis = state[action.axis];
      return {
        ...state,
        [action.axis]: {
          ...axis,
          loading: action.loading,
        },
      };
    }

    case "SET_ERROR": {
      const axis = state[action.axis];
      return {
        ...state,
        [action.axis]: {
          ...axis,
          error: action.error,
          loading: false,
        },
      };
    }

    case "SWAP_AXES": {
      return {
        x: state.y,
        y: state.x,
      };
    }

    case "ADD_MANUAL_TAG": {
      const axis = state[action.axis];
      // Only allow in manual mode
      if (axis.preset !== "manual") return state;

      const maxValues = PRESET_METADATA.manual.maxValues;
      if (axis.tags.length >= maxValues) return state;

      // Check for duplicates
      const isDuplicate = axis.tags.some(
        (t) => t.key === action.tag.key && t.value === action.tag.value
      );
      if (isDuplicate) return state;

      // Check if tag exists on other axis
      const otherAxis = action.axis === "x" ? "y" : "x";
      const existsOnOther = state[otherAxis].tags.some(
        (t) => t.key === action.tag.key && t.value === action.tag.value
      );
      if (existsOnOther) return state;

      return {
        ...state,
        [action.axis]: {
          ...axis,
          tags: [...axis.tags, action.tag],
        },
      };
    }

    case "REMOVE_TAG": {
      const axis = state[action.axis];
      // Only allow in manual mode
      if (axis.preset !== "manual") return state;

      return {
        ...state,
        [action.axis]: {
          ...axis,
          tags: axis.tags.filter((_, i) => i !== action.index),
        },
      };
    }

    case "CLEAR_AXIS": {
      const axis = state[action.axis];
      return {
        ...state,
        [action.axis]: {
          ...axis,
          tags: [],
        },
      };
    }

    default:
      return state;
  }
}

export interface UseAxisStateResult {
  state: GridAxesState;
  /** Select a preset for an axis */
  selectPreset: (axis: "x" | "y", presetId: PresetId) => void;
  /** Swap X and Y axes */
  swapAxes: () => void;
  /** Add a manual tag to an axis */
  addManualTag: (axis: "x" | "y", tag: TagSpec) => void;
  /** Remove a tag from an axis by index */
  removeTag: (axis: "x" | "y", index: number) => void;
  /** Clear all tags from an axis */
  clearAxis: (axis: "x" | "y") => void;
  /** Whether either axis is loading */
  isLoading: boolean;
  /** Whether we have enough data to build matrix */
  canBuildMatrix: boolean;
}

export function useAxisState(): UseAxisStateResult {
  const [state, dispatch] = useReducer(axisReducer, initialState);

  // Fetch preset data for each axis
  const xPresetData = usePresetData(state.x.preset);
  const yPresetData = usePresetData(state.y.preset);

  // Sync preset data to state when loaded
  useEffect(() => {
    if (!xPresetData.loading && xPresetData.tags.length > 0) {
      dispatch({ type: "SET_TAGS", axis: "x", tags: xPresetData.tags });
    }
    if (xPresetData.error) {
      dispatch({ type: "SET_ERROR", axis: "x", error: xPresetData.error });
    }
  }, [xPresetData.tags, xPresetData.loading, xPresetData.error]);

  useEffect(() => {
    if (!yPresetData.loading && yPresetData.tags.length > 0) {
      dispatch({ type: "SET_TAGS", axis: "y", tags: yPresetData.tags });
    }
    if (yPresetData.error) {
      dispatch({ type: "SET_ERROR", axis: "y", error: yPresetData.error });
    }
  }, [yPresetData.tags, yPresetData.loading, yPresetData.error]);

  // Sync loading state
  useEffect(() => {
    dispatch({ type: "SET_LOADING", axis: "x", loading: xPresetData.loading });
  }, [xPresetData.loading]);

  useEffect(() => {
    dispatch({ type: "SET_LOADING", axis: "y", loading: yPresetData.loading });
  }, [yPresetData.loading]);

  const selectPreset = useCallback((axis: "x" | "y", presetId: PresetId) => {
    dispatch({ type: "SELECT_PRESET", axis, presetId });
  }, []);

  const swapAxes = useCallback(() => {
    dispatch({ type: "SWAP_AXES" });
  }, []);

  const addManualTag = useCallback((axis: "x" | "y", tag: TagSpec) => {
    dispatch({ type: "ADD_MANUAL_TAG", axis, tag });
  }, []);

  const removeTag = useCallback((axis: "x" | "y", index: number) => {
    dispatch({ type: "REMOVE_TAG", axis, index });
  }, []);

  const clearAxis = useCallback((axis: "x" | "y") => {
    dispatch({ type: "CLEAR_AXIS", axis });
  }, []);

  const isLoading = state.x.loading || state.y.loading;
  const canBuildMatrix = state.x.tags.length > 0 && state.y.tags.length > 0;

  return {
    state,
    selectPreset,
    swapAxes,
    addManualTag,
    removeTag,
    clearAxis,
    isLoading,
    canBuildMatrix,
  };
}
