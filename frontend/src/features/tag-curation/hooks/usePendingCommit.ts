import { useCallback, useEffect, useRef, useState } from "react";

import type { CommitResult } from "../../../shared/api/tagCuration";
import { commitPendingTags, fetchPendingCount } from "../../../shared/api/tagCuration";

const POLL_INTERVAL_MS = 10_000;

export interface UsePendingCommitResult {
  pendingCount: number;
  commit: (libraryId?: string) => Promise<CommitResult>;
  isCommitting: boolean;
  isPolling: boolean;
}

export function usePendingCommit(): UsePendingCommitResult {
  const [pendingCount, setPendingCount] = useState(0);
  const [isCommitting, setIsCommitting] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const poll = useCallback(async () => {
    try {
      const count = await fetchPendingCount();
      setPendingCount(count);
    } catch {
      // Silent poll failure — don't surface to UI
    }
  }, []);

  useEffect(() => {
    setIsPolling(true);
    void poll();
    intervalRef.current = setInterval(() => {
      void poll();
    }, POLL_INTERVAL_MS);
    return () => {
      if (intervalRef.current !== null) {
        clearInterval(intervalRef.current);
      }
      setIsPolling(false);
    };
  }, [poll]);

  const commit = useCallback(
    async (libraryId?: string): Promise<CommitResult> => {
      setIsCommitting(true);
      try {
        const result = await commitPendingTags(libraryId);
        await poll();
        return result;
      } finally {
        setIsCommitting(false);
      }
    },
    [poll]
  );

  return {
    pendingCount,
    commit,
    isCommitting,
    isPolling,
  };
}
