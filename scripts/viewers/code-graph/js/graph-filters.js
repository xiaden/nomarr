/**
 * Module for managing graph filters and generating filtered node/edge sets
 */

import { HIGHLIGHT_COLORS, KIND_SHAPES, LAYER_COLORS } from './graph-colors.js';

export class GraphFilters {
    constructor(loader) {
        this.loader = loader;
        this.selectedLayers = new Set();
        this.selectedKinds = new Set();
        this.selectedEdgeTypes = new Set();
        this.searchTerm = '';
        this.selectedInterface = '';
        this.showTransitiveEdges = true;
        
        // Initialize with all options selected
        this.resetFilters();
    }

    /**
     * Reset all filters to default state
     */
    resetFilters() {
        this.selectedLayers = new Set(this.loader.getLayers());
        this.selectedKinds = new Set(this.loader.getKinds());
        this.selectedEdgeTypes = new Set(this.loader.getEdgeTypes());
        this.searchTerm = '';
        // Default to blank (show nothing until user selects)
        this.selectedInterface = '__blank__';
        this.showTransitiveEdges = true;
    }

    /**
     * Set search term filter
     * @param {string} term
     */
    setSearchTerm(term) {
        this.searchTerm = term.toLowerCase();
    }

    /**
     * Set interface filter
     * @param {string} interfaceId
     */
    setInterfaceFilter(interfaceId) {
        this.selectedInterface = interfaceId;
    }

    /**
     * Toggle layer filter
     * @param {string} layer
     * @param {boolean} enabled
     */
    setLayerFilter(layer, enabled) {
        if (enabled) {
            this.selectedLayers.add(layer);
        } else {
            this.selectedLayers.delete(layer);
        }
    }

    /**
     * Toggle kind filter
     * @param {string} kind
     * @param {boolean} enabled
     */
    setKindFilter(kind, enabled) {
        if (enabled) {
            this.selectedKinds.add(kind);
        } else {
            this.selectedKinds.delete(kind);
        }
    }

    /**
     * Toggle edge type filter
     * @param {string} edgeType
     * @param {boolean} enabled
     */
    setEdgeTypeFilter(edgeType, enabled) {
        if (enabled) {
            this.selectedEdgeTypes.add(edgeType);
        } else {
            this.selectedEdgeTypes.delete(edgeType);
        }
    }

    /**
     * Set transitive edges visibility
     * @param {boolean} show
     */
    setShowTransitiveEdges(show) {
        this.showTransitiveEdges = show;
    }

    /**
     * Check if a node matches current filters
     * @param {Object} node
     * @returns {boolean}
     */
    nodeMatchesFilters(node) {
        // Interface filter (most restrictive)
        if (this.selectedInterface) {
            if (this.selectedInterface === '__blank__') {
                // Show nothing when blank is selected
                return false;
            } else if (this.selectedInterface === '__unreachable__') {
                // Show only nodes marked as unreachable from entrypoints
                if (node.reachable_from_interface) {
                    return false;
                }
            } else {
                const connections = this.loader.nodeConnectionMap.get(node.id);
                if (!connections || !connections.has(this.selectedInterface)) {
                    return false;
                }
            }
        }
        
        // Search term filter
        if (this.searchTerm && 
            !node.id.toLowerCase().includes(this.searchTerm) && 
            !node.name.toLowerCase().includes(this.searchTerm)) {
            return false;
        }
        
        // Layer filter
        if (!this.selectedLayers.has(node.layer)) {
            return false;
        }
        
        // Kind filter
        if (!this.selectedKinds.has(node.kind)) {
            return false;
        }
        
        return true;
    }

    /**
     * Generate filtered node and edge data for visualization
     * @returns {Object} { nodes: Array, edges: Array, stats: Object }
     */
    generateFilteredGraph() {
        const visibleNodeIds = new Set();
        const nodes = [];
        
        // Filter nodes
        this.loader.graphData.nodes.forEach(node => {
            if (this.nodeMatchesFilters(node)) {
                visibleNodeIds.add(node.id);
                
                // Check if this is the selected interface entrypoint
                const isSelectedInterface = (this.selectedInterface && 
                                             this.selectedInterface !== '__blank__' && 
                                             this.selectedInterface !== '__unreachable__' &&
                                             node.id === this.selectedInterface);
                
                // Random position in a 400x400 square around center to avoid clustering
                const spread = 200;
                
                // Calculate node size based on label length
                const labelLength = node.name.length;
                const baseSize = isSelectedInterface ? 30 : 20;
                const maxSize = isSelectedInterface ? 80 : 60;
                // Cylinders (modules) need less size multiplier since they're naturally wider
                const sizeMultiplier = node.kind === 'module' ? 1.5 : 2.5;
                const calculatedSize = Math.min(maxSize, Math.max(baseSize, labelLength * sizeMultiplier));
                
                nodes.push({
                    id: node.id,
                    label: node.name,
                    title: `${node.kind}: ${node.id}\nLayer: ${node.layer}\nFile: ${node.file}`,
                    shape: KIND_SHAPES[node.kind] || 'dot',
                    color: {
                        background: LAYER_COLORS[node.layer] || LAYER_COLORS.other,
                        border: isSelectedInterface ? HIGHLIGHT_COLORS.selectedInterface : '#ffffff',
                        highlight: {
                            background: HIGHLIGHT_COLORS.selectedInterface,
                            border: '#ffffff'
                        }
                    },
                    font: {
                        color: '#ffffff',
                        size: isSelectedInterface ? 14 : 11,
                        face: 'monospace',
                        strokeWidth: 0
                    },
                    borderWidth: isSelectedInterface ? 4 : 2,
                    size: calculatedSize,
                    // Make cylinders (modules) shorter to be less tall
                    heightConstraint: node.kind === 'module' ? { minimum: calculatedSize * 0.6, maximum: calculatedSize * 0.8 } : undefined,
                    layer: node.layer,
                    kind: node.kind,
                    data: node,
                    x: (Math.random() - 0.5) * spread,
                    y: (Math.random() - 0.5) * spread
                });
            }
        });

        // Generate edges
        const edges = this.generateFilteredEdges(visibleNodeIds);

        return {
            nodes,
            edges,
            stats: {
                totalNodes: this.loader.graphData.nodes.length,
                totalEdges: this.loader.graphData.edges.length,
                visibleNodes: nodes.length,
                visibleEdges: edges.length
            }
        };
    }

