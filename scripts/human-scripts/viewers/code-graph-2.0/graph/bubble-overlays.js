/**
 * bubble-overlays.js - Bubble-set overlays using G6's layer system
 * Uses documented v5 APIs: BaseShape.upsert, getElementPosition
 * 
 * Features:
 * - Convex hull computation per layer group
 * - Drawn on background layer using BaseShape.upsert (pans/zooms with graph)
 * - Non-interactive, excluded from hit detection
 * - Lightweight edge styling for cross-layer edges
 * 
 * 200-300 lines max
 */

/* global G6 */

import { LAYER_COLORS } from './graph-styles.js';

// Import BaseShape from G6 (for upsert API)
const { BaseShape } = G6;

/**
 * Compute convex hull using Graham scan algorithm
 * @param {Array<{x: number, y: number}>} points - Points to compute hull for
 * @returns {Array<{x: number, y: number}>} - Hull vertices in clockwise order
 */
function computeConvexHull(points) {
    if (points.length < 3) return points;
    
    // Find the bottom-most point (or left-most if tie)
    let start = points[0];
    for (const p of points) {
        if (p.y < start.y || (p.y === start.y && p.x < start.x)) {
            start = p;
        }
    }
    
    // Sort points by polar angle with respect to start point
    const sorted = points.slice().sort((a, b) => {
        if (a === start) return -1;
        if (b === start) return 1;
        
        const angleA = Math.atan2(a.y - start.y, a.x - start.x);
        const angleB = Math.atan2(b.y - start.y, b.x - start.x);
        
        if (angleA !== angleB) return angleA - angleB;
        
        // Collinear points: sort by distance
        const distA = (a.x - start.x) ** 2 + (a.y - start.y) ** 2;
        const distB = (b.x - start.x) ** 2 + (b.y - start.y) ** 2;
        return distA - distB;
    });
    
    // Build hull using Graham scan
    const hull = [sorted[0], sorted[1]];
    
    for (let i = 2; i < sorted.length; i++) {
        let top = hull[hull.length - 1];
        let nextTop = hull[hull.length - 2];
        
        // Pop while we make a right turn
        while (hull.length > 1 && crossProduct(nextTop, top, sorted[i]) <= 0) {
            hull.pop();
            top = hull[hull.length - 1];
            nextTop = hull[hull.length - 2];
        }
        
        hull.push(sorted[i]);
    }
    
    return hull;
}

/**
 * Compute cross product to determine turn direction
 */
