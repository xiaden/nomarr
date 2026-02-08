/**
 * MoodAnalysis - Main accordion section for mood statistics.
 *
 * Shows mood coverage, balance, top pairs, and dominant vibes.
 */

import { Alert, CircularProgress, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import type { MoodAnalysisResponse } from "../../../shared/api/analytics";
import { getMoodAnalysis } from "../../../shared/api/analytics";

import { AccordionSection } from "./AccordionSection";
import { DominantVibes } from "./DominantVibes";
import { MoodBalance } from "./MoodBalance";
import { MoodCombos } from "./MoodCombos";
import { MoodCoverage } from "./MoodCoverage";

interface MoodAnalysisProps {
  /** Optional library ID to filter by */
  libraryId?: string;
}

export function MoodAnalysis({ libraryId }: MoodAnalysisProps) {
  const [data, setData] = useState<MoodAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await getMoodAnalysis(libraryId);
        setData(result);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load mood analysis"
        );
        console.error("[MoodAnalysis] Load error:", err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [libraryId]);

  if (loading) {
    return (
      <AccordionSection sectionId="mood-analysis" title="Mood Analysis">
        <CircularProgress size={24} />
      </AccordionSection>
    );
  }

  if (error || !data) {
    return (
      <AccordionSection sectionId="mood-analysis" title="Mood Analysis">
        <Alert severity="error">
          {error || "Failed to load mood analysis"}
        </Alert>
      </AccordionSection>
    );
  }

  // Calculate overall coverage for badge
  const strictCoverage = data.coverage.tiers["strict"]?.percentage ?? 0;

  return (
    <AccordionSection
      sectionId="mood-analysis"
      title="Mood Analysis"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {strictCoverage.toFixed(0)}% strict coverage
        </Typography>
      }
    >
      <MoodCoverage coverage={data.coverage} parentId="mood-analysis" />
      <DominantVibes vibes={data.dominant_vibes} parentId="mood-analysis" />
      <MoodBalance balance={data.balance} parentId="mood-analysis" />
      <MoodCombos pairs={data.top_pairs} parentId="mood-analysis" />
    </AccordionSection>
  );
}
