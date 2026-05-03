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
  return get("/api/web/metadata/count");
}

export interface ListEntitiesOptions {
  limit?: number;
  offset?: number;
  search?: string;
}

/**
 * List entities from a collection (artist, album, label, genre, year).
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
  return get(`/api/web/metadata/${collection}${query ? `?${query}` : ""}`);
}

/**
 * Get entity details by ID.
 */
export async function getEntity(
  collection: EntityCollection,
  entityId: string
): Promise<Entity> {
  return get(
    `/api/web/metadata/${collection}/${encodeURIComponent(entityId)}`
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
  name: string,
  options?: ListSongsOptions
): Promise<SongListResult> {
  const params = new URLSearchParams();
  params.append("name", name);
  if (options?.limit) params.append("limit", options.limit.toString());
  if (options?.offset) params.append("offset", options.offset.toString());

  return get(
    `/api/web/metadata/${collection}/${encodeURIComponent(entityId)}/song?${params.toString()}`
  );
}

export interface Album {
  entity_id: string;
  display_name: string;
  song_count?: number;
}

/**
 * List albums for an artist via traversal (artist→songs→albums).
 */
export async function listAlbumsForArtist(
  artistId: string,
  limit = 100
): Promise<Album[]> {
  const params = new URLSearchParams();
  params.append("limit", limit.toString());
  
  return get(
    `/api/web/metadata/artist/${encodeURIComponent(artistId)}/album?${params.toString()}`
  );
}
