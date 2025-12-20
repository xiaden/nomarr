/**
 * Main GraphNetwork class - coordinates all network operations
 */

import { updateEdgeVisibility } from './edge-visibility.js';
import { clearGraph, updateGraph } from './graph-updates.js';
import { initializeNetwork } from './initialization.js';
import { clearSelection, focusNode, highlightPath } from './selection.js';
import { getEdgeStyle, getNodeStyle } from './state-styles.js';
import { destroy, fit, getNodeColor, getSelectedNodes, getStats } from './utils.js';

export class GraphNetwork {
    constructor(containerId) {
        this.containerId = containerId;
        this.network = null;
        this.nodes = null;
        this.edges = null;
        this.eventHandlers = {};
        this.selectedNodeId = null;
        this.allEdges = [];
        this.maxVisibleEdges = 1200;
        this.pathHighlight = null;
        this.physicsPolicy = null;  // Initialized after network creation
        this.debugBlackBox = false;  // Set to true to enable black box debugging
    }

    // Initialization
    initialize() {
        initializeNetwork(this);
    }

    // Event handling
    on(eventName, handler) {
        if (!this.eventHandlers[eventName]) {
            this.eventHandlers[eventName] = [];
        }
        this.eventHandlers[eventName].push(handler);
    }

    triggerEvent(eventName, data) {
        if (this.eventHandlers[eventName]) {
            this.eventHandlers[eventName].forEach(handler => handler(data));
        }
    }

    // Graph updates
    async clearGraph() {
        return clearGraph(this);
    }

    async updateGraph(nodes, edges, shouldCancel = null, userPhysicsPreference = false) {
        return updateGraph(this, nodes, edges, shouldCancel, userPhysicsPreference);
    }

    // Selection and highlighting
    clearSelection() {
        clearSelection(this);
    }

    highlightPath(pathHighlight) {
        highlightPath(this, pathHighlight);
    }
    
    /**
     * Set path highlight using state-based styling
     * @param {string[]} nodeIds - IDs of nodes in the path
     * @param {string[]} edgeIds - IDs of edges in the path
     */
    setPathHighlight(nodeIds, edgeIds) {
        // Get all nodes and edges
        const allNodes = this.nodes.get();
        const allEdges = this.edges.get();
        
        // Apply PATH state to specified nodes/edges, DIMMED to others
        const nodeUpdates = allNodes.map(node => {
            const newState = nodeIds.includes(node.id) ? 'PATH' : 'DIMMED';
            if (node.renderState !== newState) {
                return { ...node, ...getNodeStyle(node, newState), renderState: newState };
            }
            return null;
        }).filter(Boolean);
        
        const edgeUpdates = allEdges.map(edge => {
            const newState = edgeIds.includes(edge.id) ? 'PATH' : 'DIMMED';
            const isVisible = nodeIds.includes(edge.from) && nodeIds.includes(edge.to);
            if (edge.renderState !== newState) {
                return { ...edge, ...getEdgeStyle(edge, newState, isVisible), renderState: newState };
            }
            return null;
        }).filter(Boolean);
        
        this.nodes.update(nodeUpdates);
        this.edges.update(edgeUpdates);
    }

    focusNode(nodeId, scale = 1.5) {
        focusNode(this, nodeId, scale);
    }

    // Edge visibility
    updateEdgeVisibility() {
        updateEdgeVisibility(this);
    }

    // Utility methods
    fit() {
        fit(this);
    }

    enablePhysics() {
        if (this.physicsPolicy) {
            this.physicsPolicy.setUserPhysicsEnabled(true);
        }
    }

    disablePhysics() {
        if (this.physicsPolicy) {
            this.physicsPolicy.setUserPhysicsEnabled(false);
        }
    }

    reheatPhysics() {
        if (this.physicsPolicy) {
            this.physicsPolicy.reheat();
        }
    }

    getNodeColor(node) {
        return getNodeColor(node);
    }

    getSelectedNodes() {
        return getSelectedNodes(this);
    }

    getStats() {
        return getStats(this);
    }

    destroy() {
        destroy(this);
    }
}
