/**
 * Metadata entity API functions.
 */

import type {
    Entity,
    EntityCollection,
    EntityCounts,
    EntityListResult,
    SongListResult,
} from "../types";

import { get } from "./client";

/**
 * Get counts for all entity collections.
 */
export async function getCounts(): Promise<EntityCounts> {
  return get("/api/v1/metadata/counts");
}

export interface ListEntitiesOptions {
  limit?: number;
  offset?: number;
  search?: string;
}

/**
 * List entities from a collection (artists, albums, labels, genres, years).
 */
export async function listEntities(
  collection: EntityCollection,
  options?: ListEntitiesOptions
): Promise<EntityListResult> {
  const params = new URLSearchParams();
  if (options?.limit) params.append("limit", options.limit.toString());
  if (options?.offset) params.append("offset", options.offset.toString());
  if (options?.search) params.append("search", options.search);

  const query = params.toString();
  return get(`/api/v1/metadata/${collection}${query ? `?${query}` : ""}`);
}

/**
 * Get entity details by ID.
 */
export async function getEntity(
  collection: EntityCollection,
  entityId: string
): Promise<Entity> {
  return get(
    `/api/v1/metadata/${collection}/${encodeURIComponent(entityId)}`
  );
}

export interface ListSongsOptions {
  limit?: number;
  offset?: number;
}

/**
 * List songs for an entity.
 */
export async function listSongsForEntity(
  collection: EntityCollection,
  entityId: string,
  rel: string,
  options?: ListSongsOptions
): Promise<SongListResult> {
  const params = new URLSearchParams();
  params.append("rel", rel);
  if (options?.limit) params.append("limit", options.limit.toString());
  if (options?.offset) params.append("offset", options.offset.toString());

  return get(
    `/api/v1/metadata/${collection}/${encodeURIComponent(entityId)}/songs?${params.toString()}`
  );
}