function crossProduct(o, a, b) {
    return (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
}

/**
 * Expand hull outward by padding distance
 * @param {Array<{x: number, y: number}>} hull - Hull vertices
 * @param {number} padding - Padding in pixels
 * @returns {Array<{x: number, y: number}>} - Padded hull
 */
function padHull(hull, padding) {
    if (hull.length < 3) return hull;
    
    // Compute centroid
    const centroid = {
        x: hull.reduce((sum, p) => sum + p.x, 0) / hull.length,
        y: hull.reduce((sum, p) => sum + p.y, 0) / hull.length
    };
    
    // Push each vertex away from centroid
    return hull.map(p => {
        const dx = p.x - centroid.x;
        const dy = p.y - centroid.y;
        const dist = Math.sqrt(dx * dx + dy * dy);
        
        if (dist === 0) return p;
        
        return {
            x: p.x + (dx / dist) * padding,
            y: p.y + (dy / dist) * padding
        };
    });
}

/**
 * Smooth hull using Chaikin's corner cutting algorithm
 * @param {Array<{x: number, y: number}>} hull - Hull vertices
 * @param {number} iterations - Number of smoothing iterations
 * @returns {Array<{x: number, y: number}>} - Smoothed hull
 */
function smoothHull(hull, iterations = 1) {
    let smoothed = hull;
    
    for (let iter = 0; iter < iterations; iter++) {
        const newHull = [];
        
        for (let i = 0; i < smoothed.length; i++) {
            const curr = smoothed[i];
            const next = smoothed[(i + 1) % smoothed.length];
            
            // Quarter point
            const q = {
                x: 0.75 * curr.x + 0.25 * next.x,
                y: 0.75 * curr.y + 0.25 * next.y
            };
            
            // Three-quarter point
            const r = {
                x: 0.25 * curr.x + 0.75 * next.x,
                y: 0.25 * curr.y + 0.75 * next.y
            };
            
            newHull.push(q, r);
        }
        
        smoothed = newHull;
    }
    
    return smoothed;
}

/**
 * Group visible nodes by layer with screen positions
 * Uses documented v5 API: graph.getElementPosition()
 * @param {Graph} graph - G6 graph instance
 * @param {Array} visibleNodes - Currently visible nodes
 * @returns {Map<string, Array>} - Map of layer -> nodes with positions
 */
function groupNodesByLayer(graph, visibleNodes) {
    const groups = new Map();
    
    for (const node of visibleNodes) {
        const layer = node.data?.layer || 'other';
        
        // Get node position using documented v5 API (docs/api/element.en.md line 20)
        const position = graph.getElementPosition(node.id);
        
        if (!position || position.x === undefined || position.y === undefined) continue;
        
        if (!groups.has(layer)) {
            groups.set(layer, []);
        }
        
        groups.get(layer).push({
            id: node.id,
            x: position.x,
            y: position.y
        });
    }
    
    return groups;
}

/**
 * Compute centroids for each layer group
 * Simplified: returns empty map since we're not computing centroid-based routing yet
 * @param {Map<string, Array>} groupedNodes - Nodes grouped by layer
 * @returns {Map<string, {x: number, y: number}>} - Layer centroids (empty for now)
 */
function computeLayerCentroids(groupedNodes) {
    // TODO: Implement centroid computation when needed for edge routing
    return new Map();
}

/**
 * Show bubble-set for a specific node's layer
 * @param {Graph} graph - G6 graph instance
 * @param {string} nodeId - Node ID to show bubble for
 * @param {Array} allVisibleNodes - All currently visible nodes
 */
export function showBubbleForNode(graph, nodeId, allVisibleNodes) {
    const node = allVisibleNodes.find(n => n.id === nodeId);
    if (!node || !node.data.layer) return;
    
    const layer = node.data.layer;
    
    // Get all nodes in the same layer
    const layerNodes = allVisibleNodes.filter(n => n.data.layer === layer);
    if (layerNodes.length < 3) return; // Need at least 3 for bubble
    
    // Get all other node IDs (for avoidMembers)
    const layerNodeIds = new Set(layerNodes.map(n => n.id));
    const avoidMembers = allVisibleNodes
        .filter(n => !layerNodeIds.has(n.id))
        .map(n => n.id);
    
    // Get layer color
    const color = LAYER_COLORS[layer] || LAYER_COLORS.other;
    const r = parseInt(color.slice(1, 3), 16);
    const g = parseInt(color.slice(3, 5), 16);
    const b = parseInt(color.slice(5, 7), 16);
    
    const bubbleConfig = {
        type: 'bubble-sets',
        key: 'selected-bubble',
        members: layerNodes.map(n => n.id),
        avoidMembers: avoidMembers,
        nonMemberInfluenceFactor: -1,
        label: true,
        labelText: layer,
        labelBackground: true,
        labelPadding: [4, 8],
        style: {
            fill: `rgba(${r}, ${g}, ${b}, 0.12)`,
            stroke: `rgba(${r}, ${g}, ${b}, 0.5)`,
            lineWidth: 2
        }
    };
    
    // Update plugins: remove old bubble, add new one
    graph.setPlugins((currentPlugins) => {
        const withoutBubble = currentPlugins.filter(p => {
            const key = typeof p === 'object' ? p.key : '';
            return key !== 'selected-bubble';
        });
        return [...withoutBubble, bubbleConfig];
    });
}

/**
 * Hide bubble-set
 * @param {Graph} graph - G6 graph instance
 */
export function hideBubble(graph) {
    graph.setPlugins((currentPlugins) => {
        return currentPlugins.filter(p => {
            const key = typeof p === 'object' ? p.key : '';
            return key !== 'selected-bubble';
        });
    });
}

/**
 * Draw bubble overlays using G6's BubbleSets plugin (DEPRECATED - use showBubbleForNode instead)
 * Uses documented v5 plugin API (docs/manual/plugin/BubbleSets.en.md)
 * @param {Graph} graph - G6 graph instance
 * @param {Map<string, Array>} groupedNodes - Nodes grouped by layer
 */
export function drawBubbleOverlays(graph, groupedNodes) {
    const bubbleConfigs = [];
    
    // Get all visible node IDs
    const allNodeIds = new Set();
    for (const nodes of groupedNodes.values()) {
        nodes.forEach(n => allNodeIds.add(n.id));
    }
    
    for (const [layer, nodes] of groupedNodes) {
        // Skip if too few nodes for bubble
        if (nodes.length < 3) continue;
        
        // Get layer color
        const color = LAYER_COLORS[layer] || LAYER_COLORS.other;
        
        // Convert hex to rgba
        const r = parseInt(color.slice(1, 3), 16);
        const g = parseInt(color.slice(3, 5), 16);
        const b = parseInt(color.slice(5, 7), 16);
        
        // Build avoidMembers: all nodes NOT in this layer
        const layerNodeIds = new Set(nodes.map(n => n.id));
        const avoidMembers = Array.from(allNodeIds).filter(id => !layerNodeIds.has(id));
        
        bubbleConfigs.push({
            type: 'bubble-sets',
            key: `bubble-${layer}`,
            members: nodes.map(n => n.id),
            avoidMembers: avoidMembers,
            nonMemberInfluenceFactor: -1,  // Avoid non-members
            style: {
                fill: `rgba(${r}, ${g}, ${b}, 0.12)`,
                stroke: `rgba(${r}, ${g}, ${b}, 0.5)`,
                lineWidth: 2
            },
            label: false // No labels on bubbles
        });
    }
    
    // Update graph plugins
    graph.setPlugins((currentPlugins) => {
        // Remove old bubble-sets
        const withoutBubbles = currentPlugins.filter(p => {
            const key = typeof p === 'object' ? p.key : '';
            return !key || !key.startsWith('bubble-');
        });
        
        // Add new bubbles
        return [...withoutBubbles, ...bubbleConfigs];
    });
}

/**
 * Compute edge styling for cross-layer edges
 * Simplified: just determines if edge crosses layers, applies style-only changes
 * @param {Graph} graph - G6 graph instance
 * @param {Array} edges - All edges in graph
 * @param {Map<string, {x: number, y: number}>} centroids - Layer centroids (unused for now)
 * @returns {Map<string, Object>} - Edge ID -> routing info
 */
export function computeEdgeRouting(graph, edges, centroids) {
    const routing = new Map();
    
    for (const edge of edges) {
        // Safety check: skip if edge doesn't have source/target
        if (!edge.source || !edge.target) continue;
        
        const sourceData = graph.getNodeData(edge.source);
        const targetData = graph.getNodeData(edge.target);
        
        if (!sourceData || !targetData) continue;
        
        const sourceLayer = sourceData.layer || 'other';
        const targetLayer = targetData.layer || 'other';
        
        // Cross-layer edge: lower opacity and thinner
        if (sourceLayer !== targetLayer) {
            routing.set(edge.id, {
                type: 'cross-layer',
                opacity: 0.2
            });
        } else {
            // Intra-layer edge: normal styling
            routing.set(edge.id, {
                type: 'intra-layer',
                opacity: 0.4
            });
        }
    }
    
    return routing;
}

/**
 * Apply edge routing styles to graph
 * Style-only approach: adjust opacity and stroke for cross-layer edges
 * Does NOT change edge type (requires verification of type-changing API)
 * @param {Graph} graph - G6 graph instance
 * @param {Map<string, Object>} routing - Edge routing info
 */
export function applyEdgeRouting(graph, routing) {
    const updates = [];
    
    for (const [edgeId, routingInfo] of routing) {
        // Only update style properties (opacity, stroke)
        // Do NOT change edge type until API is verified
        updates.push({
            id: edgeId,
            style: {
                opacity: routingInfo.opacity,
                lineWidth: routingInfo.type === 'cross-layer' ? 1 : 1.5
            }
        });
    }
    
    if (updates.length > 0) {
        graph.updateEdgeData(updates);
    }
}

/**
 * Refresh overlays and edge routing (main entry point)
 * Call after render/draw and after layout settles
 * @param {Graph} graph - G6 graph instance
 * @param {Array} visibleNodes - Currently visible nodes
 * @param {Array} visibleEdges - Currently visible edges
 */
export function refreshOverlaysAndRouting(graph, visibleNodes, visibleEdges) {
    // Group nodes by layer (simple grouping without position data)
    const groupedNodes = new Map();
    
    for (const node of visibleNodes) {
        const layer = node.data?.layer || 'other';
        
        if (!groupedNodes.has(layer)) {
            groupedNodes.set(layer, []);
        }
        
        groupedNodes.get(layer).push(node);
    }
    
    // Draw hull overlays using G6 plugin
    drawBubbleOverlays(graph, groupedNodes);
    
    // Apply edge styling (style-only, no routing yet)
    const centroids = computeLayerCentroids(groupedNodes);
    const routing = computeEdgeRouting(graph, visibleEdges, centroids);
    applyEdgeRouting(graph, routing);
}
