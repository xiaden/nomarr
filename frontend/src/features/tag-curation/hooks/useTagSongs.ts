import { useCallback, useEffect, useState } from "react";

import type { TagSongItem } from "../../../shared/api/tagCuration";
import { fetchTagSongs } from "../../../shared/api/tagCuration";

interface UseTagSongsOptions {
  tagId: string | null;
  initialPageSize?: number;
}

export interface UseTagSongsResult {
  songs: TagSongItem[];
  total: number;
  loading: boolean;
  error: string | null;
  page: number;
  setPage: (page: number) => void;
  refetch: () => void;
}

export function useTagSongs({
  tagId,
  initialPageSize = 50,
}: UseTagSongsOptions): UseTagSongsResult {
  const [songs, setSongs] = useState<TagSongItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = initialPageSize;

  const load = useCallback(async () => {
    if (!tagId) {
      setSongs([]);
      setTotal(0);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const offset = page * pageSize;
      const result = await fetchTagSongs(tagId, pageSize, offset);
      setSongs(result.songs);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load songs");
    } finally {
      setLoading(false);
    }
  }, [tagId, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    songs,
    total,
    loading,
    error,
    page,
    setPage,
    refetch: load,
  };
}
