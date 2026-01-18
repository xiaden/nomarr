/**
 * Analytics tab - tag statistics and insights.
 */

import { Alert, CircularProgress, Stack } from "@mui/material";

import { MoodDistributionView } from "../../analytics/components/MoodDistributionView";
import { TagCoOccurrence } from "../../analytics/components/TagCoOccurrence";
import { TagFrequenciesTable } from "../../analytics/components/TagFrequenciesTable";
import { useAnalyticsData } from "../../analytics/hooks/useAnalyticsData";

export function AnalyticsTab() {
  const { data, loading, error } = useAnalyticsData();

  return (
    <>
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          <MoodDistributionView data={data.moodDistribution} />
          <TagFrequenciesTable data={data.tagFrequencies} />
          <TagCoOccurrence />
        </Stack>
      )}
    </>
  );
}