/**
 * Hook for managing histogram-based calibration generation with background polling.
 * Starts generation and polls for status/progress until completion.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  HistogramCalibrationProgress,
  HistogramCalibrationResult,
} from "../../../shared/api/calibration";
import {
  getHistogramProgress,
  getHistogramStatus,
  startHistogramCalibration,
} from "../../../shared/api/calibration";

export interface CalibrationGenerationState {
  /** Whether generation is currently running */
  isGenerating: boolean;
  /** Progress info (heads completed/total) */
  progress: HistogramCalibrationProgress | null;
  /** Final result when completed */
  result: HistogramCalibrationResult | null;
  /** Error message if failed */
  error: string | null;
  /** Whether the operation completed (success or failure) */
  completed: boolean;
}

export interface UseHistogramCalibrationReturn {
  state: CalibrationGenerationState;
  /** Start calibration generation. No-op if already running. */
  startGeneration: () => Promise<void>;
  /** Reset state to allow starting a new generation */
  reset: () => void;
}

const POLL_INTERVAL_MS = 1000;

export function useHistogramCalibrationGeneration(): UseHistogramCalibrationReturn {
  const [state, setState] = useState<CalibrationGenerationState>({
    isGenerating: false,
    progress: null,
    result: null,
    error: null,
    completed: false,
  });

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMountedRef = useRef(true);

  // Cleanup on unmount
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
      if (pollIntervalRef.current) {
        clearInterval(pollIntervalRef.current);
        pollIntervalRef.current = null;
      }
    };
  }, []);

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  }, []);

  const pollStatus = useCallback(async () => {
    if (!isMountedRef.current) return;

    try {
      const [status, progress] = await Promise.all([
        getHistogramStatus(),
        getHistogramProgress(),
      ]);

      if (!isMountedRef.current) return;

      // Update progress
      setState((prev) => ({
        ...prev,
        progress,
        isGenerating: status.running,
      }));

      // Check for completion
      if (!status.running) {
        stopPolling();

        if (status.error) {
          setState((prev) => ({
            ...prev,
            isGenerating: false,
            error: status.error,
            completed: true,
          }));
        } else if (status.completed && status.result) {
          setState((prev) => ({
            ...prev,
            isGenerating: false,
            result: status.result,
            completed: true,
          }));
        }
      }
    } catch (err) {
      console.error("[CalibrationGeneration] Poll error:", err);
      // Don't stop polling on transient errors
    }
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return; // Already polling

    // Poll immediately, then on interval
    pollStatus();
    pollIntervalRef.current = setInterval(pollStatus, POLL_INTERVAL_MS);
  }, [pollStatus]);

  const startGeneration = useCallback(async () => {
    // Don't start if already running
    if (state.isGenerating) return;

    setState({
      isGenerating: true,
      progress: null,
      result: null,
      error: null,
      completed: false,
    });

    try {
      const response = await startHistogramCalibration();

      if (response.status === "already_running") {
        // Generation is already running, just start polling
        startPolling();
        return;
      }

      // Generation started, begin polling
      startPolling();
    } catch (err) {
      stopPolling();
      setState((prev) => ({
        ...prev,
        isGenerating: false,
        error: err instanceof Error ? err.message : "Failed to start calibration",
        completed: true,
      }));
    }
  }, [state.isGenerating, startPolling, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setState({
      isGenerating: false,
      progress: null,
      result: null,
      error: null,
      completed: false,
    });
  }, [stopPolling]);

  // Check initial status on mount (in case generation is already running)
  useEffect(() => {
    const checkInitialStatus = async () => {
      try {
        const status = await getHistogramStatus();
        if (status.running) {
          setState((prev) => ({ ...prev, isGenerating: true }));
          startPolling();
        }
      } catch (err) {
        console.error("[CalibrationGeneration] Initial status check failed:", err);
      }
    };
    checkInitialStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    state,
    startGeneration,
    reset,
  };
}
