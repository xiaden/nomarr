/**
 * Hook for fetching and categorizing tag metadata from the backend.
 * Used by the playlist rules engine to populate tag dropdowns.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { getTagStats, type TagStatEntry } from "../../../shared/api/navidrome";

export interface UseTagMetadataResult {
  /** All tags sorted by key */
  tags: TagStatEntry[];
  /** Tags with type float or integer */
  numericTags: TagStatEntry[];
  /** Tags with type string */
  stringTags: TagStatEntry[];
  loading: boolean;
  error: string | null;
  /** Re-fetch tag metadata */
  reload: () => void;
}

export function useTagMetadata(): UseTagMetadataResult {
  const [tags, setTags] = useState<TagStatEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchTags = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await getTagStats();
      setTags(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tag metadata");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void fetchTags();
  }, [fetchTags]);

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
