import { useCallback, useState } from "react";

import type {
  MergeResult,
  RenameResult,
  SplitResult,
  UpdateFileTagsResult,
} from "../../../shared/api/tagCuration";
import {
  mergeTags,
  renameTag,
  splitTag,
  updateFileTags as updateFileTagsApi,
} from "../../../shared/api/tagCuration";

interface UseCurationActionsOptions {
  onSuccess?: () => void;
}

export interface UseCurationActionsResult {
  rename: (tagId: string, newValue: string) => Promise<RenameResult>;
  merge: (
    sourceTagIds: string[],
    canonicalTagId: string
  ) => Promise<MergeResult>;
  split: (
    sourceTagId: string,
    songIds: string[],
    newValue: string
  ) => Promise<SplitResult>;
  updateFileTags: (
    fileId: string,
    rel: string,
    values: string[]
  ) => Promise<UpdateFileTagsResult>;
  loading: boolean;
  error: string | null;
}

export function useCurationActions({
  onSuccess,
}: UseCurationActionsOptions = {}): UseCurationActionsResult {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wrap = useCallback(
    async <T>(action: () => Promise<T>): Promise<T> => {
      setLoading(true);
      setError(null);
      try {
        const result = await action();
        onSuccess?.();
        return result;
      } catch (err) {
        const message = err instanceof Error ? err.message : "Action failed";
        setError(message);
        throw err;
      } finally {
        setLoading(false);
      }
    },
    [onSuccess]
  );

  const rename = useCallback(
    (tagId: string, newValue: string) =>
      wrap(() => renameTag(tagId, newValue)),
    [wrap]
  );

  const merge = useCallback(
    (sourceTagIds: string[], canonicalTagId: string) =>
      wrap(() => mergeTags(sourceTagIds, canonicalTagId)),
    [wrap]
  );

  const split = useCallback(
    (sourceTagId: string, songIds: string[], newValue: string) =>
      wrap(() => splitTag(sourceTagId, songIds, newValue)),
    [wrap]
  );

  const updateFileTags = useCallback(
    (fileId: string, rel: string, values: string[]) =>
      wrap(() => updateFileTagsApi(fileId, rel, values)),
    [wrap]
  );

  return {
    rename,
    merge,
    split,
    updateFileTags,
    loading,
    error,
  };
}
