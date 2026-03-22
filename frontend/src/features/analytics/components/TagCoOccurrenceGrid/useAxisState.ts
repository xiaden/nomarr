/**
 * Hook for managing axis state with reducer pattern.
 * Handles preset selection, tag management, and axis swapping.
 */

import { useReducer, useCallback } from "react";
import type { Dispatch } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";

import type { GridAxesState, AxisAction, PresetId } from "./types";
import { INITIAL_AXIS_STATE, PRESET_METADATA } from "./types";

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
  /** Raw reducer dispatch — used by parent to push SET_TAGS / SET_ERROR / SET_LOADING */
  dispatch: Dispatch<AxisAction>;
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
    dispatch,
    selectPreset,
    swapAxes,
    addManualTag,
    removeTag,
    clearAxis,
    isLoading,
    canBuildMatrix,
  };
}
