/**
 * Frontend debug utility.
 *
 * Controlled via localStorage key `nomarr_debug`.
 * Enable:  localStorage.setItem('nomarr_debug', 'true')
 * Disable: localStorage.removeItem('nomarr_debug')
 *
 * Usage:
 *   import { isDebug, debugLog } from "@shared/utils/debug";
 *   debugLog("MyComponent", "someEvent", { detail: 123 });
 */

/** Check whether debug mode is active (reads localStorage each call). */
export function isDebug(): boolean {
  try {
    return localStorage.getItem("nomarr_debug") === "true";
  } catch {
    return false;
  }
}

/**
 * Log a message only when debug mode is active.
 *
 * @param tag   Component or subsystem name, e.g. "HistogramCharts"
 * @param msg   Short description of the event
 * @param data  Optional payload to dump alongside the message
 */
export function debugLog(tag: string, msg: string, data?: unknown): void {
  if (!isDebug()) return;
  if (data !== undefined) {
    console.debug(`[nomarr:${tag}]`, msg, data);
  } else {
    console.debug(`[nomarr:${tag}]`, msg);
  }
}
