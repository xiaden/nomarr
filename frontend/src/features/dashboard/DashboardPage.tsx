import { MusicNote } from "@mui/icons-material";
import { Box, List, ListItem, ListItemIcon, ListItemText, Stack, Typography } from "@mui/material";
import { PieChart } from "@mui/x-charts/PieChart";
import { useEffect, useMemo, useState } from "react";

import {
    ErrorMessage,
    MetricCard,
    PageContainer,
    Panel,
    ProgressBar,
    ResponsiveGrid,
    SectionHeader,
} from "@shared/components/ui";
import { formatTotalDuration } from "@shared/utils/format";

import { getRecentActivity, getStats, type RecentFile } from "../../shared/api/library";
import { getWorkStatus, type WorkStatus } from "../../shared/api/processing";

/**
 * Dashboard page component.
 *
 * Landing page showing:
 * - System overview with real-time updates
 * - Processing progress with velocity tracking
 * - Library stats with charts
 * - Recent activity
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
}

export function DashboardPage() {
  const [workStatus, setWorkStatus] = useState<WorkStatus | null>(null);
  const [libraryStats, setLibraryStats] = useState<LibraryStats | null>(null);
  const [recentFiles, setRecentFiles] = useState<RecentFile[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ProgressTracking | null>(null);


  const loadDashboard = async () => {
    try {
      setLoading(true);
      setError(null);

      const [status, library, recent] = await Promise.all([
        getWorkStatus(),
        getStats(),
        getRecentActivity(10),
      ]);

      setWorkStatus(status);
      setLibraryStats(library);
      setRecentFiles(recent.files);

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

  const updateProgressTracking = (status: WorkStatus) => {
    setProgress({
      totalFiles: status.total_files,
      processedCount: status.processed_files,
      filesPerMinute: status.files_per_minute,
      estimatedMinutesRemaining: status.estimated_minutes_remaining,
    });
  };

  useEffect(() => {
    loadDashboard();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Adaptive polling: 1s when busy (scanning or processing), 30s when idle
  useEffect(() => {
    const isBusy = workStatus?.is_busy ?? false;
    const pollInterval = isBusy ? 1000 : 30000; // 1s active, 30s idle

    const interval = setInterval(async () => {
      try {
        const [status, recent] = await Promise.all([
          getWorkStatus(),
          getRecentActivity(10),
        ]);
        setWorkStatus(status);
        setRecentFiles(recent.files);
        updateProgressTracking(status);
      } catch (err) {
        console.error("[Dashboard] Failed to update work status:", err);
      }
    }, pollInterval);

    return () => clearInterval(interval);
  }, [workStatus]);

  const formatETA = (minutes: number | null): string => {
    if (minutes === null || minutes <= 0) return "—";
    if (minutes < 1) return "< 1 min";
    if (minutes < 60) return `${Math.round(minutes)} min`;
    const hours = Math.floor(minutes / 60);
    const mins = Math.round(minutes % 60);
    return `${hours}h ${mins}m`;
  };

  const formatTimeAgo = (timestamp: number): string => {
    const now = Date.now();
    const diff = now - timestamp;
    const minutes = Math.floor(diff / 60000);
    const hours = Math.floor(minutes / 60);
    const days = Math.floor(hours / 24);

    if (minutes < 1) return "just now";
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return `${days}d ago`;
  };

  // Pie chart data for library composition
  const libraryPieData = useMemo(() => {
    if (!libraryStats) return [];
    return [
      { id: "tracks", value: libraryStats.total_files, label: "Tracks", color: "#2196f3" },
      { id: "artists", value: libraryStats.unique_artists, label: "Artists", color: "#4caf50" },
      { id: "albums", value: libraryStats.unique_albums, label: "Albums", color: "#ff9800" },
    ];
  }, [libraryStats]);

  // Processing status pie chart
  const processingPieData = useMemo(() => {
    if (!workStatus) return [];
    return [
      { id: "processed", value: workStatus.processed_files, label: "Processed", color: "#4caf50" },
      { id: "pending", value: workStatus.pending_files, label: "Pending", color: "#ff9800" },
    ].filter(d => d.value > 0);
  }, [workStatus]);

  const hasPending = workStatus && workStatus.pending_files > 0;
  const isScanning = workStatus?.is_scanning ?? false;
  const progressPercent =
    progress && progress.totalFiles > 0
      ? Math.round((progress.processedCount / progress.totalFiles) * 100)
      : 0;

  return (
    <PageContainer title="Dashboard">
      {loading && <Typography sx={{ mt: 2 }}>Loading dashboard...</Typography>}
      {error && <ErrorMessage>Error: {error}</ErrorMessage>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          {/* Scanning Status - show when libraries are scanning */}
          {isScanning && workStatus?.scanning_libraries && (
            <Panel>
              <SectionHeader title="Scanning Libraries" />
              <Stack spacing={1}>
                {workStatus.scanning_libraries.map((lib) => (
                  <ProgressBar
                    key={lib.library_id}
                    label={lib.name}
                    value={lib.progress}
                    total={lib.total}
                    percentage={lib.total > 0 ? Math.round((lib.progress / lib.total) * 100) : 0}
                  />
                ))}
              </Stack>
            </Panel>
          )}

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
                  value={workStatus?.pending_files || 0}
                />
                <MetricCard
                  label="Processed"
                  value={workStatus?.processed_files || 0}
                />
              </ResponsiveGrid>
            </Panel>
          )}

          {/* Processing Summary with Chart */}
          <Panel>
            <SectionHeader title="Processing Summary" />
            {workStatus && (
              <Box sx={{ display: "flex", flexDirection: { xs: "column", md: "row" }, gap: 3 }}>
                {processingPieData.length > 0 && (
                  <Box sx={{ width: { xs: "100%", md: 200 }, height: 150 }}>
                    <PieChart
                      series={[
                        {
                          data: processingPieData,
                          innerRadius: 30,
                          outerRadius: 60,
                          paddingAngle: 2,
                          cornerRadius: 4,
                        },
                      ]}
                      height={150}
                      hideLegend
                    />
                  </Box>
                )}
                <Box sx={{ flex: 1 }}>
                  <ResponsiveGrid minWidth={150}>
                    <MetricCard label="Pending" value={workStatus.pending_files} />
                    <MetricCard label="Processed" value={workStatus.processed_files} />
                    <MetricCard label="Total Files" value={workStatus.total_files} />
                  </ResponsiveGrid>
                </Box>
              </Box>
            )}
          </Panel>

          {/* Library Stats with Chart */}
          <Panel>
            <SectionHeader title="Library Stats" />
            {libraryStats && (
              <Box sx={{ display: "flex", flexDirection: { xs: "column", md: "row" }, gap: 3 }}>
                <Box sx={{ width: { xs: "100%", md: 200 }, height: 150 }}>
                  <PieChart
                    series={[
                      {
                        data: libraryPieData,
                        innerRadius: 30,
                        outerRadius: 60,
                        paddingAngle: 2,
                        cornerRadius: 4,
                      },
                    ]}
                    height={150}
                    hideLegend
                  />
                </Box>
                <Box sx={{ flex: 1 }}>
                  <ResponsiveGrid minWidth={200}>
                    <MetricCard label="Total Files" value={libraryStats.total_files} />
                    <MetricCard label="Artists" value={libraryStats.unique_artists} />
                    <MetricCard label="Albums" value={libraryStats.unique_albums} />
                    <MetricCard
                      label="Total Duration"
                      value={formatTotalDuration(libraryStats.total_duration_seconds)}
                    />
                  </ResponsiveGrid>
                </Box>
              </Box>
            )}
          </Panel>

          {/* Recent Activity */}
          <Panel>
            <SectionHeader title="Recent Activity" />
            {recentFiles.length === 0 ? (
              <Typography color="text.secondary" fontStyle="italic">
                No recently processed tracks.
              </Typography>
            ) : (
              <List dense disablePadding>
                {recentFiles.map((file) => (
                  <ListItem key={file.file_id} disableGutters>
                    <ListItemIcon sx={{ minWidth: 36 }}>
                      <MusicNote color="action" fontSize="small" />
                    </ListItemIcon>
                    <ListItemText
                      primary={file.title || file.path.split("/").pop()}
                      secondary={`${file.artist || "Unknown"} • ${file.album || "Unknown"}`}
                      primaryTypographyProps={{ variant: "body2" }}
                      secondaryTypographyProps={{ variant: "caption" }}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {formatTimeAgo(file.last_tagged_at)}
                    </Typography>
                  </ListItem>
                ))}
              </List>
            )}
          </Panel>
        </Stack>
      )}
    </PageContainer>
  );
}
