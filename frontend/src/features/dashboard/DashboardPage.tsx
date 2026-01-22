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

import { getStats } from "../../shared/api/library";
import { getProcessingStatus, type ProcessingStatus } from "../../shared/api/processing";

/**
 * Dashboard page component.
 *
 * Landing page showing:
 * - System overview with real-time updates
 * - Processing progress with velocity tracking
 * - Library stats
 */

interface LibraryStats {
  total_files: number;
  unique_artists: number;
  unique_albums: number;
  total_duration_seconds: number;
}

interface ProgressTracking {
  totalFiles: number;
  processedCount: number;
  filesPerMinute: number;
  estimatedMinutesRemaining: number | null;
  lastUpdateTime: number;
}

export function DashboardPage() {
  const [processingStatus, setProcessingStatus] = useState<ProcessingStatus | null>(null);
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressTracking | null>(null);

  // Track processed count over time for velocity calculation
  const processedHistoryRef = useRef<Array<{ count: number; time: number }>>(
    []
  );

  const loadDashboard = async () => {
    try {
      setLoading(true);
      setError(null);

      const [status, library] = await Promise.all([
        getProcessingStatus(),
        getStats(),
      ]);

      setProcessingStatus(status);
      setLibraryStats(library);

      // Initialize progress tracking
      updateProgressTracking(status);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load dashboard data"
      );
      console.error("[Dashboard] Load error:", err);
    } finally {
      setLoading(false);
    }
  };

  const updateProgressTracking = (status: ProcessingStatus) => {
    const now = Date.now();
    const processed = status.processed;

    // Track processed count history (last 5 minutes)
    const history = processedHistoryRef.current;
    history.push({ count: processed, time: now });

    // Keep only last 5 minutes of data
    const fiveMinutesAgo = now - 5 * 60 * 1000;
    processedHistoryRef.current = history.filter(
      (entry) => entry.time > fiveMinutesAgo
    );

    // Calculate velocity (files per minute)
    let filesPerMinute = 0;
    let estimatedMinutesRemaining: number | null = null;

    if (processedHistoryRef.current.length >= 2) {
      const oldest = processedHistoryRef.current[0];
      const newest = processedHistoryRef.current[processedHistoryRef.current.length - 1];
      const timeDiffMinutes = (newest.time - oldest.time) / (1000 * 60);
      const countDiff = newest.count - oldest.count;

      if (timeDiffMinutes > 0 && countDiff > 0) {
        filesPerMinute = countDiff / timeDiffMinutes;

        // Calculate ETA for remaining files
        const remaining = status.pending;
        if (remaining > 0 && filesPerMinute > 0) {
          estimatedMinutesRemaining = remaining / filesPerMinute;
        }
      }
    }

    setProgress({
      totalFiles: status.total,
      processedCount: processed,
      filesPerMinute: Math.round(filesPerMinute * 10) / 10,
      estimatedMinutesRemaining,
      lastUpdateTime: now,
    });
  };

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Adaptive polling: 1s when processing active, 30s when idle
  useEffect(() => {
    const hasPending = processingStatus && processingStatus.pending > 0;
    const pollInterval = hasPending ? 1000 : 30000; // 1s active, 30s idle

    const interval = setInterval(async () => {
      try {
        const status = await getProcessingStatus();
        setProcessingStatus(status);
        updateProgressTracking(status);
      } catch (err) {
        console.error("[Dashboard] Failed to update processing status:", err);
      }
    }, pollInterval);

    return () => clearInterval(interval);
  }, [processingStatus]);

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

  const hasPending = processingStatus && processingStatus.pending > 0;
  const progressPercent =
    progress && progress.totalFiles > 0
      ? Math.round((progress.processedCount / progress.totalFiles) * 100)
      : 0;

  return (
    <PageContainer title="Dashboard">
      {/* Connection Status */}
      <Typography
        variant="h4"
        sx={{ mb: 2 }}
      >
        Dashboard
      </Typography>

      {loading && <Typography sx={{ mt: 2 }}>Loading dashboard...</Typography>}
      {error && <ErrorMessage>Error: {error}</ErrorMessage>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          {/* Processing Status - show when files pending */}
          {hasPending && progress && (
            <Panel>
              <SectionHeader title="Processing Status" />

              <Box sx={{ mb: 2 }}>
                <ProgressBar
                  label="Files processed"
                  value={progress.processedCount}
                  total={progress.totalFiles}
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
                  label="Pending"
                  value={processingStatus?.pending || 0}
                />
                <MetricCard
                  label="Processed"
                  value={processingStatus?.processed || 0}
                />
              </ResponsiveGrid>
            </Panel>
          )}

          {/* Processing Summary - always show */}
          <Panel>
            <SectionHeader title="Processing Summary" />
            {processingStatus && (
              <ResponsiveGrid minWidth={150}>
                <MetricCard label="Pending" value={processingStatus.pending} />
                <MetricCard label="Processed" value={processingStatus.processed} />
                <MetricCard label="Total Files" value={processingStatus.total} />
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
