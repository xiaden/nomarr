/**
 * Main orchestration module - wires all components together
 */

import { ExpansionManager } from './graph-expansion.js';
import { GraphFilters } from './graph-filters.js';
import { GraphLoader } from './graph-loader.js';
import { GraphNetwork } from './graph-network/index.js';
import { GraphUI } from './graph-ui.js';
import { PathTracer } from './path-tracer.js';

class CodeGraphViewer {
    constructor() {
        this.loader = new GraphLoader();
        this.filters = null;
        this.network = null;
        this.ui = null;
        this.pathTracer = null;
        this.expansionManager = null;
        this.isRendering = false;
        this.cancelRender = false;
        this.cancelResolve = null;
        this.userPhysicsPreference = true;  // Match checkbox default (checked)
        this.isExpanding = false;  // Track if expansion animation is in progress
        this.autoCenterDuringExpansion = true;  // Allow user to disable auto-center
    }

    /**
     * Initialize the viewer application
     */
    async initialize() {
        // Create UI first for showing file input
        this.ui = new GraphUI(null, null);
        
        // Show file input dialog
        this.ui.showFileInput(async (file) => {
            try {
                this.ui.showLoading('Loading graph...');
                const progressCallback = (percentage, completed, total) => {
                    this.ui.updateProgress(percentage, completed, total);
                };
                await this.loader.loadFromFile(file, progressCallback);
                await this.setupViewer();
            } catch (error) {
                console.error('Error loading file:', error);
                this.ui.showError(error.message);
            }
        });
    }

    /**
     * Setup graph selector dropdown to switch between detailed/simplified
     */
    setupGraphSelector() {
        const selector = document.getElementById('graphSelector');
        if (!selector) return;

        selector.addEventListener('change', async (e) => {
            const selectedPath = e.target.value;
            
            // Show loading bar
            const loadingBar = document.getElementById('loadingBar');
            const loadingBarText = document.getElementById('loadingBarText');
            loadingBar.style.display = 'block';
            loadingBarText.textContent = 'Loading graph...';

            try {
                const progressCallback = (percentage, completed, total) => {
                    loadingBarText.textContent = `Building connection map... ${percentage}% (${completed}/${total})`;
                };
                
                const loaded = await this.loader.loadGraph(selectedPath, progressCallback);
                
                if (loaded) {
                    loadingBarText.textContent = 'Rebuilding visualization...';
                    
                    // Clear existing network
                    if (this.network && this.network.network) {
                        this.network.network.destroy();
                    }
                    
                    // Reinitialize viewer with new graph
                    this.filters = new GraphFilters(this.loader);
                    this.network = new GraphNetwork('network');
                    this.ui = new GraphUI(this.loader, this.filters);
                    this.pathTracer = new PathTracer(this.loader);
                    
                    // Wire up event handlers
                    this.wireEventHandlers();
                    
                    // Initialize UI controls
                    this.ui.initializeControls();
                    
                    // Initialize network
                    this.network.initialize();
                    
                    // Apply filters and render (this will update stats)
                    await this.applyFiltersAndRender();
                    
                    // Hide loading bar
                    loadingBar.style.display = 'none';
                } else {
                    console.error('Failed to load graph:', selectedPath);
                    alert('Failed to load selected graph. Check console for details.');
                    loadingBar.style.display = 'none';
                }
            } catch (error) {
                console.error('Error switching graphs:', error);
                alert('Error loading graph: ' + error.message);
                loadingBar.style.display = 'none';
            }
        });
    }



    /**
     * Setup viewer components after data is loaded
     */
    async setupViewer() {
        // Initialize components
        this.filters = new GraphFilters(this.loader);
        this.network = new GraphNetwork('network');
        
        // Update UI with loader and filters (UI was created earlier for file input)
        this.ui.loader = this.loader;
        this.ui.filters = this.filters;
        
        this.pathTracer = new PathTracer(this.loader);
        
        // Initialize expansion manager with ALL graph data (unfiltered)
        const allData = this.filters.generateUnfilteredGraph();
        const entrypointIds = this.loader.findApplicationEntrypoints();
        console.log('Initializing ExpansionManager with', allData.nodes.length, 'nodes and', entrypointIds.size, 'entrypoint IDs');
        this.expansionManager = new ExpansionManager(allData.nodes, allData.edges, entrypointIds);
        
        // Wire up event handlers
        this.wireEventHandlers();

        // Initialize UI controls
        this.ui.initializeControls();

        // Initialize network
        this.network.initialize();

        // Hide loading and show main UI
        this.ui.hideLoading();

        // Initialize with entrypoints only (progressive disclosure)
        await this.renderEntrypointsOnly();
    }

