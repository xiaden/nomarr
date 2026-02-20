/**
 * Shared formatting utilities for durations and other display values.
 */

/**
 * Format a per-track duration (seconds) as M:SS.
 * Used wherever individual track lengths are displayed.
 */
export function formatTrackDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds <= 0) return "-";
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/**
 * Format a total collection duration (seconds) as "Xh Ym".
 * Used wherever aggregate library / playlist lengths are displayed.
 */
export function formatTotalDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}
