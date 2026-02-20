/**
 * LibraryStats component.
 * Displays aggregate library statistics.
 */

import { MetricCard, Panel, ResponsiveGrid, SectionHeader } from "@shared/components/ui";
import { formatTotalDuration } from "@shared/utils/format";

interface LibraryStatsProps {
  stats: {
    total_files: number;
    unique_artists: number;
    unique_albums: number;
    total_duration_seconds: number;
  };
}

export function LibraryStats({ stats }: LibraryStatsProps) {
  const statItems = [
    { label: "Total Files", value: stats.total_files },
    { label: "Artists", value: stats.unique_artists },
    { label: "Albums", value: stats.unique_albums },
    { label: "Total Duration", value: formatTotalDuration(stats.total_duration_seconds) },
  ];

  return (
    <Panel>
      <SectionHeader title="Library Statistics" />
      <ResponsiveGrid minColumnWidth={200}>
        {statItems.map((item) => (
          <MetricCard
            key={item.label}
            label={item.label}
            value={item.value}
          />
        ))}
      </ResponsiveGrid>
    </Panel>
  );
}
