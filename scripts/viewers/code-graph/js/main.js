/**
 * Main orchestration module - wires all components together
 */

import { GraphFilters } from './graph-filters.js';
import { GraphLoader } from './graph-loader.js';
import { GraphNetwork } from './graph-network.js';
import { GraphUI } from './graph-ui.js';
import { PathTracer } from './path-tracer.js';

class CodeGraphViewer {
    constructor() {
        this.loader = new GraphLoader();
        this.filters = null;
        this.network = null;
        this.ui = null;
        this.pathTracer = null;
        this.isRendering = false;
        this.cancelRender = false;
        this.cancelResolve = null;
    }

    /**
     * Initialize the viewer application
     */
    async initialize() {
        try {
            // Try to load graph from default location
            const loaded = await this.loader.loadGraph('../../outputs/code_graph.json');
            
            if (loaded) {
                await this.setupViewer();
                this.setupGraphSelector();
            } else {
                // Show file input if auto-load failed
                this.showFileInput();
            }
        } catch (error) {
            console.error('Initialization error:', error);
            this.showFileInput();
        }
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
                const loaded = await this.loader.loadGraph(selectedPath);
                
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
     * Show file input for manual file selection
     */
    showFileInput() {
        // Create temporary UI just for file selection
        const tempUI = {
            showFileInput: (onFileSelected) => {
                document.getElementById('loading').innerHTML = `
                    <div style="text-align: center; color: #cccccc; padding: 32px;">
                        <h2 style="color: #569cd6; margin-bottom: 16px;">Load Code Graph</h2>
                        <p style="margin-bottom: 16px; font-size: 14px;">Select the code_graph.json file to visualize:</p>
                        <input type="file" id="fileInput" accept=".json" style="display: block; margin: 0 auto 16px; padding: 8px;">
                        <p style="font-size: 12px; color: #858585; margin-top: 24px;">
                            Or run a local server: <code style="background: #2d2d30; padding: 2px 6px; border-radius: 3px;">python -m http.server 8000</code>
                        </p>
                    </div>
                `;

                document.getElementById('fileInput').addEventListener('change', (e) => {
                    if (e.target.files[0]) {
                        onFileSelected(e.target.files[0]);
                    }
                });
            },
            showError: (message) => {
                document.getElementById('loading').innerHTML = `
                    <div style="text-align: center; color: #cccccc; padding: 32px;">
                        <h2 style="color: #d16969; margin-bottom: 16px;">❌ Error</h2>
                        <p style="margin-bottom: 16px; font-size: 14px; color: #d4d4d4;">${message}</p>
                        <button onclick="location.reload()" style="padding: 8px 16px; background: #0e639c; border: none; border-radius: 3px; color: white; cursor: pointer;">
                            Reload Page
                        </button>
                    </div>
                `;
            }
        };

        tempUI.showFileInput(async (file) => {
            try {
                document.getElementById('loading').innerHTML = `
                    <div style="text-align: center; color: #cccccc; padding: 32px;">
                        <div class="spinner"></div>
                        <div style="margin-top: 16px;">Loading graph...</div>
                    </div>
                `;
                
                await this.loader.loadFromFile(file);
                await this.setupViewer();
            } catch (error) {
                console.error('Error loading file:', error);
                tempUI.showError(error.message);
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
        this.ui = new GraphUI(this.loader, this.filters);
        this.pathTracer = new PathTracer(this.loader);

        // Show loading progress
        this.ui.showLoading('Building interface connection map...');
        
        // Wire up event handlers
        this.wireEventHandlers();

        // Initialize UI controls
        this.ui.initializeControls();

        // Initialize network
        this.network.initialize();

        // Hide loading and show main UI
        this.ui.hideLoading();

        // Apply initial filters and render
        this.applyFiltersAndRender();
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

        // Network node click displays details and highlights path
        this.network.on('nodeClick', (nodeId) => {
            this.ui.displayNodeDetails(nodeId);
            
            // Highlight path to entrypoint (respect interface filter)
            if (this.pathTracer) {
                try {
                    const selectedInterface = this.filters.selectedInterface;
                    const limitToEntrypoint = (selectedInterface && 
                                              selectedInterface !== '__blank__' && 
                                              selectedInterface !== '__unreachable__') 
                        ? selectedInterface 
                        : null;
                    const pathHighlight = this.pathTracer.getPathHighlight(nodeId, 5, limitToEntrypoint);
                    this.network.highlightPath(pathHighlight);
                } catch (error) {
                    console.error('Error highlighting path:', error);
                }
            }
        });

        // Network load progress updates
        this.network.on('loadProgress', (progressData) => {
            this.updateLoadingBar(progressData);
        });

        // UI physics toggle
        this.ui.on('togglePhysics', (enabled) => {
            if (enabled) {
                this.network.enablePhysics();
            } else {
                this.network.disablePhysics();
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
            await this.network.updateGraph(result.nodes, result.edges, () => this.cancelRender);
            
            if (!this.cancelRender) {
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
}

// Initialize viewer when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        const viewer = new CodeGraphViewer();
        viewer.initialize();
    });
} else {
    const viewer = new CodeGraphViewer();
    viewer.initialize();
}
