/**
 * graph-renderer.js - The ONLY file that calls graph render methods
 * Implements two-phase boot: layout then freeze
 */

import { getNodeColor } from './graph-styles.js';

/**
 * Two-phase render: layout non-entrypoints, then freeze and preserve entrypoint positions
 * Phase 1: Let force layout position non-entrypoint nodes
 * Phase 2: Stop layout and lock entrypoint positions
 */
export async function renderGraph(graph, visibleGraph) {
    // Position entrypoints horizontally (fixed positions)
    const entrypoints = visibleGraph.nodes.filter(n => n.data.is_entrypoint);
    const spacing = 200;
    
    entrypoints.forEach((node, i) => {
        node.x = (i - (entrypoints.length - 1) / 2) * spacing;
        node.y = 0;
    });
    
    // Transform nodes for G6
    const g6Nodes = visibleGraph.nodes.map(n => ({
        id: n.id,
        data: n.data,
        style: {
            x: n.x,
            y: n.y,
            labelText: n.data.label,
            fill: getNodeColor(n.data.layer),
            stroke: getNodeColor(n.data.layer)
        }
    }));
    
    // Build node ID set for edge filtering
    const visibleNodeIds = new Set(g6Nodes.map(n => n.id));
    
    // Filter edges: only include edges where both endpoints are visible
    const g6Edges = visibleGraph.edges
        .filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
        .map(e => ({
            id: e.id,
            source: e.source,
            target: e.target,
            data: e.data
        }));
    
    // Phase 1: setData + render (starts force layout)
    graph.setData({ nodes: g6Nodes, edges: g6Edges });
    await graph.render();
    
    // Phase 2: After layout settles, keep simulation running but lock entrypoints
    setTimeout(() => {
        
        // Restore entrypoint positions (layout may have moved them)
        const updates = entrypoints.map((node, i) => ({
            id: node.id,
            style: {
                x: (i - (entrypoints.length - 1) / 2) * spacing,
                y: 0
            }
        }));
        
        if (updates.length > 0) {
            graph.updateNodeData(updates);
        }
        
        // Don't continuously force entrypoint positions - let layout settle naturally
        // The initial position and layout config should keep them reasonably positioned
        
        // Don't show bubble overlays on initial render - only on node selection
    }, 1500);
}

/**
 * Update graph with new visible data (after layout freeze)
 * Uses setData + draw WITHOUT re-running layout
 * Preserves all existing positions
 */
export async function updateGraph(graph, visibleGraph) {
    // Get current node positions to preserve them (layout is frozen)
    const currentNodes = graph.getNodeData();
    const positionMap = new Map();
    
    currentNodes.forEach(n => {
        if (n.style && n.style.x !== undefined && n.style.y !== undefined) {
            positionMap.set(n.id, { x: n.style.x, y: n.style.y });
        }
    });
    
    // Transform nodes, preserving positions for existing nodes
    // New nodes get smart initial positions near their connected nodes
    const g6Nodes = visibleGraph.nodes.map(n => {
        const pos = positionMap.get(n.id);
        
        // If new node, try to position it near a connected node
        let initialPos = { x: 0, y: 0 };
        if (!pos) {
            // Find edges where this node is the target (incoming edges)
            const incomingEdge = visibleGraph.edges.find(e => e.target === n.id);
            if (incomingEdge) {
                const sourcePos = positionMap.get(incomingEdge.source);
                if (sourcePos) {
                    // Position new node near its parent with some randomness
                    initialPos = {
                        x: sourcePos.x + (Math.random() - 0.5) * 100,
                        y: sourcePos.y + (Math.random() - 0.5) * 100
                    };
                }
            }
        }
        
        return {
            id: n.id,
            data: n.data,
            style: {
                ...(pos ? { x: pos.x, y: pos.y } : initialPos),
                labelText: n.data.label,
                fill: getNodeColor(n.data.layer),
                stroke: getNodeColor(n.data.layer)
            }
        };
    });
    
    // Build node ID set for edge filtering
    const visibleNodeIds = new Set(g6Nodes.map(n => n.id));
    
    // Filter edges: only include edges where both endpoints are visible
    const g6Edges = visibleGraph.edges
        .filter(e => visibleNodeIds.has(e.source) && visibleNodeIds.has(e.target))
        .map(e => ({
            id: e.id,
            source: e.source,
            target: e.target,
            data: e.data
        }));
    
    // setData + render (MUST use render to run layout for new nodes)
    graph.setData({ nodes: g6Nodes, edges: g6Edges });
    await graph.render(); // Use render() not draw() to run layout simulation
    
    // Don't auto-refresh bubble overlays on update - only on node selection
}

/**
 * Focus on a node (center + zoom) - v5 API
 */
export function focusOnNode(graph, nodeId) {
    graph.focusElement(nodeId, {
        easing: 'ease-in-out',
        duration: 300
    });
}
