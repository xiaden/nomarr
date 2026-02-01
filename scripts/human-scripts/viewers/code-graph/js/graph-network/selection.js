/**
 * Selection and highlighting operations (state-based)
 */

import { NodeState, getNodeStyle } from './state-styles.js';

export function clearSelection(context) {
    if (context.network) {
        context.network.unselectAll();
        
        // Reset nodes to DEFAULT state (diff-based updates)
        const nodeUpdates = [];
        context.nodes.forEach(node => {
            // Only update if not already in DEFAULT state
            if (node.renderState !== NodeState.DEFAULT) {
                const styleUpdate = getNodeStyle(node, NodeState.DEFAULT);
                styleUpdate.renderState = NodeState.DEFAULT;
                nodeUpdates.push(styleUpdate);
            }
        });
        
        context.selectedNodeId = null;
        context.pathHighlight = null;
        context.updateEdgeVisibility();
        
        if (nodeUpdates.length > 0) {
            context.nodes.update(nodeUpdates);
        }
    }
}

export function highlightPath(context, pathHighlight) {
    if (!context.nodes || !context.network) {
        console.warn('Network not initialized, skipping path highlight');
        return;
    }
    
    context.pathHighlight = pathHighlight;
    
    // Update edge visibility (handles edge states)
    context.updateEdgeVisibility();
    
    // Get all visible node IDs
    const allVisibleNodes = new Set();
    context.nodes.forEach(node => allVisibleNodes.add(node.id));
    
    // Compute node states
    const nodeUpdates = [];
    
    if (pathHighlight && pathHighlight.foundPaths) {
        // Collect nodes connected to the selected node
        const connectedToSelected = new Set();
        if (context.selectedNodeId) {
            context.allEdges.forEach(edge => {
                if (edge.from === context.selectedNodeId) {
                    connectedToSelected.add(edge.to);
                }
                if (edge.to === context.selectedNodeId) {
                    connectedToSelected.add(edge.from);
                }
            });
        }
        
        // Determine state for each visible node (diff-based updates)
        // Priority: SELECTED > PATH > CONNECTED > DIMMED
        allVisibleNodes.forEach(nodeId => {
            const node = context.nodes.get(nodeId);
            if (!node) return;
            
            let newState;
            if (nodeId === context.selectedNodeId) {
                newState = NodeState.SELECTED;  // Selected wins over everything
            } else if (pathHighlight.nodeIds.has(nodeId)) {
                newState = NodeState.PATH;
            } else if (connectedToSelected.has(nodeId)) {
                newState = NodeState.CONNECTED;
            } else {
                newState = NodeState.DIMMED;
            }
            
            // Only update if state changed
            if (node.renderState !== newState) {
                const styleUpdate = getNodeStyle(node, newState);
                styleUpdate.renderState = newState;
                nodeUpdates.push(styleUpdate);
            }
        });
    } else {
        // No path highlighting - reset all to default (diff-based updates)
        allVisibleNodes.forEach(nodeId => {
            const node = context.nodes.get(nodeId);
            if (!node) return;
            
            const newState = (nodeId === context.selectedNodeId) 
                ? NodeState.SELECTED 
                : NodeState.DEFAULT;
            
            // Only update if state changed
            if (node.renderState !== newState) {
                const styleUpdate = getNodeStyle(node, newState);
                styleUpdate.renderState = newState;
                nodeUpdates.push(styleUpdate);
            }
        });
    }
    
    if (nodeUpdates.length > 0) {
        context.nodes.update(nodeUpdates);
    }
}

export function focusNode(context, nodeId, scale = 1.5) {
    if (context.network) {
        context.network.focus(nodeId, {
            scale: scale,
            animation: true
        });
    }
}
