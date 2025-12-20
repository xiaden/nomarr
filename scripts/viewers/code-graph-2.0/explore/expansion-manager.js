/**
 * expansion-manager.js - Track visible nodes and handle expansion
 * Just IDs. Never touches G6 directly.
 */

export class ExpansionManager {
    /**
     * @param {object} graphModel - { nodes, edges, entrypointIds }
     * @param {object} adjacency - { outgoing: Map, incoming: Map }
     */
    constructor(graphModel, adjacency) {
        this.graphModel = graphModel;
        this.adjacency = adjacency;
        this.visibleNodeIds = new Set(graphModel.entrypointIds);
        this.entrypointIds = new Set(graphModel.entrypointIds);
    }
    
    /**
     * Expand to show immediate neighbors
     * Returns array of newly added node IDs for streaming
     */
    expand(nodeId) {
        if (!this.visibleNodeIds.has(nodeId)) {
            console.warn(`Cannot expand ${nodeId}: not visible`);
            return { graph: this.getVisibleGraph(), added: [] };
        }
        
        const outgoing = this.adjacency.outgoing.get(nodeId) || new Set();
        const incoming = this.adjacency.incoming.get(nodeId) || new Set();
        
        // Collect newly added nodes
        const added = [];
        [...outgoing, ...incoming].forEach(id => {
            if (!this.visibleNodeIds.has(id)) {
                added.push(id);
                this.visibleNodeIds.add(id);
            }
        });
        
        return { graph: this.getVisibleGraph(), added };
    }
    
    /**
     * Get filtered graph with only visible nodes/edges
     */
    getVisibleGraph() {
        const nodes = this.graphModel.nodes.filter(n => this.visibleNodeIds.has(n.id));
        const edges = this.graphModel.edges.filter(e => 
            this.visibleNodeIds.has(e.source) && this.visibleNodeIds.has(e.target)
        );
        return { nodes, edges };
    }
    
    /**
     * Reset to entrypoints only
     */
    reset() {
        this.visibleNodeIds = new Set(this.entrypointIds);
        return this.getVisibleGraph();
    }
    
    /**
     * Show all nodes
     */
    showAll() {
        this.visibleNodeIds = new Set(this.graphModel.nodes.map(n => n.id));
        return this.getVisibleGraph();
    }
    
    /**
     * Get stats for toolbar
     */
    getStats() {
        return {
            visible: this.visibleNodeIds.size,
            total: this.graphModel.nodes.length
        };
    }
    
    /**
     * Get node data by ID
     */
    getNode(nodeId) {
        return this.graphModel.nodes.find(n => n.id === nodeId);
    }
    
    /**
     * Get connections for a node
     */
    getConnections(nodeId) {
        const outgoing = Array.from(this.adjacency.outgoing.get(nodeId) || [])
            .map(id => this.getNode(id))
            .filter(Boolean);
        const incoming = Array.from(this.adjacency.incoming.get(nodeId) || [])
            .map(id => this.getNode(id))
            .filter(Boolean);
        return { incoming, outgoing };
    }
}