    /**
     * Wire up event handlers between components
     */
    wireEventHandlers() {
        // UI filter changes trigger graph update
        this.ui.on('filterChange', () => {
            this.applyFiltersAndRender();
        });

        // UI fit network button
        this.ui.on('fitNetwork', () => {
            this.network.fit();
        });

        // UI clear selection button
        this.ui.on('clearSelection', () => {
            this.network.clearSelection();
            this.ui.clearNodeDetails();
        });

        // Network expansion events
        this.network.on('expandNode', (nodeId) => {
            this.expandNode(nodeId);
            this.ui.displayNodeDetails(nodeId);
        });
        
        this.network.on('collapseNode', (nodeId) => {
            this.collapseNode(nodeId);
        });
        
        this.network.on('traceNode', (nodeId) => {
            this.tracePathsFromNode(nodeId);
        });
        
        this.network.on('selectNodeOnly', (nodeId) => {
            this.selectNodeOnly(nodeId);
            this.ui.displayNodeDetails(nodeId);
        });

        // Network load progress updates
        this.network.on('loadProgress', (progressData) => {
            this.updateLoadingBar(progressData);
        });

        // UI physics toggle - store user preference
        this.ui.on('togglePhysics', (enabled) => {
            this.userPhysicsPreference = enabled;
            if (enabled) {
                this.network.enablePhysics();
            } else {
                this.network.disablePhysics();
            }
        });

        // Reheat physics button
        this.ui.on('reheatPhysics', () => {
            this.network.reheatPhysics();
        });
        
        // Detect user viewport changes during expansion (stop auto-centering)
        this.network.on('zoom', () => {
            if (this.isExpanding) {
                this.autoCenterDuringExpansion = false;
            }
        });
        
        this.network.on('dragStart', () => {
            if (this.isExpanding) {
                this.autoCenterDuringExpansion = false;
            }
        });
    }

    /**
     * Update loading bar with progress
     */
    updateLoadingBar(progressData) {
        const loadingBar = document.getElementById('loadingBar');
        const loadingBarFill = document.getElementById('loadingBarFill');
        const loadingBarText = document.getElementById('loadingBarText');

        if (progressData.progress === 0) {
            // Show loading bar
            loadingBar.style.display = 'block';
        }

        // Update progress
        loadingBarFill.style.width = `${progressData.progress}%`;
        loadingBarText.textContent = `Loading nodes... ${progressData.current}/${progressData.total} batches (${progressData.progress}%)`;

        if (progressData.progress === 100) {
            // Hide loading bar after completion
            setTimeout(() => {
                loadingBar.style.display = 'none';
            }, 1000);
        }
    }

    /**
     * Apply current filters and update visualization
     */
    async applyFiltersAndRender() {
        // Cancel any ongoing render and wait for confirmation
        if (this.isRendering) {
            this.cancelRender = true;
            
            // Wait for the render to actually stop
            await new Promise(resolve => {
                this.cancelResolve = resolve;
                // Timeout after 2 seconds if render doesn't stop
                setTimeout(resolve, 2000);
            });
        }
        
        // Clear the entire graph before rendering new one
        await this.network.clearGraph();
        
        this.isRendering = true;
        this.cancelRender = false;
        this.cancelResolve = null;
        
        try {
            const result = this.filters.generateFilteredGraph();
            const renderResult = await this.network.updateGraph(
                result.nodes, 
                result.edges, 
                () => this.cancelRender,
                this.userPhysicsPreference
            );
            
            // Only update stats if render completed successfully
            if (!renderResult.cancelled) {
                this.ui.updateStats(result.stats);
            }
        } finally {
            this.isRendering = false;
            
            // If we were cancelled, notify the waiter
            if (this.cancelRender && this.cancelResolve) {
                this.cancelResolve();
            }
            
            this.cancelRender = false;
            this.cancelResolve = null;
        }
    }

    /**
     * Render only entrypoint nodes initially
     */
    async renderEntrypointsOnly() {
        const entrypointData = this.expansionManager.initializeEntrypoints();
        console.log('Rendering entrypoints:', entrypointData.nodes.length, 'nodes');
        console.log('Entrypoint node IDs:', entrypointData.nodes.map(n => n.id));
        const allData = this.expansionManager.getVisibleGraph();
        await this.network.updateGraph(
            entrypointData.nodes,
            entrypointData.edges,
            null,
            true  // Keep global physics enabled
        );
        
        // Update stats (total = all data, visible = entrypoints only)
        const totalNodes = this.filters.generateUnfilteredGraph().nodes.length;
        const totalEdges = this.filters.generateUnfilteredGraph().edges.length;
        this.ui.updateStats({ 
            totalNodes, 
            totalEdges, 
            visibleNodes: entrypointData.nodes.length, 
            visibleEdges: entrypointData.edges.length 
        });
    }

