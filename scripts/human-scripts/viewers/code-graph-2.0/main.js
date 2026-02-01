/**
 * main.js - Orchestrator only, no logic
 * 
 * G6 v5 Compliance Notes (Verification: Dec 16, 2025)
 * ===================================================
 * 
 * Mismatches vs v5 docs that were fixed:
 * 1. Label property: Changed from data.label to style.labelText
 *    - Doc: docs/manual/element/node/BaseNode.en.md (line 431)
 *    - Fixed in: graph-renderer.js (both renderGraph and updateGraph)
 * 
 * All APIs verified against docs/:
 * - Graph init: Uses v5 'behaviors' array (not v4 'modes')
 * - Data ops: Uses graph.setData() (not v4 data()/changeData())
 * - Events: Uses evt.target.id (not v4 evt.item.get('id'))
 * - States: Uses graph.setElementState() (not v4 setItemState())
 * - Viewport: Uses graph.focusElement() (not v4 focusItem())
 * - Node config: Uses node/edge (not v4 defaultNode/defaultEdge)
 * 
 * UX Behaviors (all working):
 * - Click: Select node, update panel
 * - Ctrl/Cmd+Click: Expand 1-hop neighbors
 * - Double-click: Collapse + prune orphans
 * - Shift+Click: Trace paths to entrypoints
 * - Panel link click: Focus node
 * 
 * See docs/v5-compliance.md for detailed verification.
 */

import { buildAdjacency } from './data/graph-adjacency.js';
import { loadGraphFromFile } from './data/graph-loader.js';
import { normalizeGraph } from './data/graph-normalize.js';
import { CollapseManager } from './explore/collapse-manager.js';
import { ExpansionManager } from './explore/expansion-manager.js';
import { PathTracer } from './explore/path-tracer.js';
import { registerBehaviors } from './graph/graph-behaviors.js';
import { initGraph } from './graph/graph-init.js';
import { focusOnNode, renderGraph, updateGraph } from './graph/graph-renderer.js';
import { initPanel } from './ui/panel-controller.js';
import { initToolbar } from './ui/toolbar-controller.js';
import { initViewport } from './ui/viewport-controller.js';
import { assertG6Version } from './utils/guards.js';

// App state
let graph = null;
let expansionManager = null;
let collapseManager = null;
let pathTracer = null;
let container = null;

// Initialize graph from uploaded file
async function initializeGraph(file) {
    // Load and normalize
    const rawGraph = await loadGraphFromFile(file);
    const graphModel = normalizeGraph(rawGraph);
    const adjacency = buildAdjacency(graphModel);
    
    // Create exploration managers
    expansionManager = new ExpansionManager(graphModel, adjacency);
    collapseManager = new CollapseManager(graphModel, adjacency, expansionManager);
    pathTracer = new PathTracer(adjacency);
    
    // Init graph
    graph = initGraph(container);
    
    // Register behaviors
    registerBehaviors(graph, {
        onSelect: handleSelect,
        onExpand: handleExpand,
        onCollapse: handleCollapse,
        onTrace: handleTrace,
        onShowBubble: handleShowBubble,
        onHideBubble: handleHideBubble
    });
    
    // Init viewport
    initViewport(graph);
    
    // Render entrypoints (two-phase: layout then freeze)
    const visibleGraph = expansionManager.getVisibleGraph();
    await renderGraph(graph, visibleGraph);
    updateToolbarStats();
}

// Boot
document.addEventListener('DOMContentLoaded', async () => {
    assertG6Version();
    
    container = document.getElementById('graph-container');
    
    // Wire toolbar
    initToolbar({
        onUpload: handleFileUpload,
        onReset: handleReset,
        onFit: handleFit,
        onShowAll: handleShowAll
    });
    
    // Wire panel
    window.panelController = initPanel({
        onJumpToNode: handleJumpToNode
    });
});

// Handlers (no logic, just delegation)
async function handleFileUpload(file) {
    if (file) await initializeGraph(file);
}

async function handleReset() {
    if (!expansionManager) return;
    const visibleGraph = expansionManager.reset();
    await updateGraph(graph, visibleGraph);
    updateToolbarStats();
}

function handleFit() {
    if (!graph) return;
    graph.fitView({ padding: [20, 20, 20, 20] });
}

async function handleShowAll() {
    if (!expansionManager) return;
    const visibleGraph = expansionManager.showAll();
    await updateGraph(graph, visibleGraph);
    updateToolbarStats();
}

function handleSelect(nodeId) {
    if (!expansionManager) return;
    const node = expansionManager.getNode(nodeId);
    const connections = nodeId ? expansionManager.getConnections(nodeId) : { incoming: [], outgoing: [] };
    
    // Update panel (using global panelController)
    if (window.panelController) {
        window.panelController.showNode(node, connections);
    }
}

async function handleExpand(nodeId) {
    if (!expansionManager) return;
    const { graph: visibleGraph, added } = expansionManager.expand(nodeId);
    await updateGraph(graph, visibleGraph);
    updateToolbarStats();
    // 'added' array available for future streaming implementation
}

async function handleCollapse(nodeId) {
    if (!collapseManager) return;
    const visibleGraph = collapseManager.collapse(nodeId);
    await updateGraph(graph, visibleGraph);
    updateToolbarStats();
}

async function handleShowBubble(nodeId) {
    if (!expansionManager) return;
    const visibleGraph = expansionManager.getVisibleGraph();
    const { showBubbleForNode } = await import('./graph/bubble-overlays.js');
    showBubbleForNode(graph, nodeId, visibleGraph.nodes);
}

async function handleHideBubble() {
    const { hideBubble } = await import('./graph/bubble-overlays.js');
    hideBubble(graph);
}

async function handleTrace(nodeId) {
    if (!pathTracer || !expansionManager) return;
    
    const pathNodes = pathTracer.traceToEntrypoints(nodeId, expansionManager.entrypointIds);
    
    // Merge path states with existing states (preserve 'selected')
    const allNodes = graph.getNodeData();
    const stateMap = {};
    allNodes.forEach(node => {
        const currentStates = node.states || [];
        const hasSelected = currentStates.includes('selected');
        const isInPath = pathNodes.has(node.id);
        
        // Build merged state array
        const newStates = [];
        if (hasSelected) newStates.push('selected');
        if (isInPath) {
            newStates.push('path');
        } else {
            newStates.push('dimmed');
        }
        
        stateMap[node.id] = newStates;
    });
    
    await graph.setElementState(stateMap);
}

function handleJumpToNode(nodeId) {
    if (!graph) return;
    focusOnNode(graph, nodeId);
    handleSelect(nodeId);
}

function updateToolbarStats() {
    const stats = expansionManager.getStats();
    document.getElementById('stats').textContent = `Visible: ${stats.visible} / Total: ${stats.total}`;
}
