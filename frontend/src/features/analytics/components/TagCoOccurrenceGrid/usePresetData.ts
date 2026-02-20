/**
 * Hook for fetching preset data based on selected preset type.
 * Handles genre, year, and mood tag value lookups.
 */

import { useCallback, useEffect, useState } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";
import { getMoodValues, getUniqueTagValues } from "../../../../shared/api/files";

import { PRESET_METADATA, type PresetId } from "./types";

export interface UsePresetDataResult {
  /** Resolved tag specs for the preset */
  tags: TagSpec[];
  /** Loading state */
  loading: boolean;
  /** Error message if fetch failed */
  error: string | null;
  /** Refetch the data */
  reload: () => void;
}

/**
 * Fetches tag values for a given preset.
 *
 * - genre: fetches unique genre values
 * - year: fetches unique year values
 * - mood: returns explicit nom:mood-* keys as boolean presence tags
 * - manual: returns empty array (user builds manually)
 */
export function usePresetData(presetId: PresetId): UsePresetDataResult {
  const [tags, setTags] = useState<TagSpec[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    const preset = PRESET_METADATA[presetId];
    const { fetchStrategy, maxValues } = preset;

    // Manual preset doesn't auto-fetch
    if (presetId === "manual") {
      setTags([]);
      setLoading(false);
      setError(null);
      return;
    }

    // Mood preset: fetch individual mood values from tuple strings
    if (fetchStrategy.moodValueLookup) {
      try {
        setLoading(true);
        setError(null);

        const moodTier = fetchStrategy.moodTier ?? "mood-strict";
        const response = await getMoodValues(moodTier, maxValues);

        // Build TagSpecs: key = "nom:mood-*" pattern, value = individual mood value
        // Backend will use CONTAINS matching on the mood tag tuple strings
        const moodTags: TagSpec[] = response.tag_keys.map((moodValue) => ({
          key: fetchStrategy.tagKey ?? "nom:mood-*",
          value: moodValue,
        }));

        setTags(moodTags);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load mood values"
        );
        setTags([]);
      } finally {
        setLoading(false);
      }
      return;
    }

    // Standard fetch for genre/year
    if (!fetchStrategy.tagKey) {
      setError("Invalid preset configuration");
      return;
    }

    try {
      setLoading(true);
      setError(null);

      const response = await getUniqueTagValues(
        fetchStrategy.tagKey,
        fetchStrategy.nomarrOnly
      );

      // Parse values preserving backend order (song_count DESC from API).
      // Use a seen set for dedup but an array to preserve insertion order.
      const seen = new Set<string>();
      const parsedValues: string[] = [];
      for (const value of response.tag_keys) {
        // Handle JSON array values (multi-value tags)
        if (value.startsWith("[") && value.endsWith("]")) {
          try {
            const parsed = JSON.parse(value) as unknown;
            if (Array.isArray(parsed)) {
              for (const v of parsed) {
                const s = String(v);
                if (!seen.has(s)) { seen.add(s); parsedValues.push(s); }
              }
            } else {
              if (!seen.has(value)) { seen.add(value); parsedValues.push(value); }
            }
          } catch {
            if (!seen.has(value)) { seen.add(value); parsedValues.push(value); }
          }
        } else {
          if (!seen.has(value)) { seen.add(value); parsedValues.push(value); }
        }
      }

      // For year preset: filter out placeholder/invalid years (< 1900).
      const filteredValues =
        presetId === "year"
          ? parsedValues.filter((v) => {
              const n = parseInt(v, 10);
              return !isNaN(n) && n >= 10;
            })
          : parsedValues;

      // Take the top maxValues (already sorted by song_count DESC by backend).
      const limitedValues = filteredValues.slice(0, maxValues);

      // Convert to TagSpecs
      const tagSpecs: TagSpec[] = limitedValues.map((value) => ({
        key: fetchStrategy.tagKey as string,
        value,
      }));

      setTags(tagSpecs);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load preset data"
      );
      setTags([]);
    } finally {
      setLoading(false);
    }
  }, [presetId]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return {
    tags,
    loading,
    error,
    reload: fetchData,
  };
}
