/**
 * collapse-manager.js - Remove nodes and prune orphans
 * Explicitly protects entrypoints.
 */

export class CollapseManager {
    /**
     * @param {object} graphModel - { nodes, edges, entrypointIds }
     * @param {object} adjacency - { outgoing: Map, incoming: Map }
     * @param {ExpansionManager} expansionManager
     */
    constructor(graphModel, adjacency, expansionManager) {
        this.graphModel = graphModel;
        this.adjacency = adjacency;
        this.expansionManager = expansionManager;
        this.entrypointIds = new Set(graphModel.entrypointIds);
    }
    
    /**
     * Collapse a node and prune orphans
     */
    collapse(nodeId) {
        // Never collapse entrypoints
        if (this.entrypointIds.has(nodeId)) {
            console.warn(`Cannot collapse ${nodeId}: is entrypoint`);
            return this.expansionManager.getVisibleGraph();
        }
        
        // Remove the node
        this.expansionManager.visibleNodeIds.delete(nodeId);
        
        // Prune orphans (nodes with 0 visible degree)
        const pruned = this._pruneOrphans();
        
        return this.expansionManager.getVisibleGraph();
    }
    
    /**
     * Remove orphaned nodes (0 visible connections, not entrypoints)
     * 
     * Optimized for performance:
     * - Early-exit when finding any visible neighbor (avoids Array.from/filter)
     * - Collect orphans first, delete after iteration (avoid mutation during iteration)
     * - Cascade prune iteratively until no more orphans found
     * 
     * Edge consistency: ExpansionManager.getVisibleGraph() deterministically rebuilds
     * edges from visibleNodeIds, ensuring no dangling edges remain after pruning.
     */
    _pruneOrphans() {
        let totalPruned = 0;
        const visibleIds = this.expansionManager.visibleNodeIds;
        
        // Cascade prune until no more orphans found
        let changed = true;
        while (changed) {
            changed = false;
            const toRemove = [];
            
            // Collect orphans (don't mutate Set during iteration)
            for (const nodeId of visibleIds) {
                // Skip entrypoints - they are never orphans
                if (this.entrypointIds.has(nodeId)) continue;
                
                // Check if node has any visible neighbors (early-exit for performance)
                const hasVisibleNeighbor = this._hasVisibleNeighbor(nodeId, visibleIds);
                
                if (!hasVisibleNeighbor) {
                    toRemove.push(nodeId);
                }
            }
            
            // Remove orphans after iteration
            if (toRemove.length > 0) {
                toRemove.forEach(id => visibleIds.delete(id));
                totalPruned += toRemove.length;
                changed = true;
            }
        }
        
        return totalPruned;
    }
    
    /**
     * Check if node has any visible neighbor (early-exit)
     * More efficient than Array.from/filter for large graphs
     */
    _hasVisibleNeighbor(nodeId, visibleIds) {
        const outgoing = this.adjacency.outgoing.get(nodeId);
        if (outgoing) {
            for (const neighborId of outgoing) {
                if (visibleIds.has(neighborId)) return true;
            }
        }
        
        const incoming = this.adjacency.incoming.get(nodeId);
        if (incoming) {
            for (const neighborId of incoming) {
                if (visibleIds.has(neighborId)) return true;
            }
        }
        
        return false;
    }
}
