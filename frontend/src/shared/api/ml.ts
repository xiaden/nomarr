/**
 * ML management API functions.
 */

import { get, patch, post } from "./client";

export interface VramProbeResponse {
  status: string;
}

/**
 * A registered ML model vertex.
 */
export interface MlModel {
  id: string;
  backbone: string;
  head_type: string;
  model_stem: string;
  output_count: number;
  fully_configured: boolean;
  is_known: boolean;
  source: string;
}

/**
 * A single output activation for a model.
 */
export interface MlModelOutput {
  id: string;
  output_index: number;
  label: string | null;
  fully_labeled: boolean;
}

export interface UpdateLabelPayload {
  label: string;
}

export interface MarkConfiguredPayload {
  value: boolean;
}

/**
 * Return all registered ML model vertices with their configuration status.
 */
export async function listModels(): Promise<MlModel[]> {
  return get("/api/web/machine-learning/model");
}

/**
 * Return all output activation vertices for a model.
 */
export async function getModelOutputs(modelId: string): Promise<MlModelOutput[]> {
  return get(`/api/web/machine-learning/model/${modelId}/output`);
}

/**
 * Assign a human-readable label to a model output activation.
 */
export async function updateOutputLabel(
  modelId: string,
  outputId: string,
  payload: UpdateLabelPayload
): Promise<{ status: string }> {
  return patch(`/api/web/machine-learning/model/${modelId}/output/${outputId}`, payload);
}

/**
 * Set the fully_configured flag on a model.
 */
export async function markModelConfigured(
  modelId: string,
  payload: MarkConfiguredPayload
): Promise<{ status: string; fully_configured: string }> {
  return post(`/api/web/machine-learning/model/${modelId}/mark-configured`, payload);
}

/**
 * Schedule a re-run of the per-model VRAM probe.
 * Clears existing measurements so the next worker startup re-probes.
 */
export async function triggerVramProbe(): Promise<VramProbeResponse> {
  return post("/api/web/machine-learning/vram-probe");
}
