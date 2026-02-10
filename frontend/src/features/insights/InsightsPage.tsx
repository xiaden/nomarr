/**
 * Insights page - library analytics.
 *
 * Features:
 * - Tag frequency statistics and mood distribution
 * - Tag correlations and co-occurrence matrix
 */

import { PageContainer } from "@shared/components/ui";

import { AnalyticsTab } from "./components/AnalyticsTab";

export function InsightsPage() {
  return (
    <PageContainer title="Insights">
      <AnalyticsTab />
    </PageContainer>
  );
}
