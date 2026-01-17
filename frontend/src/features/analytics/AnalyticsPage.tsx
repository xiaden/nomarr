/**
 * Analytics page.
 *
 * Features:
 * - Tag frequency statistics
 * - Mood distribution
 * - Tag correlations
 * - Tag co-occurrence matrix
 */

import { Alert, CircularProgress, Stack } from "@mui/material";

import { PageContainer } from "@shared/components/ui";

import { MoodDistributionView } from "./components/MoodDistributionView";
import { TagCoOccurrence } from "./components/TagCoOccurrence";
import { TagFrequenciesTable } from "./components/TagFrequenciesTable";
import { useAnalyticsData } from "./hooks/useAnalyticsData";

export function AnalyticsPage() {
  const { data, loading, error } = useAnalyticsData();

  return (
    <PageContainer title="Analytics">
      {loading && <CircularProgress />}
      {error && <Alert severity="error">Error: {error}</Alert>}

      {!loading && !error && (
        <Stack spacing={2.5}>
          <MoodDistributionView data={data.moodDistribution} />
          <TagFrequenciesTable data={data.tagFrequencies} />
          <TagCoOccurrence />
        </Stack>
      )}
    </PageContainer>
  );
}
