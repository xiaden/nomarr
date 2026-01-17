import { Box, Stack, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "react";

import {
    ErrorMessage,
    MetricCard,
    PageContainer,
    Panel,
    ProgressBar,
    ResponsiveGrid,
    SectionHeader,
} from "@shared/components/ui";

import { useSSE } from "../../hooks/useSSE";
import { getStats } from "../../shared/api/library";
import { getQueueStatus } from "../../shared/api/queue";

/**
 * Dashboard page component.
 *
 * Landing page showing:
 * - System overview with real-time updates
 * - Queue summary with progress tracking
 * - Library stats
 */

interface QueueSummary {
  pending: number;
  running: number;
  completed: number;
  errors: number;
}

interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

interface ProgressTracking {
  totalJobs: number;
  completedCount: number;
  filesPerMinute: number;
  estimatedMinutesRemaining: number | null;
  lastUpdateTime: number;
}

export function DashboardPage() {
  const [queueSummary, setQueueSummary] = useState<QueueSummary | null>(null);
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressTracking | null>(null);

  // Track completed count over time for velocity calculation
  const completedHistoryRef = useRef<Array<{ count: number; time: number }>>(
    []
  );

  const loadDashboard = async () => {
    try {
      setLoading(true);
      setError(null);

      const [queue, library] = await Promise.all([
        getQueueStatus(),
        getStats(),
      ]);

      setQueueSummary(queue);
      setLibraryStats(library);

      // Initialize progress tracking
      updateProgressTracking(queue);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load dashboard data"
      );
      console.error("[Dashboard] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const updateProgressTracking = (queue: QueueSummary) => {
    const now = Date.now();
    const total = queue.pending + queue.running + queue.completed + queue.errors;
    const completed = queue.completed;

    // Track completed count history (last 5 minutes)
    const history = completedHistoryRef.current;
    history.push({ count: completed, time: now });

    // Keep only last 5 minutes of data
    const fiveMinutesAgo = now - 5 * 60 * 1000;
    completedHistoryRef.current = history.filter(
      (entry) => entry.time > fiveMinutesAgo
    );

    // Calculate velocity (files per minute)
    let filesPerMinute = 0;
    let estimatedMinutesRemaining: number | null = null;

    if (completedHistoryRef.current.length >= 2) {
      const oldest = completedHistoryRef.current[0];
      const newest = completedHistoryRef.current[completedHistoryRef.current.length - 1];
      const timeDiffMinutes = (newest.time - oldest.time) / (1000 * 60);
      const countDiff = newest.count - oldest.count;

      if (timeDiffMinutes > 0 && countDiff > 0) {
        filesPerMinute = countDiff / timeDiffMinutes;

        // Calculate ETA for remaining jobs
        const remaining = queue.pending + queue.running;
        if (remaining > 0 && filesPerMinute > 0) {
          estimatedMinutesRemaining = remaining / filesPerMinute;
        }
      }
    }

    setProgress({
      totalJobs: total,
      completedCount: completed,
      filesPerMinute: Math.round(filesPerMinute * 10) / 10,
      estimatedMinutesRemaining,
      lastUpdateTime: now,
    });
  };

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // SSE real-time updates
  const { connected } = useSSE({
    onMessage: (event) => {
      try {
        const data = JSON.parse(event.data);
        console.log("[Dashboard] SSE update:", data);

        // Update queue summary if data contains queue info
        if (data.queue) {
          setQueueSummary({
            pending: data.queue.pending || 0,
            running: data.queue.running || 0,
            completed: data.queue.completed || 0,
            errors: data.queue.errors || 0,
          });

          // Update progress tracking
          updateProgressTracking({
            pending: data.queue.pending || 0,
            running: data.queue.running || 0,
            completed: data.queue.completed || 0,
            errors: data.queue.errors || 0,
          });
        }
      } catch (err) {
        console.error("[Dashboard] Failed to parse SSE message:", err);
      }
    },
    onError: (error) => {
      console.error("[Dashboard] SSE error:", error);
    },
  });

  const formatDuration = (seconds: number): string => {
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${hours}h ${minutes}m`;
  };

  const formatETA = (minutes: number | null): string => {
    if (minutes === null || minutes <= 0) return "—";
    if (minutes < 1) return "< 1 min";
    if (minutes < 60) return `${Math.round(minutes)} min`;
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    return `${hours}h ${mins}m`;
  };

  const hasActiveJobs =
    queueSummary && (queueSummary.pending > 0 || queueSummary.running > 0);
  const progressPercent =
    progress && progress.totalJobs > 0
      ? Math.round((progress.completedCount / progress.totalJobs) * 100)
      : 0;

  return (
    <PageContainer title="Dashboard">
      {/* Connection Status */}
      <Typography
        variant="body2"
        sx={{
          color: connected ? "success.main" : "error.main",
          mb: 2,
        }}
      >
        {connected ? "● Live" : "● Disconnected"}
      </Typography>

      {loading && <Typography sx={{ mt: 2 }}>Loading dashboard...</Typography>}
      {error && <ErrorMessage>Error: {error}</ErrorMessage>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          {/* Processing Status */}
          {hasActiveJobs && progress && (
            <Panel>
              <SectionHeader title="Processing Status" />

              <Box sx={{ mb: 2 }}>
                <ProgressBar
                  label="Files processed"
                  value={progress.completedCount}
                  total={progress.totalJobs}
                  percentage={progressPercent}
                />
              </Box>

              <ResponsiveGrid minWidth={150}>
                <MetricCard
                  label="Velocity"
                  value={
                    progress.filesPerMinute > 0
                      ? `${progress.filesPerMinute}/min`
                      : "—"
                  }
                />
                <MetricCard
                  label="ETA"
                  value={formatETA(progress.estimatedMinutesRemaining)}
                />
                <MetricCard
                  label="Active"
                  value={queueSummary?.running || 0}
                />
                <MetricCard
                  label="Remaining"
                  value={queueSummary?.pending || 0}
                />
              </ResponsiveGrid>
            </Panel>
          )}

          {/* Queue Summary */}
          <Panel>
            <SectionHeader title="Queue Summary" />
            {queueSummary && (
              <ResponsiveGrid minWidth={150}>
                <MetricCard label="Pending" value={queueSummary.pending} />
                <MetricCard label="Running" value={queueSummary.running} />
                <MetricCard label="Completed" value={queueSummary.completed} />
                <MetricCard label="Errors" value={queueSummary.errors} />
              </ResponsiveGrid>
            )}
          </Panel>

          {/* Library Stats */}
          <Panel>
            <SectionHeader title="Library Stats" />
            {libraryStats && (
              <ResponsiveGrid minWidth={200}>
                <MetricCard label="Total Files" value={libraryStats.total_files} />
                <MetricCard label="Artists" value={libraryStats.unique_artists} />
                <MetricCard label="Albums" value={libraryStats.unique_albums} />
                <MetricCard
                  label="Total Duration"
                  value={formatDuration(libraryStats.total_duration_seconds)}
                />
              </ResponsiveGrid>
            )}
          </Panel>

          {/* Recent Activity placeholder */}
          <Panel>
            <SectionHeader title="Recent Activity" />
            <Typography color="text.secondary" fontStyle="italic">
              Recently processed tracks and system events will appear here.
            </Typography>
          </Panel>
        </Stack>
      )}
    </PageContainer>
  );
}
