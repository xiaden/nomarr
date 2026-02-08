/**
 * AccordionSubsection - Inner level accordion subsection.
 *
 * Used for collapsible content within an AccordionSection.
 * Lighter styling than outer sections.
 */

import { Box } from "@mui/material";

import { NestedAccordion } from "./NestedAccordion";

interface AccordionSubsectionProps {
  /** Unique identifier for localStorage persistence */
  subsectionId: string;
  /** Parent section ID (for namespacing) */
  parentId: string;
  /** Subsection title */
  title: string;
  /** Whether expanded by default */
  defaultExpanded?: boolean;
  /** Subsection content */
  children: React.ReactNode;
  /** Optional subtitle/badge in header */
  secondary?: React.ReactNode;
}

export function AccordionSubsection({
  subsectionId,
  parentId,
  title,
  defaultExpanded = true,
  children,
  secondary,
}: AccordionSubsectionProps) {
  // Namespace subsection key under parent
  const storageKey = `${parentId}:${subsectionId}`;

  return (
    <Box sx={{ mb: 1 }}>
      <NestedAccordion
        storageKey={storageKey}
        title={title}
        defaultExpanded={defaultExpanded}
        secondary={secondary}
      >
        {children}
      </NestedAccordion>
    </Box>
  );
}
