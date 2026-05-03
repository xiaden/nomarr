import { useCallback, useEffect, useState } from "react";

import type { TagListResult, TagValueItem } from "../../../shared/api/tagCuration";
import { fetchTagValues } from "../../../shared/api/tagCuration";

interface UseTagValuesOptions {
  name?: string;
  prefix?: string;
  initialPageSize?: number;
}

export interface UseTagValuesResult {
  rows: TagValueItem[];
  total: number;
  loading: boolean;
  error: string | null;
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  setPageSize: (size: number) => void;
  refetch: () => void;
}

export function useTagValues({
  name,
  prefix,
  initialPageSize = 100,
}: UseTagValuesOptions = {}): UseTagValuesResult {
  const [rows, setRows] = useState<TagValueItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState(initialPageSize);

  useEffect(() => {
    setPage(0);
  }, [name, prefix]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const offset = page * pageSize;
      const result: TagListResult = await fetchTagValues(name, prefix, pageSize, offset);
      setRows(result.tags);
      setTotal(result.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load tag values");
    } finally {
      setLoading(false);
    }
  }, [name, prefix, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  return {
    rows,
    total,
    loading,
    error,
    page,
    setPage,
    pageSize,
    setPageSize,
    refetch: load,
  };
}
