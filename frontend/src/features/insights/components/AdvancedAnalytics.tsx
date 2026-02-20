/**
 * AdvancedAnalytics - Power user analytics section.
 *
 * Contains tag co-occurrence grid for power users.
 * Collapsed by default.
 */

import { AccordionSection } from "@shared/components/ui";

import { TagCoOccurrenceGrid } from "../../analytics/components/TagCoOccurrenceGrid";


interface AdvancedAnalyticsProps {
  /** Optional library ID to filter by */
  libraryId?: string;
}

export function AdvancedAnalytics({ libraryId }: AdvancedAnalyticsProps) {
  return (
    <AccordionSection
      sectionId="advanced"
      title="Advanced Analytics"
      defaultExpanded={false}
    >
      <TagCoOccurrenceGrid libraryId={libraryId} />
    </AccordionSection>
  );
}
