/**
 * Hook for fetching preset data based on selected preset type.
 * Handles genre, year, and mood tag value lookups.
 */

import { useCallback, useEffect, useState } from "react";

import type { TagSpec } from "../../../../shared/api/analytics";
import { getUniqueTagValues } from "../../../../shared/api/files";

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

    // Mood preset uses explicit keys
    if (presetId === "mood" && fetchStrategy.explicitKeys) {
      // For mood tags, we treat each key as a "presence" indicator
      // The value is a placeholder since we're checking if the tag exists
      const moodTags: TagSpec[] = fetchStrategy.explicitKeys.map((key) => ({
        key,
        value: "*", // Wildcard - any value means "has this mood tag"
      }));
      setTags(moodTags.slice(0, maxValues));
      setLoading(false);
      setError(null);
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

      // Parse values and build TagSpecs
      const parsedValues = new Set<string>();
      for (const value of response.tag_keys) {
        // Handle JSON array values (multi-value tags)
        if (value.startsWith("[") && value.endsWith("]")) {
          try {
            const parsed = JSON.parse(value) as unknown;
            if (Array.isArray(parsed)) {
              for (const v of parsed) {
                parsedValues.add(String(v));
              }
            } else {
              parsedValues.add(value);
            }
          } catch {
            parsedValues.add(value);
          }
        } else {
          parsedValues.add(value);
        }
      }

      // Sort and limit to maxValues
      const sortedValues = Array.from(parsedValues).sort();
      const limitedValues = sortedValues.slice(0, maxValues);

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
