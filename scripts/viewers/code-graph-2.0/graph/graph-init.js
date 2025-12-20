/**
 * graph-init.js - Create G6 Graph instance
 * 50-100 lines max
 */

/* global G6 */

import { detectV4Usage } from '../utils/guards.js';
import { EDGE_STATES, LAYER_COLORS, NODE_STATES } from './graph-styles.js';

/**
 * Initialize G6 graph
 */
export function initGraph(container) {
    const graph = new G6.Graph({
        container,
        width: container.offsetWidth,
        height: container.offsetHeight,
        
        // Layout (continuous force simulation)
        layout: {
            type: 'force',
            preventOverlap: true,
            nodeSize: 30,              // Node size for collision detection (diameter)
            nodeSpacing: 20,           // Minimum spacing between node edges
            nodeStrength: 1000,        // Node charge for Coulomb repulsion (positive = repulsion, docs are wrong)
            edgeStrength: 200,         // Edge attraction strength (default 500, reduced)
            linkDistance: 150,         // Target edge length
            collideStrength: 1,        // Anti-overlap force strength [0,1]
            factor: 2,                 // Repulsion coefficient multiplier
            coulombDisScale: 0.005,    // Coulomb distance scale (affects repulsion range)
            getMass: (node) => {
                // Entrypoints have massive mass so they resist movement
                return node.data.is_entrypoint ? 10000 : 1;
            },
            getCenter: (node) => {
                // Entrypoints have strong centripetal force to their fixed positions
                if (node.data.is_entrypoint && node.style?.x !== undefined) {
                    return {
                        x: node.style.x,
                        y: node.style.y || 0,
                        strength: 100  // Strong force to keep them in place
                    };
                }
                return null; // Other nodes use default center
            }
        },
        
        // Node configuration (v5 API)
        node: {
            type: 'circle',
            style: {
                size: 30,
                fill: LAYER_COLORS.other,
                stroke: LAYER_COLORS.other,
                lineWidth: 2,
                labelFill: '#fff',
                labelFontSize: 12,
                labelPlacement: 'bottom',
                labelOffsetY: 8
            },
            state: NODE_STATES
        },
        
        // Edge configuration (v5 API)
        edge: {
            type: 'line',
            style: {
                stroke: '#484f58',
                lineWidth: 1.5,
                opacity: 0.4,
                endArrow: true
            },
            state: EDGE_STATES
        },
        
        // Behaviors (v5 API)
        behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element']
    });
    
    // V4 detection
    detectV4Usage(graph);
    
    return graph;
}
