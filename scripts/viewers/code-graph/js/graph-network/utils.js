/**
 * Utility methods for network operations
 */

import { HIGHLIGHT_COLORS, LAYER_COLORS } from '../graph-colors.js';

export function fit(context) {
    if (context.network) {
        context.network.fit({ animation: true });
    }
}

export function getNodeColor(node) {
    // Unreachable nodes are gray
    if (node.reachable_from_interface === false) {
        return HIGHLIGHT_COLORS.unreachable;
    }
    
    return LAYER_COLORS[node.layer] || LAYER_COLORS.other;
}

export function getSelectedNodes(context) {
    return context.network ? context.network.getSelectedNodes() : [];
}

export function getStats(context) {
    if (!context.network) {
        return { nodes: 0, edges: 0 };
    }
    return {
        nodes: context.nodes.getIds().length,
        edges: context.edges.getIds().length
    };
}

export function destroy(context) {
    if (context.network) {
        context.network.destroy();
        context.network = null;
    }
}
