/**
 * AdvancedAnalytics - Power user analytics section.
 *
 * Contains tag co-occurrence matrix for power users.
 * Collapsed by default.
 */

import { TagCoOccurrence } from "../../analytics/components/TagCoOccurrence";

import { AccordionSection } from "./AccordionSection";

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
      <TagCoOccurrence libraryId={libraryId} />
    </AccordionSection>
  );
}
