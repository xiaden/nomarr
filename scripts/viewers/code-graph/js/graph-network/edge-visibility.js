/**
 * Edge visibility management (state-based)
 */

import { EdgeState, getEdgeStyle } from './state-styles.js';

export function updateEdgeVisibility(context) {
    if (!context.edges || context.allEdges.length === 0) return;

    // Calculate in-degree for each node
    const inDegree = new Map();
    context.allEdges.forEach(edge => {
        inDegree.set(edge.to, (inDegree.get(edge.to) || 0) + 1);
    });

    // Categorize edges
    const pathEdges = [];
    const selectedEdges = [];
    const otherEdges = [];

    context.allEdges.forEach(edge => {
        // Priority 1: Path to entrypoint edges (use edge.id for correct matching)
        if (context.pathHighlight && context.pathHighlight.edgeIds.has(edge.id)) {
            pathEdges.push(edge);
        }
        // Priority 2: Selected node edges
        else if (context.selectedNodeId && 
            (edge.from === context.selectedNodeId || edge.to === context.selectedNodeId)) {
            selectedEdges.push(edge);
        } 
        // Priority 3: Other edges
        else {
            otherEdges.push(edge);
        }
    });

    // Sort other edges by noisiness
    otherEdges.sort((a, b) => {
        const degreeA = inDegree.get(a.to) || 0;
        const degreeB = inDegree.get(b.to) || 0;
        return degreeA - degreeB;
    });

    // Determine how many other edges we can show
    const usedBudget = pathEdges.length + selectedEdges.length;
    const remainingBudget = Math.max(0, context.maxVisibleEdges - usedBudget);
    const visibleOtherEdges = otherEdges.slice(0, remainingBudget);

    // Build set of visible edges
    const visibleEdges = [...pathEdges, ...selectedEdges, ...visibleOtherEdges];
    const visibleEdgeIds = new Set(visibleEdges.map(e => e.id));

    // Compute edge states and apply styles (diff-based updates)
    const edgeUpdates = [];
    
    context.allEdges.forEach(edge => {
        const isVisible = visibleEdgeIds.has(edge.id);
        // Use edge.id directly for path matching (handles multiple edges between same nodes)
        const isPathEdge = context.pathHighlight && context.pathHighlight.edgeIds.has(edge.id);
        const isSelected = context.selectedNodeId && 
            (edge.from === context.selectedNodeId || edge.to === context.selectedNodeId);
        
        const shouldDim = context.pathHighlight && context.pathHighlight.foundPaths && !isPathEdge && !isSelected;
        
        // Determine new edge state
        let newState;
        if (isPathEdge) {
            newState = EdgeState.PATH;
        } else if (isSelected) {
            newState = EdgeState.SELECTED;
        } else if (shouldDim) {
            newState = EdgeState.DIMMED;
        } else {
            newState = EdgeState.DEFAULT;
        }
        
        // Get current edge data from DataSet to check previous state
        const currentEdge = context.edges.get(edge.id);
        const oldState = currentEdge?.renderState;
        const oldVisibility = currentEdge?.hidden === false;
        
        // Only update if state or visibility changed
        if (oldState !== newState || oldVisibility !== isVisible) {
            const styleUpdate = getEdgeStyle(edge, newState, isVisible);
            styleUpdate.renderState = newState;  // Store state on edge
            edgeUpdates.push(styleUpdate);
        }
    });

    if (edgeUpdates.length > 0) {
        context.edges.update(edgeUpdates);
    }
}
