/**
 * guards.js - Runtime safety checks
 */

/* global G6 */

/**
 * Assert G6 v5 is loaded
 */
export function assertG6Version() {
    if (!window.G6) {
        throw new Error('G6 is not loaded');
    }
    
    if (!G6.version || !G6.version.startsWith('5.')) {
        throw new Error(`G6 v5 required, found: ${G6.version || 'unknown'}`);
    }
}

/**
 * Detect v4 API usage patterns (intern insurance)
 * Note: v5 also has graph.render() but with different semantics - this is valid.
 */
export function detectV4Usage(graph) {
    // Check for v4-style modes config (v5 uses behaviors array)
    const options = graph.getOptions ? graph.getOptions() : {};
    if (options.modes && typeof options.modes === 'object' && !Array.isArray(options.modes)) {
        console.warn('⚠️ V4 pattern detected: modes config object. V5 uses behaviors array.');
    }
    
    // Check for v4-style defaultNode/defaultEdge (v5 uses node/edge)
    if (options.defaultNode || options.defaultEdge) {
        console.warn('⚠️ V4 pattern detected: defaultNode/defaultEdge. V5 uses node/edge config.');
    }
}

/**
 * Check for edge ID collisions
 */
export function checkEdgeIdCollisions(edges) {
    const ids = new Set();
    const collisions = [];
    
    edges.forEach(edge => {
        if (ids.has(edge.id)) {
            collisions.push(edge.id);
        }
        ids.add(edge.id);
    });
    
    if (collisions.length > 0) {
        console.warn(`⚠️ Edge ID collisions detected:`, collisions);
    }
    
    return collisions.length === 0;
}
