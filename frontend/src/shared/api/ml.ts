/**
 * ML management API functions.
 */

import { post } from "./client";

export interface VramProbeResponse {
  status: string;
}

/**
 * Schedule a re-run of the per-model VRAM probe.
 * Clears existing measurements so the next worker startup re-probes.
 */
export async function triggerVramProbe(): Promise<VramProbeResponse> {
  return post("/api/web/ml/vram-probe");
}
