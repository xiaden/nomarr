/**
 * AccordionSection - Outer level accordion section.
 *
 * Provides consistent styling for top-level sections like
 * "Collection Overview", "Mood Analysis", "Advanced".
 */

import { Box, Paper } from "@mui/material";

import { NestedAccordion } from "./NestedAccordion";

interface AccordionSectionProps {
  /** Unique identifier for localStorage persistence */
  sectionId: string;
  /** Section title */
  title: string;
  /** Whether expanded by default */
  defaultExpanded?: boolean;
  /** Section content */
  children: React.ReactNode;
  /** Optional subtitle/badge in header */
  secondary?: React.ReactNode;
}

export function AccordionSection({
  sectionId,
  title,
  defaultExpanded = true,
  children,
  secondary,
}: AccordionSectionProps) {
  return (
    <Paper elevation={1} sx={{ mb: 2 }}>
      <NestedAccordion
        storageKey={sectionId}
        title={title}
        defaultExpanded={defaultExpanded}
        secondary={secondary}
      >
        <Box sx={{ px: 1 }}>{children}</Box>
      </NestedAccordion>
    </Paper>
  );
}
