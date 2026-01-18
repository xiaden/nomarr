/**
 * Insights page - combines analytics and Navidrome integration.
 *
 * Features:
 * - Tag frequency statistics and mood distribution (Analytics)
 * - Tag correlations and co-occurrence matrix (Analytics)  
 * - Navidrome config generation (Navidrome)
 * - Smart playlist generation for Navidrome (Navidrome)
 */

import { useState } from "react";

import { PageContainer, TabNav } from "@shared/components/ui";

import { AnalyticsTab } from "./components/AnalyticsTab";
import { NavidromeTab } from "./components/NavidromeTab";

export function InsightsPage() {
  const [activeTab, setActiveTab] = useState<"analytics" | "navidrome">("analytics");

  return (
    <PageContainer title="Insights">
      <TabNav
        tabs={[
          { id: "analytics", label: "Analytics" },
          { id: "navidrome", label: "Navidrome Integration" },
        ]}
        activeTab={activeTab}
        onTabChange={(id) => setActiveTab(id as "analytics" | "navidrome")}
      />

      {/* Tab Content */}
      {activeTab === "analytics" && <AnalyticsTab />}
      {activeTab === "navidrome" && <NavidromeTab />}
    </PageContainer>
  );
}