/**
 * Hook for fetching and categorizing tag metadata from the backend.
 * Used by the playlist rules engine to populate tag dropdowns.
 *
 * Filters to only show relevant tags:
 * - Standard song tags (artist, album, year, genre, etc.)
 * - nom:mood-* tags (mood-loose, mood-regular, mood-strict)
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { getTagStats, type TagStatEntry } from "../../../shared/api/navidrome";

/** Standard song tags to include in the rules engine. */
const STANDARD_TAG_RELS = new Set([
  "artist",
  "artists",
  "album",
  "album_artist",
  "genre",
  "year",
  "date",
  "bpm",
  "composer",
  "label",
  "publisher",
  "title",
  "lyricist",
]);

/** Tags that should always be treated as numeric for comparisons. */
const FORCE_NUMERIC_TAG_RELS = new Set([
  "year",
  "bpm",
]);

/** Display-friendly labels for tag keys. */
const TAG_LABELS: Record<string, string> = {
  artist: "Artist",
  artists: "Artists",
  album: "Album",
  album_artist: "Album Artist",
  genre: "Genre",
  year: "Year",
  date: "Date",
  bpm: "BPM",
  composer: "Composer",
  label: "Label",
  publisher: "Publisher",
  title: "Title",
  lyricist: "Lyricist",
  "nom:mood-loose": "Mood (Loose)",
  "nom:mood-regular": "Mood (Regular)",
  "nom:mood-strict": "Mood (Strict)",
};

function isRelevantTag(key: string): boolean {
  return STANDARD_TAG_RELS.has(key) || key.startsWith("nom:mood-");
}

export interface TagMetaEntry extends TagStatEntry {
  label: string;
}

export interface UseTagMetadataResult {
  /** All relevant tags sorted by label */
  tags: TagMetaEntry[];
  /** Tags with type float or integer */
  numericTags: TagMetaEntry[];
  /** Tags with type string */
  stringTags: TagMetaEntry[];
  loading: boolean;
  error: string | null;
  /** Re-fetch tag metadata */
  reload: () => void;
}

export function useTagMetadata(): UseTagMetadataResult {
  const [rawTags, setRawTags] = useState<TagStatEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTags = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getTagStats();
      setRawTags(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tag metadata");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTags();
  }, [fetchTags]);

  const tags = useMemo(() => {
    return rawTags
      .filter((t) => isRelevantTag(t.key))
      .map((t) => ({
        ...t,
        type: FORCE_NUMERIC_TAG_RELS.has(t.key) ? "integer" : t.type,
        label: TAG_LABELS[t.key] ?? t.key,
      }))
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [rawTags]);

  const numericTags = useMemo(
    () => tags.filter((t) => t.type === "float" || t.type === "integer"),
    [tags],
  );

  const stringTags = useMemo(
    () => tags.filter((t) => t.type === "string"),
    [tags],
  );

  return { tags, numericTags, stringTags, loading, error, reload: fetchTags };
}
