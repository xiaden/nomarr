/**
 * API module exports.
 *
 * Import domain functions directly:
 *   import { listJobs, getQueueStatus } from "@/shared/api/queue";
 *   import { list, create } from "@/shared/api/library";
 *
 * Or import from index for convenience:
 *   import { listJobs, list } from "@/shared/api";
 */

// Re-export all domain modules
export * from "./analytics";
export * from "./auth";
export * from "./calibration";
export * from "./filesystem";
export * from "./metadata";
export * from "./queue";
export * from "./tags";
export * from "./worker";

// Library - explicit exports to avoid conflicts with files module
export {
    cleanupOrphanedTags, create, deleteLibrary, getDefault, getFileTags, getLibrary, getStats,
    list,
    scan, setDefault, update, type CleanupTagsResult, type CreateLibraryPayload, type FileTagsResult, type LibraryStats,
    type UpdateLibraryPayload
} from "./library";

// Files - explicit exports to avoid conflicts
export {
    getTagValues, getUniqueTagKeys, getUniqueTagValues, search, type FileTag,
    type LibraryFile,
    type SearchFilesParams,
    type SearchFilesResponse, type TagValuesResponse, type UniqueTagKeysResponse
} from "./files";

// Config - export with original name
export { getConfig, updateConfig, type UpdateConfigResponse } from "./config";

// Navidrome - rename getConfig to avoid conflict
export {
    generatePlaylist, generateTemplates, getConfig as getNavidromeConfig, getPreview as getNavidromePreview, getTemplates, previewPlaylist, type GeneratePlaylistParams,
    type GeneratePlaylistResponse, type GenerateTemplatesResponse, type GeneratedTemplate, type GetTemplatesResponse, type NavidromeConfigResponse, type NavidromePreviewResponse, type NavidromeTag, type PlaylistTemplate
} from "./navidrome";

// Re-export client utilities
export { API_BASE_URL, ApiError, snakeToCamel } from "./client";

