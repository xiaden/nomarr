/**
 * MoodAnalysis - Main accordion section for mood statistics.
 *
 * Shows mood coverage, balance, top pairs, and dominant vibes.
 * Includes a mood tier selector that filters the top pairs query.
 */

import {
  Alert,
  CircularProgress,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  type SelectChangeEvent,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import type { MoodAnalysisResponse } from "../../../shared/api/analytics";
import { getMoodAnalysis } from "../../../shared/api/analytics";

import { AccordionSection } from "./AccordionSection";
import { DominantVibes } from "./DominantVibes";
import { MoodCombos } from "./MoodCombos";
import { MoodCoverage } from "./MoodCoverage";

const MOOD_TIERS = [
  { value: "strict", label: "Strict" },
  { value: "regular", label: "Regular" },
  { value: "loose", label: "Loose" },
] as const;

interface MoodAnalysisProps {
  /** Optional library ID to filter by */
  libraryId?: string;
}

export function MoodAnalysis({ libraryId }: MoodAnalysisProps) {
  const [data, setData] = useState<MoodAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [moodTier, setMoodTier] = useState("strict");

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await getMoodAnalysis(libraryId, moodTier);
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
  }, [libraryId, moodTier]);

  const handleTierChange = (event: SelectChangeEvent<string>) => {
    setMoodTier(event.target.value);
  };

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
      <MoodCoverage coverage={data.coverage} balance={data.balance} parentId="mood-analysis" />
      <DominantVibes vibes={data.dominant_vibes} parentId="mood-analysis" />
      <MoodCombos
        pairs={data.top_pairs}
        parentId="mood-analysis"
        tierSelector={
          <FormControl
            size="small"
            sx={{ minWidth: 120 }}
            onClick={(e) => e.stopPropagation()}
          >
            <InputLabel id="mood-tier-label">Tier</InputLabel>
            <Select
              labelId="mood-tier-label"
              id="mood-tier-select"
              value={moodTier}
              label="Tier"
              onChange={handleTierChange}
            >
              {MOOD_TIERS.map((tier) => (
                <MenuItem key={tier.value} value={tier.value}>
                  {tier.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>
        }
      />
    </AccordionSection>
  );
}
