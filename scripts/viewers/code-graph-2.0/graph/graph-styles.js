/**
 * graph-styles.js - State → style mapping
 * Pure config, no graph calls
 */

export const LAYER_COLORS = {
    interfaces: '#3b82f6',
    services: '#8b5cf6',
    workflows: '#ec4899',
    components: '#f59e0b',
    persistence: '#10b981',
    helpers: '#6366f1',
    root: '#ef4444',
    other: '#6b7280'
};

export const NODE_STATES = {
    selected: {
        stroke: '#58a6ff',
        lineWidth: 4
    },
    dimmed: {
        opacity: 0.3
    },
    path: {
        stroke: '#fbbf24',
        lineWidth: 3
    },
    new: {
        stroke: '#7ee787',
        lineWidth: 3
    }
};

export const EDGE_STATES = {
    selected: {
        stroke: '#58a6ff',
        lineWidth: 3
    },
    dimmed: {
        opacity: 0.1
    },
    path: {
        stroke: '#fbbf24',
        lineWidth: 2
    }
};

/**
 * Get node color by layer
 */
export function getNodeColor(layer) {
    return LAYER_COLORS[layer] || LAYER_COLORS.other;
}
