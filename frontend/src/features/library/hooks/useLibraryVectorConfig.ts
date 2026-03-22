import { useCallback, useEffect, useRef, useState } from "react";

import {
  getLibraryVectorConfig,
  updateLibraryVectorConfig,
  type VectorConfigResponse,
  type VectorConfigUpdate,
} from "../../../shared/api/library";

export function useLibraryVectorConfig(libraryId: string | null) {
  const [config, setConfig] = useState<VectorConfigResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loadConfig = useCallback(async () => {
    if (!libraryId) return;
    try {
      setLoading(true);
      setError(null);
      const data = await getLibraryVectorConfig(libraryId);
      setConfig(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load vector config");
    } finally {
      setLoading(false);
    }
  }, [libraryId]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const updateConfig = useCallback(
    (update: VectorConfigUpdate) => {
      if (!libraryId) return;

      // Update local state immediately for responsive UI
      setConfig((prev) =>
        prev
          ? {
              ...prev,
              vector_group_size: update.vector_group_size ?? prev.vector_group_size,
              vector_search_thoroughness:
                update.vector_search_thoroughness ?? prev.vector_search_thoroughness,
              is_group_size_inherited: update.vector_group_size === null,
              is_thoroughness_inherited: update.vector_search_thoroughness === null,
            }
          : prev,
      );

      // Debounce API call
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(async () => {
        try {
          setSaving(true);
          const result = await updateLibraryVectorConfig(libraryId, update);
          setConfig(result);
        } catch (err) {
          setError(err instanceof Error ? err.message : "Failed to save vector config");
        } finally {
          setSaving(false);
        }
      }, 400);
    },
    [libraryId],
  );

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    };
  }, []);

  return { config, loading, saving, error, updateConfig, reload: loadConfig };
}
