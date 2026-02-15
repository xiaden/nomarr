/**
 * API module exports.
 *
 * Import domain functions directly:
 *   import { getProcessingStatus } from "@/shared/api/processing";
 *   import { list, create } from "@/shared/api/library";
 *
 * Or import from index for convenience:
 *   import { getProcessingStatus, list } from "@/shared/api";
 */

// Re-export all domain modules
export * from "./analytics";
export * from "./auth";
export * from "./calibration";
export * from "./filesystem";
export * from "./metadata";
export * from "./processing";
export * from "./tags";
export * from "./worker";
export * from "./vectors";

// Library - explicit exports to avoid conflicts with files module
export {
    cleanupOrphanedTags, create, deleteLibrary, getFileTags, getLibrary, getReconcileStatus, getStats,
    list, reconcileTags,
    scan, update, updateWriteMode,
    type CleanupTagsResult, type CreateLibraryPayload, type FileTagsResult, type LibraryStats,
    type ReconcileStatusResult, type ReconcileTagsResult, type UpdateLibraryPayload, type UpdateWriteModeResult
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
    generatePlaylist, generateTemplates, getConfig as getNavidromeConfig, getPreview as getNavidromePreview, getTagStats, getTagValues as getNavidromeTagValues, getTemplates, previewPlaylist, type GeneratePlaylistParams,
    type GeneratePlaylistResponse, type GenerateTemplatesResponse, type GeneratedTemplate, type GetTemplatesResponse, type NavidromeConfigResponse, type NavidromePreviewResponse, type NavidromeTag, type PlaylistPreviewResponse, type PlaylistTemplate, type TagStatEntry
} from "./navidrome";

// Re-export client utilities
export { API_BASE_URL, ApiError, snakeToCamel } from "./client";

