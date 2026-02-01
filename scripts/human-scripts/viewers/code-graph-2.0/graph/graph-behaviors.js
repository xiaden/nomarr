/**
 * graph-behaviors.js - Register custom G6 behaviors
 * Emits semantic events: selectNode, expandNode, collapseNode, traceNode
 */

/**
 * Register interaction behaviors
 */
export function registerBehaviors(graph, callbacks) {
    let clickTimer = null;
    let clickedNodeId = null;
    
    // Node click handler
    graph.on('node:click', (evt) => {
        const nodeId = evt.target.id;
        const isCtrl = evt.originalEvent.ctrlKey || evt.originalEvent.metaKey;
        const isShift = evt.originalEvent.shiftKey;
        
        if (clickTimer) {
            // Double click → collapse
            clearTimeout(clickTimer);
            clickTimer = null;
            if (callbacks.onCollapse) callbacks.onCollapse(nodeId);
        } else {
            // Single click → wait to distinguish
            clickedNodeId = nodeId;
            clickTimer = setTimeout(() => {
                if (isCtrl) {
                    // Ctrl+Click → expand
                    if (callbacks.onExpand) callbacks.onExpand(clickedNodeId);
                    
                    // Debug: Show full node properties
                    const nodeData = graph.getNodeData(clickedNodeId);
                    if (nodeData) {
                        const layoutOptions = graph.getOptions?.()?.layout || {};
                        console.log('=== NODE DEBUG (Expanded) ===');
                        console.log('Node ID:', nodeData.id);
                        console.log('Position:', { x: nodeData.style?.x, y: nodeData.style?.y });
                        console.log('Data:', nodeData.data);
                        console.log('Is Entrypoint:', nodeData.data?.is_entrypoint);
                        console.log('Layout Config:', {
                            type: layoutOptions.type,
                            nodeStrength: layoutOptions.nodeStrength,
                            nodeSize: layoutOptions.nodeSize,
                            nodeSpacing: layoutOptions.nodeSpacing,
                            edgeStrength: layoutOptions.edgeStrength,
                            linkDistance: layoutOptions.linkDistance,
                            collideStrength: layoutOptions.collideStrength,
                            preventOverlap: layoutOptions.preventOverlap,
                            factor: layoutOptions.factor,
                            coulombDisScale: layoutOptions.coulombDisScale
                        });
                        console.log('Has getMass:', typeof layoutOptions.getMass === 'function');
                        console.log('Has getCenter:', typeof layoutOptions.getCenter === 'function');
                        if (typeof layoutOptions.getMass === 'function') {
                            console.log('Computed Mass:', layoutOptions.getMass(nodeData));
                        }
                        if (typeof layoutOptions.getCenter === 'function') {
                            console.log('Computed Center:', layoutOptions.getCenter(nodeData));
                        }
                        console.log('============================');
                    }
                } else if (isShift) {
                    // Shift+Click → trace
                    if (callbacks.onTrace) callbacks.onTrace(clickedNodeId);
                } else {
                    // Normal click → select
                    if (callbacks.onSelect) {
                        callbacks.onSelect(clickedNodeId);
                        
                        // Show bubble-set for selected node's layer
                        if (callbacks.onShowBubble) {
                            callbacks.onShowBubble(clickedNodeId);
                        }
                    }
                    
                    // Debug: Show full node properties
                    const nodeData = graph.getNodeData(clickedNodeId);
                    if (nodeData) {
                        const layoutOptions = graph.getOptions?.()?.layout || {};
                        console.log('=== NODE DEBUG (Selected) ===');
                        console.log('Node ID:', nodeData.id);
                        console.log('Position:', { x: nodeData.style?.x, y: nodeData.style?.y });
                        console.log('Data:', nodeData.data);
                        console.log('Is Entrypoint:', nodeData.data?.is_entrypoint);
                        console.log('Layout Config:', {
                            type: layoutOptions.type,
                            nodeStrength: layoutOptions.nodeStrength,
                            nodeSize: layoutOptions.nodeSize,
                            nodeSpacing: layoutOptions.nodeSpacing,
                            edgeStrength: layoutOptions.edgeStrength,
                            linkDistance: layoutOptions.linkDistance,
                            collideStrength: layoutOptions.collideStrength,
                            preventOverlap: layoutOptions.preventOverlap,
                            factor: layoutOptions.factor,
                            coulombDisScale: layoutOptions.coulombDisScale
                        });
                        console.log('Has getMass:', typeof layoutOptions.getMass === 'function');
                        console.log('Has getCenter:', typeof layoutOptions.getCenter === 'function');
                        if (typeof layoutOptions.getMass === 'function') {
                            console.log('Computed Mass:', layoutOptions.getMass(nodeData));
                        }
                        if (typeof layoutOptions.getCenter === 'function') {
                            console.log('Computed Center:', layoutOptions.getCenter(nodeData));
                        }
                        console.log('============================');
                    }
                }
                clickTimer = null;
            }, 250);
        }
    });
    
    // Canvas click → deselect
    graph.on('canvas:click', () => {
        if (callbacks.onSelect) callbacks.onSelect(null);
        
        // Remove bubble-set on deselect
        if (callbacks.onHideBubble) {
            callbacks.onHideBubble();
        }
    });
}