    /**
     * Generate filtered edges based on visible nodes
     * @param {Set} visibleNodeIds
     * @returns {Array}
     */
    generateFilteredEdges(visibleNodeIds) {
        const edges = [];
        const directEdgeIds = new Set();
        
        // Add direct edges where both endpoints are visible
        this.loader.graphData.edges.forEach((edge, idx) => {
            if (visibleNodeIds.has(edge.source_id) && 
                visibleNodeIds.has(edge.target_id) &&
                this.selectedEdgeTypes.has(edge.type)) {
                directEdgeIds.add(`${edge.source_id}:${edge.target_id}`);
                edges.push({
                    id: idx,
                    from: edge.source_id,
                    to: edge.target_id,
                    label: edge.type,
                    title: `${edge.type}\nLine: ${edge.lineno || 'N/A'}`,
                    arrows: 'to',
                    color: {
                        color: '#666666',
                        highlight: '#ffd700'
                    },
                    font: {
                        color: '#ffffff',
                        size: 11,
                        align: 'top',
                        background: 'rgba(0, 0, 0, 0.8)',
                        strokeWidth: 0
                    },
                    type: edge.type,
                    smooth: {
                        enabled: true,
                        type: 'curvedCW',
                        roundness: 0.3
                    },
                    length: 50
                });
            }
        });

        // Add transitive edges if enabled
        if (this.showTransitiveEdges && visibleNodeIds.size > 0) {
            const transitiveEdges = this.computeTransitiveEdges(visibleNodeIds, directEdgeIds);
            edges.push(...transitiveEdges);
        }

        return edges;
    }

    /**
     * Compute transitive edges through hidden nodes
     * @param {Set} visibleNodeIds
     * @param {Set} directEdgeIds - Set of "source:target" strings for direct edges
     * @returns {Array}
     */
    computeTransitiveEdges(visibleNodeIds, directEdgeIds) {
        const transitiveEdges = [];
        const transitiveEdgeMap = new Map(); // "source:target" -> edge type
        
        // Build adjacency map for BFS
        const adjacencyMap = new Map();
        this.loader.graphData.edges.forEach(edge => {
            if (!this.selectedEdgeTypes.has(edge.type)) return;
            if (!adjacencyMap.has(edge.source_id)) {
                adjacencyMap.set(edge.source_id, []);
            }
            adjacencyMap.get(edge.source_id).push({
                target: edge.target_id,
                type: edge.type
            });
        });

        // BFS from each visible node to find connections through hidden nodes
        visibleNodeIds.forEach(sourceId => {
            const queue = [{id: sourceId, path: [], edgeType: null}];
            const visited = new Set([sourceId]);
            
            while (queue.length > 0) {
                const {id: currentId, path, edgeType} = queue.shift();
                
                // If we reached another visible node (not the source), record connection
                if (currentId !== sourceId && visibleNodeIds.has(currentId)) {
                    const key = `${sourceId}:${currentId}`;
                    if (!transitiveEdgeMap.has(key)) {
                        transitiveEdgeMap.set(key, edgeType || 'transitive');
                    }
                    continue; // Don't traverse beyond visible nodes
                }
                
                // Explore neighbors (limit depth to prevent infinite loops)
                if (path.length < 5) {
                    const neighbors = adjacencyMap.get(currentId) || [];
                    neighbors.forEach(({target, type}) => {
                        if (!visited.has(target)) {
                            visited.add(target);
                            queue.push({
                                id: target,
                                path: [...path, currentId],
                                edgeType: edgeType || type
                            });
                        }
                    });
                }
            }
        });

        // Convert transitive edge map to edge array, excluding direct edges
        let transitiveId = this.loader.graphData.edges.length;
        transitiveEdgeMap.forEach((type, key) => {
            if (!directEdgeIds.has(key)) {
                const [from, to] = key.split(':');
                transitiveEdges.push({
                    id: `transitive_${transitiveId++}`,
                    from: from,
                    to: to,
                    label: type,
                    title: `Transitive: ${type}\n(through hidden nodes)`,
                    arrows: 'to',
                    color: {
                        color: '#888888',
                        highlight: '#ffd700'
                    },
                    font: {
                        color: '#aaaaaa',
                        size: 10,
                        align: 'top',
                        background: 'rgba(0, 0, 0, 0.7)',
                        strokeWidth: 0
                    },
                    type: type,
                    smooth: {
                        enabled: true,
                        type: 'curvedCW',
                        roundness: 0.3
                    },
                    dashes: true,
                    length: 50
                });
            }
        });

        return transitiveEdges;
    }
}
