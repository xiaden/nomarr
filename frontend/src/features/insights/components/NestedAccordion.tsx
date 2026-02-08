/**
 * NestedAccordion - Accordion with localStorage persistence.
 *
 * Stores expansion state in localStorage using the provided storageKey.
 * State is persisted on toggle, not on unmount.
 */

import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";

const STORAGE_PREFIX = "nomarr:insights:accordion:";

interface NestedAccordionProps {
  /** Unique identifier for localStorage persistence */
  storageKey: string;
  /** Title displayed in accordion header */
  title: string;
  /** Whether accordion is expanded by default (when no stored state) */
  defaultExpanded?: boolean;
  /** Content rendered inside accordion */
  children: React.ReactNode;
  /** Optional subtitle or badge */
  secondary?: React.ReactNode;
}

export function NestedAccordion({
  storageKey,
  title,
  defaultExpanded = true,
  children,
  secondary,
}: NestedAccordionProps) {
  const fullKey = `${STORAGE_PREFIX}${storageKey}`;

  // Initialize from localStorage or default
  const [expanded, setExpanded] = useState(() => {
    try {
      const stored = localStorage.getItem(fullKey);
      if (stored !== null) {
        return stored === "true";
      }
    } catch {
      // Ignore localStorage errors
    }
    return defaultExpanded;
  });

  // Persist to localStorage on change
  const handleChange = useCallback(
    (_event: React.SyntheticEvent, isExpanded: boolean) => {
      setExpanded(isExpanded);
      try {
        localStorage.setItem(fullKey, String(isExpanded));
      } catch {
        // Ignore localStorage errors
      }
    },
    [fullKey]
  );

  // Sync with localStorage changes from other tabs
  useEffect(() => {
    const handleStorage = (e: StorageEvent) => {
      if (e.key === fullKey && e.newValue !== null) {
        setExpanded(e.newValue === "true");
      }
    };
    window.addEventListener("storage", handleStorage);
    return () => window.removeEventListener("storage", handleStorage);
  }, [fullKey]);

  return (
    <Accordion expanded={expanded} onChange={handleChange}>
      <AccordionSummary expandIcon={<ExpandMoreIcon />}>
        <Typography variant="h6" sx={{ flexGrow: 1 }}>
          {title}
        </Typography>
        {secondary}
      </AccordionSummary>
      <AccordionDetails>{children}</AccordionDetails>
    </Accordion>
  );
}
