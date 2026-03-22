import type { TagSpec } from "../../../../shared/api/analytics";
import { getMoodValues, getUniqueTagValues } from "../../../../shared/api/files";

import { PRESET_METADATA, type PresetId } from "./types";

/**
 * Fetches tag values for a given preset.
 *
 * - genre: fetches unique genre values
 * - year: fetches unique year values
 * - mood: fetches mood values and maps them to nom:mood-strict key tags
 * - manual: returns empty array (user builds manually)
 *
 * Throws on fetch error — caller is responsible for error handling.
 */
export async function fetchPresetTags(presetId: PresetId): Promise<TagSpec[]> {
  const preset = PRESET_METADATA[presetId];
  const { fetchStrategy, maxValues } = preset;

  // Manual preset doesn't auto-fetch
  if (presetId === "manual") {
    return [];
  }

  // Mood preset: fetch individual mood values from tuple strings
  if (fetchStrategy.moodValueLookup) {
    const moodTier = fetchStrategy.moodTier ?? "mood-strict";
    const response = await getMoodValues(moodTier, maxValues);

    return response.tag_keys.map((moodValue) => ({
      key: fetchStrategy.tagKey ?? "nom:mood-strict",
      value: moodValue,
    }));
  }

  // Standard fetch for genre/year
  if (!fetchStrategy.tagKey) {
    throw new Error("Invalid preset configuration");
  }

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
  return limitedValues.map((value) => ({
    key: fetchStrategy.tagKey as string,
    value,
  }));
}
