/**
 * Hook for managing background calibration apply with polling.
 * Starts apply and polls for status/progress until completion.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import type {
  ApplyCalibrationResponse,
  ApplyProgress,
} from "../../../shared/api/calibration";
import {
  getApplyProgress,
  getApplyStatus,
  startApplyCalibration,
} from "../../../shared/api/calibration";

export interface CalibrationApplyState {
  /** Whether apply is currently running */
  isApplying: boolean;
  /** Progress info (files completed/total) */
  progress: ApplyProgress | null;
  /** Final result when completed */
  result: ApplyCalibrationResponse | null;
  /** Error message if failed */
  error: string | null;
  /** Whether the operation completed (success or failure) */
  completed: boolean;
}

export interface UseCalibrationApplyReturn {
  state: CalibrationApplyState;
  /** Start calibration apply. No-op if already running. */
  startApply: () => Promise<void>;
  /** Reset state to allow starting a new apply */
  reset: () => void;
}

const POLL_INTERVAL_MS = 1000;

export function useCalibrationApply(): UseCalibrationApplyReturn {
  const [state, setState] = useState<CalibrationApplyState>({
    isApplying: false,
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
        getApplyStatus(),
        getApplyProgress(),
      ]);

      if (!isMountedRef.current) return;

      // Update progress
      setState((prev) => ({
        ...prev,
        progress,
        isApplying: status.status === "running",
      }));

      // Check for completion
      if (status.status !== "running") {
        stopPolling();

        if (status.status === "failed") {
          setState((prev) => ({
            ...prev,
            isApplying: false,
            error: status.error,
            completed: true,
          }));
        } else if (status.status === "completed" && status.result) {
          setState((prev) => ({
            ...prev,
            isApplying: false,
            result: status.result,
            completed: true,
          }));
        }
      }
    } catch (err) {
      console.error("[CalibrationApply] Poll error:", err);
      // Don't stop polling on transient errors
    }
  }, [stopPolling]);

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return; // Already polling

    // Poll immediately, then on interval
    pollStatus();
    pollIntervalRef.current = setInterval(pollStatus, POLL_INTERVAL_MS);
  }, [pollStatus]);

  const startApply = useCallback(async () => {
    // Don't start if already running
    if (state.isApplying) return;

    setState({
      isApplying: true,
      progress: null,
      result: null,
      error: null,
      completed: false,
    });

    try {
      const response = await startApplyCalibration();

      if (response.status === "already_running") {
        // Apply is already running, just start polling
        startPolling();
        return;
      }

      // Apply started, begin polling
      startPolling();
    } catch (err) {
      stopPolling();
      setState((prev) => ({
        ...prev,
        isApplying: false,
        error:
          err instanceof Error
            ? err.message
            : "Failed to start calibration apply",
        completed: true,
      }));
    }
  }, [state.isApplying, startPolling, stopPolling]);

  const reset = useCallback(() => {
    stopPolling();
    setState({
      isApplying: false,
      progress: null,
      result: null,
      error: null,
      completed: false,
    });
  }, [stopPolling]);

  // Check initial status on mount (in case apply is already running)
  useEffect(() => {
    const checkInitialStatus = async () => {
      try {
        const status = await getApplyStatus();
        if (status.status === "running") {
          setState((prev) => ({ ...prev, isApplying: true }));
          startPolling();
        }
      } catch (err) {
        console.error(
          "[CalibrationApply] Initial status check failed:",
          err,
        );
      }
    };
    checkInitialStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { state, startApply, reset };
}
