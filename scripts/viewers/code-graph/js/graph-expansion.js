/**
 * Progressive disclosure expansion/collapse logic for graph exploration
 */

/**
 * Expansion manager - tracks visible nodes and handles expand/collapse
 */
export class ExpansionManager {
    constructor(allNodes, allEdges, entrypointIds) {
        this.allNodes = new Map(allNodes.map(n => [n.id, n]));
        this.allEdges = allEdges;
        this.visibleNodeIds = new Set();
        this.expandedNodeIds = new Set();
        this.entrypointIds = entrypointIds || new Set();
        
        console.log('ExpansionManager initialized with:', allNodes.length, 'nodes,', allEdges.length, 'edges');
        console.log('Entrypoint IDs to look for:', Array.from(this.entrypointIds));
        console.log('Sample node IDs:', Array.from(this.allNodes.keys()).slice(0, 5));
        
        // Build adjacency for fast neighbor lookup
        this.adjacency = new Map();
        allNodes.forEach(node => this.adjacency.set(node.id, { incoming: new Set(), outgoing: new Set() }));
        
        allEdges.forEach(edge => {
            if (this.adjacency.has(edge.from)) {
                this.adjacency.get(edge.from).outgoing.add(edge.to);
            }
            if (this.adjacency.has(edge.to)) {
                this.adjacency.get(edge.to).incoming.add(edge.from);
            }
        });
    }
    
    /**
     * Initialize with entrypoint nodes only
     * @returns {Object} { nodes, edges }
     */
    initializeEntrypoints() {
        console.log('initializeEntrypoints: Looking for entrypoints in', this.allNodes.size, 'nodes');
        const entrypoints = Array.from(this.allNodes.values()).filter(node => {
            const matches = this.entrypointIds.has(node.id);
            if (matches) console.log('Found entrypoint node:', node.id);
            return matches;
        });
        
        console.log('Found', entrypoints.length, 'entrypoint nodes');
        
        entrypoints.forEach(node => {
            this.visibleNodeIds.add(node.id);
        });
        
        return this.getVisibleGraph();
    }
    
    /**
     * Expand a node - show all directly connected neighbors
     * @param {string} nodeId
     * @returns {Object} { newNodes, newEdges } - only the newly visible items
     */
    expandNode(nodeId) {
        console.log('expandNode called for:', nodeId);
        console.log('Already expanded?', this.expandedNodeIds.has(nodeId));
        
        if (this.expandedNodeIds.has(nodeId)) {
            return { newNodes: [], newEdges: [] };
        }
        
        this.expandedNodeIds.add(nodeId);
        const neighbors = this.adjacency.get(nodeId);
        if (!neighbors) {
            console.log('No neighbors found for', nodeId);
            return { newNodes: [], newEdges: [] };
        }
        
        console.log('Node has', neighbors.incoming.size, 'incoming and', neighbors.outgoing.size, 'outgoing connections');
        
        const newNodeIds = new Set();
        const allConnected = new Set([...neighbors.incoming, ...neighbors.outgoing]);
        console.log('Total connected neighbors:', allConnected.size);
        
        allConnected.forEach(neighborId => {
            if (!this.visibleNodeIds.has(neighborId)) {
                this.visibleNodeIds.add(neighborId);
                newNodeIds.add(neighborId);
            }
        });
        
        console.log('New neighbors to add:', newNodeIds.size, '(some were already visible)');
        
        const newNodes = Array.from(newNodeIds).map(id => this.allNodes.get(id)).filter(Boolean);
        const newEdges = this.allEdges.filter(edge => 
            (edge.from === nodeId && newNodeIds.has(edge.to)) ||
            (edge.to === nodeId && newNodeIds.has(edge.from)) ||
            (newNodeIds.has(edge.from) && this.visibleNodeIds.has(edge.to)) ||
            (newNodeIds.has(edge.to) && this.visibleNodeIds.has(edge.from))
        );
        
        return { newNodes, newEdges };
    }
    
