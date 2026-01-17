/**
 * Tags/Inspect API functions.
 */

import { del, get } from "./client";

export interface ShowTagsResponse {
  path: string;
  namespace: string;
  tags: Record<string, unknown>;
  count: number;
}

/**
 * Read tags from an audio file.
 */
export async function showTags(path: string): Promise<ShowTagsResponse> {
  return get(`/api/web/tags/show-tags?path=${encodeURIComponent(path)}`);
}

export interface RemoveTagsResponse {
  path: string;
  namespace: string;
  removed: number;
}

/**
 * Remove all namespaced tags from an audio file.
 */
export async function removeTags(path: string): Promise<RemoveTagsResponse> {
  return del(`/api/web/tags/remove-tags?path=${encodeURIComponent(path)}`);
}
