/**
 * CollectionOverview - Main accordion section for collection statistics.
 *
 * Shows library stats, year/genre/artist distributions in nested subsections.
 */

import { Alert, CircularProgress, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import type { CollectionOverviewResponse } from "../../../shared/api/analytics";
import { getCollectionOverview } from "../../../shared/api/analytics";

import { AccordionSection } from "./AccordionSection";
import { GenreDistribution } from "./GenreDistribution";
import { LibraryStats } from "./LibraryStats";
import { YearDistribution } from "./YearDistribution";

interface CollectionOverviewProps {
  /** Optional library ID to filter by */
  libraryId?: string;
}

export function CollectionOverview({ libraryId }: CollectionOverviewProps) {
  const [data, setData] = useState<CollectionOverviewResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true);
        setError(null);
        const result = await getCollectionOverview(libraryId);
        setData(result);
      } catch (err) {
        setError(
          err instanceof Error
            ? err.message
            : "Failed to load collection overview"
        );
        console.error("[CollectionOverview] Load error:", err);
      } finally {
        setLoading(false);
      }
    };

    loadData();
  }, [libraryId]);

  if (loading) {
    return (
      <AccordionSection
        sectionId="collection-overview"
        title="Collection Overview"
      >
        <CircularProgress size={24} />
      </AccordionSection>
    );
  }

  if (error || !data) {
    return (
      <AccordionSection
        sectionId="collection-overview"
        title="Collection Overview"
      >
        <Alert severity="error">
          {error || "Failed to load collection overview"}
        </Alert>
      </AccordionSection>
    );
  }

  const trackCount = data.stats.file_count.toLocaleString();

  return (
    <AccordionSection
      sectionId="collection-overview"
      title="Collection Overview"
      secondary={
        <Typography variant="body2" color="text.secondary">
          {trackCount} tracks
        </Typography>
      }
    >
      <LibraryStats stats={data.stats} parentId="collection-overview" />
      <YearDistribution
        distribution={data.year_distribution}
        parentId="collection-overview"
      />
      <GenreDistribution
        distribution={data.genre_distribution}
        parentId="collection-overview"
      />
    </AccordionSection>
  );
}
