/**
 * Network initialization and event handling
 */

import { PhysicsPolicy } from './physics-policy.js';

export function initializeNetwork(context) {
    const container = document.getElementById(context.containerId);
    if (!container) {
        throw new Error(`Container element #${context.containerId} not found`);
    }

    // Create empty DataSets
    context.nodes = new vis.DataSet([]);
    context.edges = new vis.DataSet([]);

    const data = { nodes: context.nodes, edges: context.edges };
    const options = {
        physics: {
            enabled: true,  // Enable by default to match checkbox
            forceAtlas2Based: {
                gravitationalConstant: -150,
                centralGravity: 0.001,
                springLength: 200,
                springConstant: 0.15,
                damping: 0.3,
                avoidOverlap: 1.0
            },
            solver: 'forceAtlas2Based',
            stabilization: {
                enabled: true,
                iterations: 500,
                updateInterval: 50,
                fit: false  // Don't auto-zoom on stabilization/physics changes
            },
            maxVelocity: 20,
            minVelocity: .5,
            timestep: 0.5,
            adaptiveTimestep: true
        },
        interaction: {
            hover: true,
            tooltipDelay: 100,
            navigationButtons: true,
            keyboard: true,
            hideEdgesOnDrag: true,
            hideEdgesOnZoom: false
        },
        layout: {
            hierarchical: {
                enabled: false
            }
        },
        nodes: {
            borderWidth: 2,
            borderWidthSelected: 3,
            chosen: false,
            font: {
                color: '#ffffff',  // White text for node labels
                background: 'rgba(0, 0, 0, 0.7)',
                strokeWidth: 0,
                vadjust: 0
            },
            labelHighlightBold: false
        },
        edges: {
            width: 1,
            selectionWidth: 3,
            font: {
                color: '#999999',  // Light grey for edge labels
                strokeWidth: 0
            },
            smooth: {
                enabled: false
            },
            chosen: {
                edge: (values, id, selected, hovering) => {
                    if (selected) {
                        values.width = 3;
                    }
                }
            }
        }
    };

    context.network = new vis.Network(container, data, options);
    
    // Initialize physics policy
    context.physicsPolicy = new PhysicsPolicy(context);
    
    // Center viewport at (0, 0)
    context.network.moveTo({
        position: { x: 0, y: 0 },
        scale: 1.0
    });
    
    attachEventHandlers(context);
}

export function attachEventHandlers(context) {
    let clickTimeout = null;
    let clickCount = 0;
    
    // Single click handler with delay to detect double-clicks
    context.network.on('click', (params) => {
        clickCount++;
        
        // Clear existing timeout
        if (clickTimeout) {
            clearTimeout(clickTimeout);
            clickTimeout = null;
        }
        
        // Wait to distinguish single from double click
        clickTimeout = setTimeout(() => {
            const isSingleClick = clickCount === 1;
            clickCount = 0;
            clickTimeout = null;
            
            if (params.nodes.length > 0) {
                const nodeId = params.nodes[0];
                const event = params.event;
                
                if (event.srcEvent.shiftKey) {
                    // Shift+click: Trace paths to entrypoints
                    context.triggerEvent('traceNode', nodeId);
                } else if (event.srcEvent.ctrlKey || event.srcEvent.metaKey) {
                    // Ctrl+click: Select only (no expansion)
                    context.selectedNodeId = nodeId;
                    context.updateEdgeVisibility();
                    context.triggerEvent('selectNodeOnly', nodeId);
                } else if (isSingleClick) {
                    // Single click: Expand node
                    context.selectedNodeId = nodeId;
                    context.updateEdgeVisibility();
                    context.triggerEvent('expandNode', nodeId);
                } else {
                    // Double click: Collapse node
                    context.triggerEvent('collapseNode', nodeId);
                }
            } else if (params.edges.length > 0) {
                // Edge clicked - highlight the target node and select
                const edgeId = params.edges[0];
                const edge = context.edges.get(edgeId);
                if (edge && edge.to) {
                    context.selectedNodeId = edge.to;
                    context.updateEdgeVisibility();
                    context.triggerEvent('selectNodeOnly', edge.to);
                }
            } else {
                // Empty space clicked - clear all highlights
                context.clearSelection();
            }
        }, 250);  // 250ms delay to detect double-click
    });

    // Reapply edge styling after drag
    context.network.on('dragEnd', () => {
        if (context.pathHighlight || context.selectedNodeId) {
            context.updateEdgeVisibility();
        }
    });
}