    /**
     * Expand a node - show its neighbors with animation
     */
    async expandNode(nodeId) {
        console.log('expandNode called for:', nodeId);
        
        // Focus on the clicked node
        this.network.network.focus(nodeId, {
            scale: 1.5,
            animation: { duration: 500, easingFunction: 'easeInOutQuad' }
        });
        
        // Get neighbors to add
        const { newNodes, newEdges } = this.expansionManager.expandNode(nodeId);
        console.log('Expansion returned:', newNodes.length, 'new nodes,', newEdges.length, 'new edges');
        
        if (newNodes.length === 0) {
            console.log('No new nodes to add, node already expanded or has no neighbors');
            return;  // Already expanded
        }
        
        // Fix all currently visible nodes in place BUT keep physics enabled
        // This way they act as immovable obstacles that repel new nodes
        const currentNodes = this.network.nodes.get();
        this.network.nodes.update(currentNodes.map(n => ({
            id: n.id,
            fixed: { x: true, y: true },
            physics: true  // Keep physics ON so they repel new nodes
        })));
        
        console.log('Existing nodes frozen, adding new nodes with physics enabled');
        
        // Get parent position for spawning new nodes
        const parentPos = this.network.network.getPosition(nodeId);
        
        // Add all nodes at once in a circle pattern (further out to avoid overlap)
        const radius = 250;  // Increased from 150 to give more space
        const newNodeData = newNodes.map((node, i) => {
            const angle = (i / newNodes.length) * Math.PI * 2;
            return {
                ...node,
                x: parentPos.x + Math.cos(angle) * radius,
                y: parentPos.y + Math.sin(angle) * radius,
                physics: true,  // CRITICAL: Enable physics for animation
                fixed: false    // Allow movement
            };
        });
        
        // Add all nodes at once
        this.network.nodes.add(newNodeData);
        console.log('Added', newNodeData.length, 'nodes with physics=true at radius', radius);
        
        // Add all edges
        this.network.edges.add(newEdges);
        
        // Start physics and wait for stabilization
        this.network.network.setOptions({ physics: { enabled: true } });
        console.log('Physics explicitly enabled, waiting for stabilization');
        
        // Function to freeze new nodes after settling
        const freezeNewNodes = () => {
            console.log('Freezing newly expanded nodes');
            const addedIds = newNodes.map(n => n.id);
            this.network.nodes.update(addedIds.map(id => ({
                id: id,
                fixed: { x: true, y: true },
                physics: true  // Keep physics ON so they can still repel future nodes
            })));
            console.log('Newly expanded nodes frozen');
            
            // Update stats
            const totalNodes = this.filters.generateUnfilteredGraph().nodes.length;
            const totalEdges = this.filters.generateUnfilteredGraph().edges.length;
            this.ui.updateStats({
                totalNodes,
                totalEdges,
                visibleNodes: this.network.nodes.length,
                visibleEdges: this.network.edges.length
            });
        };
        
        // Set up both stabilization event AND fallback timeout
        let stabilizationHandled = false;
        
        this.network.network.once('stabilizationIterationsDone', () => {
            if (!stabilizationHandled) {
                console.log('Physics stabilization complete (event)');
                stabilizationHandled = true;
                freezeNewNodes();
            }
        });
        
        // Fallback timeout in case stabilization event doesn't fire
        setTimeout(() => {
            if (!stabilizationHandled) {
                console.log('Physics stabilization timeout reached (fallback)');
                stabilizationHandled = true;
                freezeNewNodes();
            }
        }, 3000);  // 3 second fallback
    }

    /**
     * Collapse a node - remove it and orphaned neighbors
     */
    collapseNode(nodeId) {
        const { removedNodeIds, removedEdgeIds } = this.expansionManager.collapseNode(nodeId);
        
        if (removedNodeIds.length > 0) {
            this.network.nodes.remove(removedNodeIds);
            this.network.edges.remove(removedEdgeIds);
            
            const totalNodes = this.filters.generateUnfilteredGraph().nodes.length;
            const totalEdges = this.filters.generateUnfilteredGraph().edges.length;
            this.ui.updateStats({
                totalNodes,
                totalEdges,
                visibleNodes: this.network.nodes.length,
                visibleEdges: this.network.edges.length
            });
        }
    }

    /**
     * Trace paths from node to entrypoints
     */
    async tracePathsFromNode(nodeId) {
        // Show progress indicator
        this.ui.showLoading('Tracing paths...');
        
        const { pathNodeIds, pathEdgeIds } = await new Promise(resolve => {
            setTimeout(() => {
                resolve(this.expansionManager.tracePaths(nodeId, (current, total, percent) => {
                    this.ui.updateProgress(percent, current, total);
                }));
            }, 10);
        });
        
        this.ui.hideLoading();
        
        // Apply PATH state to traced nodes/edges using state-styles
        this.network.setPathHighlight(pathNodeIds, pathEdgeIds);
    }

    /**
     * Select node without expansion (Ctrl+click)
     */
    selectNodeOnly(nodeId) {
        // Just update the left panel
        this.ui.displayNodeDetails(nodeId);
    }
    
    /**
     * Focus on a node from the info panel (click on connection)
     * Does not expand, just centers the viewport
     */
    focusNodeFromPanel(nodeId) {
        this.network.network.focus(nodeId, {
            scale: 1.5,
            animation: { duration: 500, easingFunction: 'easeInOutQuad' }
        });
        // Update selection state
        this.network.selectedNodeId = nodeId;
        this.network.updateEdgeVisibility();
        this.ui.displayNodeDetails(nodeId);
    }
}

// Initialize viewer when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        const viewer = new CodeGraphViewer();
        viewer.initialize();
        window.codeGraphViewer = viewer;  // Expose for panel navigation
    });
} else {
    const viewer = new CodeGraphViewer();
    viewer.initialize();
    window.codeGraphViewer = viewer;  // Expose for panel navigation
}
