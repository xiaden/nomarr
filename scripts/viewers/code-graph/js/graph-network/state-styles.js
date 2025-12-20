/**
 * State-based styling system for nodes and edges
 * 
 * Philosophy: Separate state (what) from presentation (how).
 * - State: The semantic condition of a node/edge (selected, dimmed, etc.)
 * - Style: The visual properties derived from that state
 * 
 * This eliminates the need to "restore" properties - we just recompute styles from current state.
 */

import { HIGHLIGHT_COLORS, LAYER_COLORS } from '../graph-colors.js';

/**
 * Node states
 */
export const NodeState = {
    DEFAULT: 'default',      // Normal visible node
    SELECTED: 'selected',    // User clicked this node
    PATH: 'path',           // Part of path to entrypoint
    CONNECTED: 'connected',  // Connected to selected node
    DIMMED: 'dimmed'        // Background node (not in current focus)
};

/**
 * Edge states
 */
export const EdgeState = {
    DEFAULT: 'default',      // Normal visible edge
    PATH: 'path',           // Part of path to entrypoint
    SELECTED: 'selected',    // Connected to selected node
    DIMMED: 'dimmed'        // Background edge (not in current focus)
};

/**
 * Get complete node style based on state
 * @param {Object} node - Node data object
 * @param {string} state - NodeState value
 * @returns {Object} Complete style object for vis.js
 */
export function getNodeStyle(node, state) {
    const baseColor = getNodeColor(node);
    // Always get original properties from node.data (set by graph-filters.js)
    // This prevents losing data when DataSet properties get modified by previous updates
    const originalLabel = node.data?.name || node.name || node.label || node.id;
    
    // Get original color from graph-filters.js creation, NOT from potentially modified node.color
    // graph-filters.js stores the color object with highlight property
    const originalColor = node.data ? {
        background: getNodeColor(node.data),
        border: node.data.color?.border || '#ffffff',
        highlight: node.data.color?.highlight || {
            background: HIGHLIGHT_COLORS.selectedInterface,
            border: '#ffffff'
        }
    } : node.color;

    // Preserve original node properties - only override what we need to change per state
    const baseUpdate = {
        id: node.id,
        label: originalLabel
    };

    switch (state) {
    case NodeState.SELECTED:
        return {
            ...baseUpdate,
            borderWidth: 4,
            color: {
                ...originalColor,  // Preserve original color object (including highlight)
                border: HIGHLIGHT_COLORS.selected
                // Keep original background - don't overwrite!
            },
            opacity: 1.0,
            level: 0,
            font: {
                size: undefined,
                color: undefined,
                background: undefined
            },
            widthConstraint: false,  // Clear size lock from DIMMED
            heightConstraint: false
        };

    case NodeState.PATH:
        return {
            ...baseUpdate,
            borderWidth: 4,
            color: {
                ...originalColor,
                border: HIGHLIGHT_COLORS.path
                // Keep original background - don't overwrite!
            },
            opacity: 1.0,
            level: 0,
            font: {
                size: undefined,
                color: undefined,
                background: undefined
            },
            widthConstraint: false,  // Clear size lock from DIMMED
            heightConstraint: false
        };

    case NodeState.CONNECTED:
        return {
            ...baseUpdate,
            borderWidth: 2,
            color: {
                ...originalColor
                // Keep original colors - connected nodes should still be recognizable
            },
            opacity: 1.0,
            level: 5,
            font: {
                size: undefined,
                color: undefined,
                background: undefined
            },
            widthConstraint: false,  // Clear size lock from DIMMED
            heightConstraint: false
        };

    case NodeState.DIMMED: {
        const nodeSize = node.size || 25;
        // Always use original label from node.data to prevent label loss
        const originalLabel = node.data?.name || node.name || node.label || node.id;
        return {
            id: node.id,
            borderWidth: 2,
            color: {
                border: baseColor,
                background: baseColor
            },
            opacity: 0.08,
            level: 10,
            label: originalLabel,  // Keep original label but make it invisible with font
            font: {
                size: 1,  // Tiny but not 0 (0 can persist in vis.js)
                color: 'transparent',
                background: 'transparent'
            },
            widthConstraint: { minimum: nodeSize, maximum: nodeSize },
            heightConstraint: { minimum: nodeSize, maximum: nodeSize }
        };
    }

    case NodeState.DEFAULT:
    default:
        return {
            ...baseUpdate,
            borderWidth: 2,
            color: originalColor,  // Restore original color completely
            opacity: 1.0,
            level: undefined,
            font: {
                size: undefined,
                color: undefined,
                background: undefined
            },
            widthConstraint: false,
            heightConstraint: false
        };
    }
}

/**
 * Get complete edge style based on state
 * @param {Object} edge - Edge data object
 * @param {string} state - EdgeState value
 * @param {boolean} isVisible - Whether edge should be visible
 * @returns {Object} Complete style object for vis.js
 */
export function getEdgeStyle(edge, state, isVisible) {
    const baseStyle = {
        id: edge.id,
        hidden: !isVisible,
        label: edge.label || edge.type,
        font: {},  // Use global defaults
        level: undefined
    };

    switch (state) {
    case EdgeState.PATH:
        return {
            ...baseStyle,
            color: HIGHLIGHT_COLORS.path,
            width: 3,
            level: 0,
            font: {
                background: 'rgba(0, 0, 0, 0.7)'  // Dark background for path labels to be visible
            }
        };

    case EdgeState.SELECTED:
        return {
            ...baseStyle,
            color: edge.color || '#666666',
            width: edge.width || 1,
            level: 0,
            font: {
                background: 'rgba(0, 0, 0, 0.7)'  // Dark background for selected edge labels
            }
        };

    case EdgeState.DIMMED: {
        const baseColor = edge.color || '#666666';
        const dimmedColor = typeof baseColor === 'string'
            ? { color: baseColor, opacity: 0.08 }
            : { ...baseColor, opacity: 0.08 };

        return {
            id: edge.id,
            hidden: !isVisible,
            color: dimmedColor,
            width: edge.width || 1,
            level: 10,
            label: '',  // Completely hide label
            font: {
                size: 0,
                color: 'transparent',
                background: 'transparent',
                strokeWidth: 0
            }
        };
    }

    case EdgeState.DEFAULT:
    default:
        return {
            ...baseStyle,
            color: edge.color || '#666666',
            width: edge.width || 1,
            label: '',  // Hide labels in default state to prevent overlap
            font: {
                size: undefined,  // Use global default
                color: undefined,  // Use global default
                background: 'transparent',  // Explicitly no dark background
                strokeWidth: 0
            }
        };
    }
}

/**
 * Get node color based on layer and reachability
 */
function getNodeColor(node) {
    if (node.reachable_from_interface === false) {
        return HIGHLIGHT_COLORS.unreachable;
    }
    return LAYER_COLORS[node.layer] || LAYER_COLORS.other;
}
