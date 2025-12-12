/**
 * Analytics page.
 *
 * Features:
 * - Tag frequency statistics
 * - Mood distribution
 * - Tag correlations
 * - Tag co-occurrence matrix
 */

import { MoodDistributionView } from "./components/MoodDistributionView";
import { TagCoOccurrence } from "./components/TagCoOccurrence";
import { TagFrequenciesTable } from "./components/TagFrequenciesTable";
import { useAnalyticsData } from "./hooks/useAnalyticsData";

export function AnalyticsPage() {
  const { data, loading, error } = useAnalyticsData();

  return (
    <div style={{ padding: "20px" }}>
      <h1 style={{ marginBottom: "20px" }}>Analytics</h1>

      {loading && <p>Loading analytics data...</p>}
      {error && <p style={{ color: "var(--accent-red)" }}>Error: {error}</p>}

      {!loading && !error && (
        <div style={{ display: "grid", gap: "20px" }}>
          <MoodDistributionView data={data.moodDistribution} />
          <TagFrequenciesTable data={data.tagFrequencies} />
          <TagCoOccurrence />
        </div>
      )}
    </div>
  );
}
