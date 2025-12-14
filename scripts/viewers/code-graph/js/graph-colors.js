/**
 * Centralized color definitions for code graph visualization
 * All color assignments should reference these constants to ensure consistency
 */

export const LAYER_COLORS = {
    'interfaces': '#4ec9b0',
    'services': '#569cd6',
    'workflows': '#dcdcaa',
    'components': '#c586c0',
    'persistence': '#9cdcfe',
    'helpers': '#ce9178',
    'root': '#d16969',
    'other': '#858585'
};

export const HIGHLIGHT_COLORS = {
    'path': '#ff9800',           // Orange - path to entrypoint
    'selected': '#2196F3',       // Blue - selected node border
    'unreachable': '#757575',    // Gray - unreachable nodes
    'selectedInterface': '#FFD700'  // Gold - selected interface node
};

export const KIND_SHAPES = {
    'module': 'database',      // Cylinder (distinct!)
    'class': 'box',            // Rectangle
    'function': 'ellipse',     // Oval
    'method': 'circle'         // Circle
};

export const KIND_SIZES = {
    'module': 25,
    'class': 20,
    'function': 20,
    'method': 20
};
