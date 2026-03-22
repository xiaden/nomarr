/**
 * API key management endpoints.
 */
import { get, post } from "./client";

export interface ApiKeyResponse {
  api_key: string;
}

export async function getApiKey(): Promise<ApiKeyResponse> {
  return get<ApiKeyResponse>("/api/web/api-key");
}

export async function regenerateApiKey(): Promise<ApiKeyResponse> {
  return post<ApiKeyResponse>("/api/web/api-key/regenerate");
}
