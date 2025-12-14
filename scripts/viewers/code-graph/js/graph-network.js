/**
 * Module for managing the vis.js network visualization
 */

import { HIGHLIGHT_COLORS, LAYER_COLORS } from './graph-colors.js';

export class GraphNetwork {
    constructor(containerId) {
        this.containerId = containerId;
        this.network = null;
        this.nodes = null;
        this.edges = null;
        this.eventHandlers = {};
        this.selectedNodeId = null;
        this.allEdges = [];  // Store all edges
        this.maxVisibleEdges = 1200;  // Limit visible edges for performance
        this.pathHighlight = null;  // Current path highlighting data
        this.originalNodeLabels = new Map();  // Store original node labels
        this.originalEdgeLabels = new Map();  // Store original edge labels
        this.originalNodeProps = new Map();  // Store original node properties (font, constraints)
    }

    /**
     * Initialize the network visualization
     */
    initialize() {
        const container = document.getElementById(this.containerId);
        if (!container) {
            throw new Error(`Container element #${this.containerId} not found`);
        }

        // Create empty DataSets
        this.nodes = new vis.DataSet([]);
        this.edges = new vis.DataSet([]);

        const data = { nodes: this.nodes, edges: this.edges };
        const options = {
            physics: {
                enabled: false,  // Start with physics disabled for blank state
                forceAtlas2Based: {
                    gravitationalConstant: -150,  // Much stronger repulsion to prevent tangles
                    centralGravity: 0.005,
                    springLength: 50,  // Shorter ideal edge length
                    springConstant: 0.15,  // Stronger spring force to pull nodes together
                    damping: 0.95,  // Much higher damping to stop rotation
                    avoidOverlap: 1.0  // Stronger overlap avoidance
                },
                solver: 'forceAtlas2Based',
                stabilization: {
                    enabled: true,
                    iterations: 500,  // More iterations to untangle better
                    updateInterval: 50,
                    fit: true
                },
                maxVelocity: 20,
                minVelocity: 0.1,  // Lower minimum velocity
                timestep: 0.5,
                adaptiveTimestep: true  // Adjust timestep based on movement
            },
            interaction: {
                hover: true,
                tooltipDelay: 100,
                navigationButtons: true,
                keyboard: true,
                hideEdgesOnDrag: true,  // Hide edges while dragging for better performance
                hideEdgesOnZoom: false
            },
            layout: {
                hierarchical: {
                    enabled: false,
                    sortMethod: 'directed',
                    levelSeparation: 150
                }
            },
            nodes: {
                borderWidth: 2,
                borderWidthSelected: 3,
                chosen: false,  // Disable to prevent size changes on hover/select
                font: {
                    background: 'rgba(0, 0, 0, 0.7)',  // Dark background for labels
                    strokeWidth: 0,
                    vadjust: 0
                },
                labelHighlightBold: false
            },
            edges: {
                width: 1,
                selectionWidth: 3,
                smooth: {
                    enabled: false  // Disable smoothing for better performance
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

        this.network = new vis.Network(container, data, options);
        
        // Center viewport at (0, 0)
        this.network.moveTo({
            position: { x: 0, y: 0 },
            scale: 1.0
        });
        
        this.attachEventHandlers();
    }

    /**
     * Attach internal event handlers
     */
    attachEventHandlers() {
        // Click event for node/edge selection
        this.network.on('click', (params) => {
            if (params.nodes.length > 0) {
                // Node clicked
                this.selectedNodeId = params.nodes[0];
                this.updateEdgeVisibility();
                this.triggerEvent('nodeClick', params.nodes[0]);
            } else if (params.edges.length > 0) {
                // Edge clicked - highlight the target node
                const edgeId = params.edges[0];
                const edge = this.edges.get(edgeId);
                if (edge && edge.to) {
                    this.selectedNodeId = edge.to;
                    this.updateEdgeVisibility();
                    this.triggerEvent('nodeClick', edge.to);
                }
            } else {
                // Empty space clicked - clear all highlights
                this.clearSelection();
            }
        });

        // Double-click to focus
        this.network.on('doubleClick', (params) => {
            if (params.nodes.length > 0) {
                this.network.focus(params.nodes[0], {
                    scale: 1.5,
                    animation: true
                });
            }
        });

        // Reapply edge styling after drag (hideEdgesOnDrag resets edge properties)
        this.network.on('dragEnd', () => {
            if (this.pathHighlight || this.selectedNodeId) {
                this.updateEdgeVisibility();
            }
        });

        // Note: Physics stays enabled continuously for interactive graph
        // The gradual node loading (10 every 250ms) keeps CPU usage reasonable
    }

    /**
     * Register custom event handler
     * @param {string} eventName - Name of event (e.g., 'nodeClick')
     * @param {Function} handler - Handler function
     */
    on(eventName, handler) {
        if (!this.eventHandlers[eventName]) {
            this.eventHandlers[eventName] = [];
        }
        this.eventHandlers[eventName].push(handler);
    }

    /**
     * Trigger custom event
     * @param {string} eventName
     * @param {*} data
     */
    triggerEvent(eventName, data) {
        if (this.eventHandlers[eventName]) {
            this.eventHandlers[eventName].forEach(handler => handler(data));
        }
    }

    /**
     * Clear all nodes and edges from the graph
     */
    async clearGraph() {
        if (!this.nodes || !this.edges) return;
        
        // Clear edges first
        this.edges.clear();
        this.allEdges = [];
        
        // Remove nodes in batches for smooth animation
        const nodeIds = this.nodes.getIds();
        const batchSize = 50;
        const delay = 5;
        
        for (let i = 0; i < nodeIds.length; i += batchSize) {
            const batch = nodeIds.slice(i, i + batchSize);
            this.nodes.remove(batch);
            await new Promise(resolve => setTimeout(resolve, delay));
        }
        
        // Reset state
        this.selectedNodeId = null;
        this.pathHighlight = null;
    }

    /**
     * Update network with new node and edge data
     * @param {Array} nodes - Node array
     * @param {Array} edges - Edge array
     * @param {Function} shouldCancel - Optional function that returns true if render should be cancelled
     */
    async updateGraph(nodes, edges, shouldCancel = null) {
        // Detect if this is initial load or filter change
        const currentNodeIds = new Set(this.nodes.getIds());
        const newNodeIds = new Set(nodes.map(n => n.id));
        const isInitialLoad = currentNodeIds.size === 0;
        
        // Store all edges for visibility management
        this.allEdges = edges;
        
        if (isInitialLoad) {
            // Initial load: clear and animate everything in
            this.nodes.clear();
            this.edges.clear();
            this.selectedNodeId = null;
            
            if (nodes.length > 0) {
                // Add nodes one at a time with smooth animation (1 every 20ms)
                const batchSize = 1;
                const delayPerBatch = 20;
                const totalBatches = nodes.length;
                
                // Add ALL edges first
                this.edges.add(edges);
                this.updateEdgeVisibility();
                
                // Sort nodes by edge count (most connected first)
                const edgeCount = new Map();
                edges.forEach(edge => {
                    edgeCount.set(edge.from, (edgeCount.get(edge.from) || 0) + 1);
                    edgeCount.set(edge.to, (edgeCount.get(edge.to) || 0) + 1);
                });
                const sortedNodes = [...nodes].sort((a, b) => 
                    (edgeCount.get(b.id) || 0) - (edgeCount.get(a.id) || 0)
                );
                
                // Enable physics
                this.network.setOptions({ physics: { enabled: true } });
                
                // Build edge lookup for positioning
                const nodeConnections = new Map();
                edges.forEach(edge => {
                    if (!nodeConnections.has(edge.from)) nodeConnections.set(edge.from, []);
                    if (!nodeConnections.has(edge.to)) nodeConnections.set(edge.to, []);
                    nodeConnections.get(edge.from).push(edge.to);
                    nodeConnections.get(edge.to).push(edge.from);
                });
                
                // Add nodes gradually (sorted by edge count)
                for (let i = 0; i < sortedNodes.length; i += batchSize) {
                    // Check for cancellation
                    if (shouldCancel && shouldCancel()) {
                        // Clear what we've added so far
                        this.nodes.clear();
                        this.edges.clear();
                        return;
                    }
                    
                    const batch = sortedNodes.slice(i, i + batchSize);
                    
                    // Position each node near its connected neighbors
                    batch.forEach(node => {
                        const connectedIds = nodeConnections.get(node.id) || [];
                        const positions = [];
                        
                        connectedIds.forEach(connectedId => {
                            try {
                                const pos = this.network.getPosition(connectedId);
                                if (pos && pos.x !== undefined && pos.y !== undefined) {
                                    positions.push(pos);
                                }
                            } catch (e) {
                                // Node not yet placed
                            }
                        });
                        
                        if (positions.length > 0) {
                            // Average position of connected nodes, with offset to avoid overlap
                            const avgX = positions.reduce((sum, p) => sum + p.x, 0) / positions.length;
                            const avgY = positions.reduce((sum, p) => sum + p.y, 0) / positions.length;
                            const offsetAngle = Math.random() * Math.PI * 2;
                            const offsetDist = 100;
                            node.x = avgX + Math.cos(offsetAngle) * offsetDist;
                            node.y = avgY + Math.sin(offsetAngle) * offsetDist;
                        }
                    });
                    
                    this.nodes.add(batch);
                    
                    const progress = Math.min(100, Math.round(((i + 1) / totalBatches) * 100));
                    this.triggerEvent('loadProgress', { current: i + 1, total: totalBatches, progress });
                    
                    await new Promise(resolve => setTimeout(resolve, delayPerBatch));
                }
                
                this.triggerEvent('loadProgress', { current: totalBatches, total: totalBatches, progress: 100 });
                
                // Stabilize then freeze
                setTimeout(() => {
                    this.network.stabilize(200);
                    setTimeout(() => {
                        this.network.setOptions({ physics: { enabled: false } });
                    }, 3000);
                }, 1000);
            }
        } else {
            // Filter change: incrementally add/remove
            const nodesToAdd = nodes.filter(n => !currentNodeIds.has(n.id));
            const nodesToRemove = Array.from(currentNodeIds).filter(id => !newNodeIds.has(id));
            
            // Update edges
            this.edges.clear();
            this.edges.add(edges);
            this.updateEdgeVisibility();
            
            // Remove nodes in batches (10 every 10ms for snappy removal)
            if (nodesToRemove.length > 0) {
                const removeBatchSize = 10;
                const removeDelay = 10;
                
                for (let i = 0; i < nodesToRemove.length; i += removeBatchSize) {
                    const batch = nodesToRemove.slice(i, i + removeBatchSize);
                    this.nodes.remove(batch);
                    await new Promise(resolve => setTimeout(resolve, removeDelay));
                }
            }
            
            // Add new nodes one at a time (sorted by edge count)
            if (nodesToAdd.length > 0) {
                const addDelay = 20;
                
                // Sort new nodes by edge count (most connected first)
                const edgeCount = new Map();
                edges.forEach(edge => {
                    edgeCount.set(edge.from, (edgeCount.get(edge.from) || 0) + 1);
                    edgeCount.set(edge.to, (edgeCount.get(edge.to) || 0) + 1);
                });
                const sortedNewNodes = [...nodesToAdd].sort((a, b) => 
                    (edgeCount.get(b.id) || 0) - (edgeCount.get(a.id) || 0)
                );
                
                // Build edge lookup for positioning
                const nodeConnections = new Map();
                edges.forEach(edge => {
                    if (!nodeConnections.has(edge.from)) nodeConnections.set(edge.from, []);
                    if (!nodeConnections.has(edge.to)) nodeConnections.set(edge.to, []);
                    nodeConnections.get(edge.from).push(edge.to);
                    nodeConnections.get(edge.to).push(edge.from);
                });
                
                // Brief physics burst for new nodes
                this.network.setOptions({ physics: { enabled: true } });
                
                for (let i = 0; i < sortedNewNodes.length; i++) {
                    // Check for cancellation
                    if (shouldCancel && shouldCancel()) {
                        // Keep graph in consistent state
                        return;
                    }
                    
                    const node = sortedNewNodes[i];
                    const connectedIds = nodeConnections.get(node.id) || [];
                    const positions = [];
                    
                    connectedIds.forEach(connectedId => {
                        try {
                            const pos = this.network.getPosition(connectedId);
                            if (pos && pos.x !== undefined && pos.y !== undefined) {
                                positions.push(pos);
                            }
                        } catch (e) {
                            // Node not yet placed
                        }
                    });
                    
                    if (positions.length > 0) {
                        // Average position of connected nodes, with offset to avoid overlap
                        const avgX = positions.reduce((sum, p) => sum + p.x, 0) / positions.length;
                        const avgY = positions.reduce((sum, p) => sum + p.y, 0) / positions.length;
                        const offsetAngle = Math.random() * Math.PI * 2;
                        const offsetDist = 100;
                        node.x = avgX + Math.cos(offsetAngle) * offsetDist;
                        node.y = avgY + Math.sin(offsetAngle) * offsetDist;
                    }
                    
                    this.nodes.add(node);
                    await new Promise(resolve => setTimeout(resolve, addDelay));
                }
                
                // Stabilize briefly then freeze again
                setTimeout(() => {
                    this.network.stabilize(100);
                    setTimeout(() => {
                        this.network.setOptions({ physics: { enabled: false } });
                    }, 1000);
                }, 500);
            }
        }
    }

    /**
     * Fit network to screen with animation
     */
    fit() {
        if (this.network) {
            this.network.fit({ animation: true });
        }
    }

    /**
     * Clear selection
     */
    clearSelection() {
        if (this.network) {
            this.network.unselectAll();
            
            // Reset all nodes (restore full opacity and default colors)
            const nodeUpdates = [];
            
            // Get all visible nodes and restore labels
            this.nodes.forEach(node => {
                const defaultColor = this.getNodeColor(node);
                const originalLabel = this.originalNodeLabels.get(node.id) || node.label;
                const originalProps = this.originalNodeProps.get(node.id);
                
                const update = {
                    id: node.id,
                    borderWidth: 2,
                    color: {
                        border: defaultColor,
                        background: defaultColor
                    },
                    opacity: 1.0,
                    level: undefined,
                    label: originalLabel
                };
                
                // Restore original properties if we stored them
                if (originalProps) {
                    update.font = originalProps.font ? { ...originalProps.font } : undefined;
                    update.widthConstraint = originalProps.widthConstraint;
                    update.heightConstraint = originalProps.heightConstraint;
                }
                
                nodeUpdates.push(update);
            });
            
            // Clear stored labels and properties
            this.originalNodeLabels.clear();
            this.originalEdgeLabels.clear();
            this.originalNodeProps.clear();
            
            this.selectedNodeId = null;
            this.pathHighlight = null;
            this.updateEdgeVisibility();
            
            if (nodeUpdates.length > 0) {
                this.nodes.update(nodeUpdates);
            }
        }
    }

    /**
     * Focus on a specific node
     * @param {string} nodeId
     * @param {number} scale - Zoom level (default 1.5)
     */
    focusNode(nodeId, scale = 1.5) {
        if (this.network) {
            this.network.focus(nodeId, {
                scale: scale,
                animation: true
            });
        }
    }

    /**
     * Enable physics simulation
     */
    enablePhysics() {
        if (this.network) {
            this.network.setOptions({ physics: { enabled: true } });
        }
    }

    /**
     * Disable physics simulation
     */
    disablePhysics() {
        if (this.network) {
            this.network.setOptions({ physics: { enabled: false } });
        }
    }

    /**
     * Stabilize the network (useful after updates)
     */
    stabilize() {
        if (this.network) {
            this.network.stabilize();
        }
    }

    /**
     * Highlight path to entrypoint
     * @param {Object} pathHighlight - {nodeIds: Set, edgeIds: Set, paths: Array, foundPaths: boolean}
     */
    highlightPath(pathHighlight) {
        if (!this.nodes || !this.network) {
            console.warn('Network not initialized, skipping path highlight');
            return;
        }
        
        // Store previous path nodes to know what to clear
        const previousPathNodes = this.pathHighlight?.nodeIds || new Set();
        this.pathHighlight = pathHighlight;
        
        // Only update edge visibility
        this.updateEdgeVisibility();
        
        // Get all visible node IDs
        const allVisibleNodes = new Set();
        this.nodes.forEach(node => allVisibleNodes.add(node.id));
        
        // Update ONLY the nodes that changed state (path nodes + previously highlighted nodes + selected)
        const nodeUpdates = [];
        
        if (pathHighlight && pathHighlight.foundPaths) {
            // Collect nodes connected to the selected node
            const connectedToSelected = new Set();
            if (this.selectedNodeId) {
                this.allEdges.forEach(edge => {
                    if (edge.from === this.selectedNodeId) {
                        connectedToSelected.add(edge.to);
                    }
                    if (edge.to === this.selectedNodeId) {
                        connectedToSelected.add(edge.from);
                    }
                });
            }
            
            // Nodes to keep visible: path nodes + selected + connected to selected
            const highlightedNodes = new Set([...pathHighlight.nodeIds]);
            if (this.selectedNodeId) {
                highlightedNodes.add(this.selectedNodeId);
            }
            connectedToSelected.forEach(nodeId => highlightedNodes.add(nodeId));
            
            // Update all visible nodes
            allVisibleNodes.forEach(nodeId => {
                const node = this.nodes.get(nodeId);
                if (!node) return;
                
                const defaultColor = this.getNodeColor(node);
                const isConnectedToSelected = connectedToSelected.has(nodeId);
                
                if (pathHighlight.nodeIds.has(nodeId)) {
                    // Highlight path nodes with orange border and restore label
                    const originalLabel = this.originalNodeLabels.get(nodeId) || node.label;
                    const originalProps = this.originalNodeProps.get(nodeId);
                    const update = {
                        id: nodeId,
                        borderWidth: 4,
                        color: {
                            border: HIGHLIGHT_COLORS.path,
                            background: defaultColor
                        },
                        opacity: 1.0,
                        level: 0,
                        label: originalLabel
                    };
                    if (originalProps) {
                        update.font = originalProps.font ? { ...originalProps.font } : undefined;
                        update.widthConstraint = originalProps.widthConstraint;
                        update.heightConstraint = originalProps.heightConstraint;
                    }
                    nodeUpdates.push(update);
                } else if (nodeId === this.selectedNodeId) {
                    // Keep selected node highlighted and restore label
                    const originalLabel = this.originalNodeLabels.get(nodeId) || node.label;
                    const originalProps = this.originalNodeProps.get(nodeId);
                    const update = {
                        id: nodeId,
                        borderWidth: 4,
                        color: {
                            border: HIGHLIGHT_COLORS.selected,
                            background: defaultColor
                        },
                        opacity: 1.0,
                        level: 0,
                        label: originalLabel
                    };
                    if (originalProps) {
                        update.font = originalProps.font ? { ...originalProps.font } : undefined;
                        update.widthConstraint = originalProps.widthConstraint;
                        update.heightConstraint = originalProps.heightConstraint;
                    }
                    nodeUpdates.push(update);
                } else if (isConnectedToSelected) {
                    // Keep connected nodes visible but not highlighted, keep their labels
                    const originalLabel = this.originalNodeLabels.get(nodeId) || node.label;
                    const originalProps = this.originalNodeProps.get(nodeId);
                    const update = {
                        id: nodeId,
                        borderWidth: 2,
                        color: {
                            border: defaultColor,
                            background: defaultColor
                        },
                        opacity: 1.0,
                        level: 5,
                        label: originalLabel
                    };
                    if (originalProps) {
                        update.font = originalProps.font ? { ...originalProps.font } : undefined;
                        update.widthConstraint = originalProps.widthConstraint;
                        update.heightConstraint = originalProps.heightConstraint;
                    }
                    nodeUpdates.push(update);
                } else {
                    // Dim non-path nodes and hide their labels
                    const originalNode = this.nodes.get(nodeId);
                    if (originalNode) {
                        if (originalNode.label && !this.originalNodeLabels.has(nodeId)) {
                            this.originalNodeLabels.set(nodeId, originalNode.label);
                        }
                        if (!this.originalNodeProps.has(nodeId)) {
                            this.originalNodeProps.set(nodeId, {
                                font: originalNode.font ? { ...originalNode.font } : undefined,
                                widthConstraint: originalNode.widthConstraint,
                                heightConstraint: originalNode.heightConstraint,
                                size: originalNode.size
                            });
                        }
                    }
                    const nodeSize = node.size || 25;
                    nodeUpdates.push({
                        id: nodeId,
                        borderWidth: 2,
                        color: {
                            border: defaultColor,
                            background: defaultColor
                        },
                        opacity: 0.08,
                        level: 10,
                        label: ' ',  // Single space to maintain size
                        font: { size: 0, color: 'rgba(0,0,0,0)', background: 'none' },  // Completely hide label
                        widthConstraint: { minimum: nodeSize, maximum: nodeSize },  // Fix width
                        heightConstraint: node.heightConstraint || { minimum: nodeSize, maximum: nodeSize }  // Fix height
                    });
                }
            });
        } else if (previousPathNodes.size > 0) {
            // No paths found, but we had previous highlights - clear them
            previousPathNodes.forEach(nodeId => {
                const node = this.nodes.get(nodeId);
                if (node && nodeId !== this.selectedNodeId) {
                    const defaultColor = this.getNodeColor(node);
                    nodeUpdates.push({
                        id: nodeId,
                        borderWidth: 2,
                        color: {
                            border: defaultColor,
                            background: defaultColor
                        }
                    });
                }
            });
        }
        
        if (nodeUpdates.length > 0) {
            this.nodes.update(nodeUpdates);
        }
    }

    /**
     * Get default node color based on layer and reachability
     */
    getNodeColor(node) {
        // Unreachable nodes are gray
        if (node.reachable_from_interface === false) {
            return HIGHLIGHT_COLORS.unreachable;
        }
        
        return LAYER_COLORS[node.layer] || LAYER_COLORS.other;
    }

    /**
     * Update edge visibility based on selected node, path highlighting, and edge limit
     */
    updateEdgeVisibility() {
        if (!this.edges || this.allEdges.length === 0) return;

        // Calculate in-degree for each node (how many edges point to it)
        const inDegree = new Map();
        this.allEdges.forEach(edge => {
            inDegree.set(edge.to, (inDegree.get(edge.to) || 0) + 1);
        });

        // Categorize edges
        const pathEdges = [];
        const selectedEdges = [];
        const otherEdges = [];

        let matchedPathEdges = 0;
        this.allEdges.forEach(edge => {
            const edgeKey = `${edge.from}->${edge.to}`;
            
            // Priority 1: Path to entrypoint edges (highlighted in orange)
            if (this.pathHighlight && this.pathHighlight.edgeIds.has(edgeKey)) {
                pathEdges.push({...edge, color: HIGHLIGHT_COLORS.path, width: 3});
                matchedPathEdges++;
            }
            // Priority 2: Selected node edges
            else if (this.selectedNodeId && 
                (edge.from === this.selectedNodeId || edge.to === this.selectedNodeId)) {
                selectedEdges.push(edge);
            } 
            // Priority 3: Other edges
            else {
                otherEdges.push(edge);
            }
        });
        


        // Sort other edges by noisiness (prefer edges to low-degree nodes)
        otherEdges.sort((a, b) => {
            const degreeA = inDegree.get(a.to) || 0;
            const degreeB = inDegree.get(b.to) || 0;
            return degreeA - degreeB;  // Lower degree first
        });

        // Determine how many other edges we can show
        const usedBudget = pathEdges.length + selectedEdges.length;
        const remainingBudget = Math.max(0, this.maxVisibleEdges - usedBudget);
        const visibleOtherEdges = otherEdges.slice(0, remainingBudget);

        // Build set of visible edges
        const visibleEdges = [...pathEdges, ...selectedEdges, ...visibleOtherEdges];
        const visibleEdgeIds = new Set(visibleEdges.map(e => e.id));

        // Update edge properties
        const edgeUpdates = this.allEdges.map(edge => {
            const isVisible = visibleEdgeIds.has(edge.id);
            const edgeKey = `${edge.from}->${edge.to}`;
            const isPathEdge = this.pathHighlight && this.pathHighlight.edgeIds.has(edgeKey);
            const isSelected = this.selectedNodeId && 
                (edge.from === this.selectedNodeId || edge.to === this.selectedNodeId);
            
            const shouldDim = this.pathHighlight && this.pathHighlight.foundPaths && !isPathEdge && !isSelected;
            
            // Determine color with opacity for edges
            let edgeColor;
            if (isPathEdge) {
                edgeColor = HIGHLIGHT_COLORS.path;
            } else if (shouldDim) {
                // Dim non-path edges by setting color with low opacity
                const baseColor = edge.originalColor || edge.color;
                if (typeof baseColor === 'string') {
                    // Convert hex/named color to rgba with low opacity
                    edgeColor = { color: baseColor, opacity: 0.08 };
                } else if (baseColor && typeof baseColor === 'object') {
                    edgeColor = { ...baseColor, opacity: 0.08 };
                } else {
                    edgeColor = { color: '#848484', opacity: 0.08 };
                }
            } else {
                edgeColor = edge.originalColor || edge.color;
            }
            
            // Hide labels on dimmed edges, restore on highlighted edges
            let label;
            let font;
            
            if (shouldDim && isVisible) {
                // Dimmed edge that's visible - hide label completely
                const originalEdge = this.edges.get(edge.id);
                if (originalEdge && originalEdge.label && !this.originalEdgeLabels.has(edge.id)) {
                    this.originalEdgeLabels.set(edge.id, originalEdge.label);
                }
                label = '';  // Empty string to hide label
                font = { size: 0, color: 'rgba(0,0,0,0)', background: 'none' };  // Invisible font with no background
            } else if (!shouldDim) {
                // Not dimmed - restore/keep original label
                const storedLabel = this.originalEdgeLabels.get(edge.id);
                if (storedLabel) {
                    label = storedLabel;
                } else {
                    const originalEdge = this.edges.get(edge.id);
                    label = originalEdge ? originalEdge.label : undefined;
                }
                font = edge.font;
            }
            
            // Determine z-order level (lower values render on top)
            const level = (isPathEdge || isSelected) ? 0 : (shouldDim ? 10 : undefined);
            
            const update = {
                id: edge.id,
                hidden: !isVisible,
                color: edgeColor,
                width: isPathEdge ? 3 : (edge.originalWidth || edge.width || 1),
                level: level
            };
            
            // Always include label/font for visible edges
            if (isVisible) {
                if (label !== undefined) update.label = label;
                if (font !== undefined) update.font = font;
            }
            
            return update;
        });

        this.edges.update(edgeUpdates);
    }

    /**
     * Get currently selected nodes
     * @returns {Array}
     */
    getSelectedNodes() {
        return this.network ? this.network.getSelectedNodes() : [];
    }

    /**
     * Get network statistics
     * @returns {Object}
     */
    getStats() {
        if (!this.network) {
            return { nodes: 0, edges: 0 };
        }
        return {
            nodes: this.nodes.length,
            edges: this.edges.length
        };
    }

    /**
     * Destroy the network instance
     */
    destroy() {
        if (this.network) {
            this.network.destroy();
            this.network = null;
        }
    }
}
