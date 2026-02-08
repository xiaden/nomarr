/**
 * Analytics tab - collection profile and insights.
 *
 * Uses accordion sections for:
 * - Collection Overview (stats, years, genres, artists)
 * - Mood Analysis (coverage, balance, vibes, combos)
 * - Advanced (tag frequencies, co-occurrence matrix)
 */

import { Box, Stack } from "@mui/material";
import { useState } from "react";

import { AdvancedAnalytics } from "./AdvancedAnalytics";
import { CollectionOverview } from "./CollectionOverview";
import { LibraryFilter } from "./LibraryFilter";
import { MoodAnalysis } from "./MoodAnalysis";

export function AnalyticsTab() {
  const [libraryId, setLibraryId] = useState<string | undefined>(undefined);

  return (
    <Stack spacing={0} sx={{ mt: 2 }}>
      <Box sx={{ mb: 2 }}>
        <LibraryFilter value={libraryId} onChange={setLibraryId} />
      </Box>
      <CollectionOverview libraryId={libraryId} />
      <MoodAnalysis libraryId={libraryId} />
      <AdvancedAnalytics libraryId={libraryId} />
    </Stack>
  );
}
