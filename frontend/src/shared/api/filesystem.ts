/**
 * Filesystem API functions.
 */

import { get } from "./client";

export interface FsEntry {
  name: string;
  is_dir: boolean;
}

export interface FsListResponse {
  path: string;
  entries: FsEntry[];
}

/**
 * List directory contents relative to library root.
 *
 * @param path - Relative path from library root (undefined or empty string for root)
 * @returns Directory listing with entries (directories first, alphabetically sorted)
 * @throws ApiError on invalid path, directory traversal, or path not found
 */
export async function listFs(path?: string): Promise<FsListResponse> {
  const queryParams = new URLSearchParams();
  if (path) {
    queryParams.append("path", path);
  }

  const query = queryParams.toString();
  const endpoint = query ? `/api/web/fs/list?${query}` : "/api/web/fs/list";

  return get(endpoint);
}
