/**
 * useAnalyticsData - Hook to load analytics data
 */

import { useEffect, useState } from "react";

import { api } from "../../../shared/api";

export interface TagFrequency {
  tag_key: string;
  total_count: number;
  unique_values: number;
}

export interface MoodDistribution {
  mood: string;
  count: number;
  percentage: number;
}

export interface AnalyticsData {
  tagFrequencies: TagFrequency[];
  moodDistribution: MoodDistribution[];
}

export function useAnalyticsData() {
  const [data, setData] = useState<AnalyticsData>({
    tagFrequencies: [],
    moodDistribution: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const loadAnalytics = async () => {
      try {
        setLoading(true);
        setError(null);

        const [tagFreqData, moodData] = await Promise.all([
          api.analytics.getTagFrequencies(50),
          api.analytics.getMoodDistribution(),
        ]);

        setData({
          tagFrequencies: tagFreqData.tag_frequencies,
          moodDistribution: moodData.mood_distribution,
        });
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load analytics"
        );
        console.error("[Analytics] Load error:", err);
      } finally {
        setLoading(false);
      }
    };

    loadAnalytics();
  }, []);

  return { data, loading, error };
}
