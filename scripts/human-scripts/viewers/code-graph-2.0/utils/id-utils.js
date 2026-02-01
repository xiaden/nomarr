/**
 * id-utils.js - ID generation utilities
 */

/**
 * Generate unique edge ID
 */
export function generateEdgeId(source, target, type, index) {
    return `edge_${source}_${target}_${type}_${index}`;
}

/**
 * Validate node ID
 */
export function isValidNodeId(id) {
    return typeof id === 'string' && id.length > 0;
}

/**
 * Validate edge ID
 */
export function isValidEdgeId(id) {
    return typeof id === 'string' && id.length > 0;
}
