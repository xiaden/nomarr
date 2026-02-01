/**
 * path-tracer.js - Trace paths from nodes to entrypoints
 * BFS/DFS with cycle detection, progress callbacks.
 */

export class PathTracer {
    /**
     * @param {object} adjacency - { outgoing: Map, incoming: Map }
     */
    constructor(adjacency) {
        this.adjacency = adjacency;
        console.log('✓ PathTracer initialized');
    }
    
    /**
     * Trace backward from nodeId to any entrypoints
     * @param {string} nodeId
     * @param {Set} entrypointIds
     * @returns {Set} - All node IDs on paths
     */
    traceToEntrypoints(nodeId, entrypointIds) {
        const onPath = new Set();
        const visited = new Set();
        const queue = [nodeId];
        
        while (queue.length > 0) {
            const current = queue.shift();
            
            if (visited.has(current)) continue;
            visited.add(current);
            onPath.add(current);
            
            // Stop at entrypoints
            if (entrypointIds.has(current)) continue;
            
            // Add incoming neighbors
            const incoming = this.adjacency.incoming.get(current) || new Set();
            for (const parent of incoming) {
                if (!visited.has(parent)) {
                    queue.push(parent);
                }
            }
        }
        
        return onPath;
    }
}