    /**
     * Collapse a node - remove it and orphaned neighbors
     * @param {string} nodeId
     * @returns {Object} { removedNodeIds, removedEdgeIds }
     */
    collapseNode(nodeId) {
        const node = this.allNodes.get(nodeId);
        if (!node || this.entrypointIds.has(nodeId)) {
            return { removedNodeIds: [], removedEdgeIds: [] };  // Can't collapse entrypoints
        }
        
        this.visibleNodeIds.delete(nodeId);
        this.expandedNodeIds.delete(nodeId);
        
        // Find nodes that are now orphaned
        const orphanedNodes = new Set();
        for (const [id, adj] of this.adjacency.entries()) {
            if (!this.visibleNodeIds.has(id)) continue;
            if (this.entrypointIds.has(id)) continue;  // Never orphan entrypoints
            
            // Check if this node has any connections to remaining visible nodes
            const hasConnection = [...adj.incoming, ...adj.outgoing].some(connId => 
                this.visibleNodeIds.has(connId) && connId !== nodeId
            );
            
            if (!hasConnection) {
                orphanedNodes.add(id);
            }
        }
        
        // Remove orphaned nodes
        orphanedNodes.forEach(id => {
            this.visibleNodeIds.delete(id);
            this.expandedNodeIds.delete(id);
        });
        
        const removedNodeIds = [nodeId, ...orphanedNodes];
        const removedEdgeIds = this.allEdges
            .filter(edge => removedNodeIds.includes(edge.from) || removedNodeIds.includes(edge.to))
            .map(edge => edge.id);
        
        return { removedNodeIds, removedEdgeIds };
    }
    
    /**
     * Trace all paths from nodeId to any entrypoint (cycle-safe)
     * @param {string} nodeId
     * @param {Function} progressCallback - called with (current, total, percentage)
     * @returns {Object} { pathNodeIds, pathEdgeIds }
     */
    tracePaths(nodeId, progressCallback = null) {
        const pathNodeIds = new Set([nodeId]);
        const pathEdgeIds = new Set();
        const visited = new Set();
        const queue = [nodeId];
        
        let processed = 0;
        const estimatedTotal = this.adjacency.get(nodeId)?.incoming.size || 1;
        
        while (queue.length > 0) {
            const current = queue.shift();
            if (visited.has(current)) continue;
            visited.add(current);
            processed++;
            
            if (progressCallback) {
                const progress = Math.min(100, Math.round((processed / Math.max(estimatedTotal, processed)) * 100));
                progressCallback(processed, Math.max(estimatedTotal, processed), progress);
            }
            
            if (this.entrypointIds.has(current) && current !== nodeId) {
                // Found path to entrypoint, don't traverse further from here
                continue;
            }
            
            const neighbors = this.adjacency.get(current);
            if (!neighbors) continue;
            
            // Trace backwards (incoming edges)
            for (const incoming of neighbors.incoming) {
                if (!visited.has(incoming)) {
                    pathNodeIds.add(incoming);
                    queue.push(incoming);
                    
                    // Add edge
                    const edge = this.allEdges.find(e => e.from === incoming && e.to === current);
                    if (edge) pathEdgeIds.add(edge.id);
                }
            }
        }
        
        return {
            pathNodeIds: Array.from(pathNodeIds),
            pathEdgeIds: Array.from(pathEdgeIds)
        };
    }
    
    /**
     * Get current visible graph
     * @returns {Object} { nodes, edges }
     */
    getVisibleGraph() {
        const nodes = Array.from(this.visibleNodeIds)
            .map(id => this.allNodes.get(id))
            .filter(Boolean);
        
        const edges = this.allEdges.filter(edge =>
            this.visibleNodeIds.has(edge.from) && this.visibleNodeIds.has(edge.to)
        );
        
        return { nodes, edges };
    }
    
    /**
     * Check if a node can be expanded (has hidden neighbors)
     * @param {string} nodeId
     * @returns {number} Count of hidden neighbors
     */
    getHiddenNeighborCount(nodeId) {
        if (this.expandedNodeIds.has(nodeId)) return 0;
        
        const neighbors = this.adjacency.get(nodeId);
        if (!neighbors) return 0;
        
        const allConnected = new Set([...neighbors.incoming, ...neighbors.outgoing]);
        return Array.from(allConnected).filter(id => !this.visibleNodeIds.has(id)).length;
    }
}
