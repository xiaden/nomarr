/**
 * graph-adjacency.js - Build adjacency lists
 * Used by expansion, tracing, dead-code analysis
 */

/**
 * Build adjacency maps
 * Returns: { outgoing, incoming }
 */
export function buildAdjacency(graphModel) {
    const outgoing = new Map(); // nodeId -> Set<nodeId>
    const incoming = new Map(); // nodeId -> Set<nodeId>
    
    // Initialize all nodes
    graphModel.nodes.forEach(node => {
        outgoing.set(node.id, new Set());
        incoming.set(node.id, new Set());
    });
    
    // Build edges
    graphModel.edges.forEach(edge => {
        const out = outgoing.get(edge.source);
        const inc = incoming.get(edge.target);
        
        if (out) out.add(edge.target);
        if (inc) inc.add(edge.source);
    });
    
    return { outgoing, incoming };
}
