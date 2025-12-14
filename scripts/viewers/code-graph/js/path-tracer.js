/**
 * Module for tracing paths from nodes to entrypoints
 */

export class PathTracer {
    constructor(graphLoader) {
        this.graphLoader = graphLoader;
        this.reverseEdges = new Map();  // target_id -> [{source_id, type, ast_case}, ...]
        this.entrypoints = new Set();
        this.buildReverseEdges();
        this.findEntrypoints();
    }

    /**
     * Build reverse edge map for backward traversal
     */
    buildReverseEdges() {
        const REACHABLE_EDGE_TYPES = new Set([
            'CALLS', 'CALLS_FUNCTION', 'CALLS_METHOD', 'CALLS_CLASS',
            'CALLS_ATTRIBUTE', 'CALLS_DEPENDENCY', 'CALLS_THREAD_TARGET',
            'USES_TYPE', 'IMPORTS'
        ]);

        this.reverseEdges.clear();
        
        this.graphLoader.graphData.edges.forEach(edge => {
            if (REACHABLE_EDGE_TYPES.has(edge.type)) {
                if (!this.reverseEdges.has(edge.target_id)) {
                    this.reverseEdges.set(edge.target_id, []);
                }
                this.reverseEdges.get(edge.target_id).push({
                    sourceId: edge.source_id,
                    type: edge.type,
                    astCase: edge.ast_case || 'Unknown'
                });
            }
        });
    }

    /**
     * Find interface entrypoint nodes
     */
    findEntrypoints() {
        this.entrypoints.clear();
        
        this.graphLoader.graphData.nodes.forEach(node => {
            const nodeId = node.id;
            
            // API entrypoint
            if (nodeId === 'nomarr.interfaces.api.api_app') {
                this.entrypoints.add(nodeId);
            }
            
            // CLI entrypoints
            if (nodeId.startsWith('nomarr.interfaces.cli.') && 
                (nodeId.endsWith('.main') || nodeId.includes('.cmd_'))) {
                this.entrypoints.add(nodeId);
            }
            
            // Worker entrypoints
            if (nodeId.includes('.run') && nodeId.includes('Worker')) {
                this.entrypoints.add(nodeId);
            }
        });
    }

    /**
     * Find all paths from target node to entrypoints using BFS
     * @param {string} targetId - Node ID to start from
     * @param {number} maxPaths - Maximum number of paths to find
     * @param {number} maxDepth - Maximum path depth
     * @param {string|null} limitToEntrypoint - If set, only find paths to this specific entrypoint
     * @returns {Array} Array of paths, each path is array of {nodeId, edgeType, astCase}
     */
    findPathsToEntrypoints(targetId, maxPaths = 5, maxDepth = 50, limitToEntrypoint = null) {
        // Determine which entrypoints to search for
        const targetEntrypoints = limitToEntrypoint 
            ? new Set([limitToEntrypoint])
            : this.entrypoints;
        
        // Early exit if already an entrypoint
        if (targetEntrypoints.has(targetId)) {
            return [[{nodeId: targetId, edgeType: null, astCase: null}]];
        }
        
        const queue = [[{nodeId: targetId, edgeType: null, astCase: null}]];
        const visited = new Set([targetId]);  // Track visited nodes globally to prevent re-exploration
        const foundPaths = [];
        let iterations = 0;
        const maxIterations = 10000;  // Safety limit

        while (queue.length > 0 && foundPaths.length < maxPaths && iterations++ < maxIterations) {
            const path = queue.shift();
            const current = path[0];

            // Skip if path too long
            if (path.length > maxDepth) {
                continue;
            }

            // Explore parents (nodes that call/use this node)
            const parents = this.reverseEdges.get(current.nodeId) || [];
            for (const parent of parents) {
                // Skip if this parent is already in the current path (cycle detection)
                const inCurrentPath = path.some(p => p.nodeId === parent.sourceId);
                if (inCurrentPath) {
                    continue;
                }

                // Build new path (parent at front)
                const newPath = [
                    {nodeId: parent.sourceId, edgeType: parent.type, astCase: parent.astCase},
                    ...path
                ];
                
                // Found an entrypoint!
                if (targetEntrypoints.has(parent.sourceId)) {
                    foundPaths.push(newPath);
                    continue;
                }
                
                // Only explore further if we haven't visited this node yet
                // This prevents exponential explosion while still finding multiple paths
                if (!visited.has(parent.sourceId)) {
                    visited.add(parent.sourceId);
                    queue.push(newPath);
                }
            }
        }

        if (iterations >= maxIterations) {
            console.warn(`Path search hit iteration limit for node ${targetId}`);
        }

        return foundPaths;
    }

    /**
     * Get all nodes and edges involved in paths to entrypoints
     * @param {string} targetId - Node ID to trace from
     * @param {number} maxPaths - Maximum paths to find
     * @param {string|null} limitToEntrypoint - If set, only find paths to this specific entrypoint
     * @returns {Object} {nodeIds: Set, edgeIds: Set, paths: Array}
     */
    getPathHighlight(targetId, maxPaths = 5, limitToEntrypoint = null) {
        if (!targetId || !this.graphLoader || !this.graphLoader.graphData) {
            console.warn('Invalid state for path tracing');
            return { nodeIds: new Set(), edgeIds: new Set(), paths: [], foundPaths: false };
        }
        
        const paths = this.findPathsToEntrypoints(targetId, maxPaths, 50, limitToEntrypoint);
        const nodeIds = new Set();
        const edgeIds = new Set();

        // Extract all nodes and edges from all paths
        paths.forEach((path, pathIndex) => {
            path.forEach(step => {
                nodeIds.add(step.nodeId);
            });

            // Build edge IDs from path
            for (let i = 0; i < path.length - 1; i++) {
                const from = path[i].nodeId;
                const to = path[i + 1].nodeId;
                // Edge ID format: from->to (vis.js will match by from/to)
                edgeIds.add(`${from}->${to}`);
            }
        });

        return { nodeIds, edgeIds, paths, foundPaths: paths.length > 0 };
    }

    /**
     * Check if a node is reachable from any entrypoint
     * @param {string} nodeId
     * @returns {boolean}
     */
    isReachable(nodeId) {
        const node = this.graphLoader.graphData.nodes.find(n => n.id === nodeId);
        return node ? node.reachable_from_interface : false;
    }
}
