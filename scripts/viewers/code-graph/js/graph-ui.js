/**
 * Module for managing UI interactions and display updates
 */

export class GraphUI {
    constructor(loader, filters) {
        this.loader = loader;
        this.filters = filters;
        this.selectedNodeId = null;
    }

    /**
     * Initialize filter controls
     */
    initializeControls() {
        this.populateInterfaceFilter();
        this.populateLayerFilters();
        this.populateKindFilters();
        this.populateEdgeTypeFilters();
        this.attachEventListeners();
    }

    /**
     * Populate interface filter dropdown
     */
    populateInterfaceFilter() {
        const select = document.getElementById('interfaceFilter');
        
        // Add blank option at the top
        const blankOption = document.createElement('option');
        blankOption.value = '__blank__';
        blankOption.textContent = '(Select an interface to view)';
        select.insertBefore(blankOption, select.firstChild);
        
        this.loader.interfaceNodes.forEach(node => {
            const option = document.createElement('option');
            option.value = node.id;
            const fileName = node.file.split('/').pop();
            option.textContent = `${node.name} (${fileName})`;
            select.appendChild(option);
        });

        // Default to blank (show nothing)
        select.value = '__blank__';
    }

    /**
     * Populate layer filter checkboxes
     */
    populateLayerFilters() {
        const container = document.getElementById('layerFilters');
        this.createCheckboxGroup(container, this.loader.getLayers(), (layer, checked) => {
            this.filters.setLayerFilter(layer, checked);
        });
    }

    /**
     * Populate kind filter checkboxes
     */
    populateKindFilters() {
        const container = document.getElementById('kindFilters');
        this.createCheckboxGroup(container, this.loader.getKinds(), (kind, checked) => {
            this.filters.setKindFilter(kind, checked);
        });
    }

    /**
     * Populate edge type filter checkboxes
     */
    populateEdgeTypeFilters() {
        const container = document.getElementById('edgeTypeFilters');
        this.createCheckboxGroup(container, this.loader.getEdgeTypes(), (edgeType, checked) => {
            this.filters.setEdgeTypeFilter(edgeType, checked);
        });
    }

    /**
     * Helper to create a group of checkboxes
     * @param {HTMLElement} container
     * @param {Array} items
     * @param {Function} onChange
     */
    createCheckboxGroup(container, items, onChange) {
        items.forEach(item => {
            const label = document.createElement('label');
            label.className = 'checkbox-label';
            
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.value = item;
            checkbox.checked = true;
            checkbox.onchange = (e) => {
                onChange(item, e.target.checked);
                this.triggerFilterChange();
            };
            
            label.appendChild(checkbox);
            label.appendChild(document.createTextNode(item));
            container.appendChild(label);
        });
    }

    /**
     * Attach event listeners to UI controls
     */
    attachEventListeners() {
        // Search input
        document.getElementById('search').addEventListener('input', (e) => {
            this.filters.setSearchTerm(e.target.value);
            this.triggerFilterChange();
        });

        // Interface filter
        document.getElementById('interfaceFilter').addEventListener('change', (e) => {
            this.filters.setInterfaceFilter(e.target.value);
            this.triggerFilterChange();
        });

        // Transitive edges checkbox
        document.getElementById('showTransitiveEdges').addEventListener('change', (e) => {
            this.filters.setShowTransitiveEdges(e.target.checked);
            this.triggerFilterChange();
        });

        // Physics toggle checkbox
        document.getElementById('enablePhysics').addEventListener('change', (e) => {
            this.triggerEvent('togglePhysics', e.target.checked);
        });

        // Button controls
        document.getElementById('resetViewBtn').addEventListener('click', () => {
            this.resetView();
        });

        document.getElementById('fitNetworkBtn').addEventListener('click', () => {
            this.triggerEvent('fitNetwork');
        });

        document.getElementById('clearSelectionBtn').addEventListener('click', () => {
            this.clearSelection();
        });
    }

    /**
     * Custom event system for UI actions
     */
    eventHandlers = {};

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

    triggerFilterChange() {
        this.triggerEvent('filterChange');
    }

    /**
     * Update statistics display
     * @param {Object} stats - { totalNodes, totalEdges, visibleNodes, visibleEdges }
     */
    updateStats(stats) {
        document.getElementById('totalNodes').textContent = stats.totalNodes;
        document.getElementById('totalEdges').textContent = stats.totalEdges;
        document.getElementById('visibleNodes').textContent = stats.visibleNodes;
        document.getElementById('visibleEdges').textContent = stats.visibleEdges;
    }

    /**
     * Display node details in info panel
     * @param {string} nodeId
     */
    displayNodeDetails(nodeId) {
        this.selectedNodeId = nodeId;
        const node = this.loader.getNodeById(nodeId);
        
        if (!node) {
            this.clearNodeDetails();
            return;
        }

        const outgoingEdges = this.loader.getOutgoingEdges(nodeId);
        const incomingEdges = this.loader.getIncomingEdges(nodeId);

        let html = `
            <div class="info-section">
                <h2>Node Details</h2>
                <div class="info-row">
                    <span class="info-label">ID:</span>
                    <span class="info-value">${this.escapeHtml(node.id)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Name:</span>
                    <span class="info-value">${this.escapeHtml(node.name)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Kind:</span>
                    <span class="info-value">${this.escapeHtml(node.kind)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Layer:</span>
                    <span class="info-value">${this.escapeHtml(node.layer)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">File:</span>
                    <span class="info-value">${this.escapeHtml(node.file)}</span>
                </div>
                <div class="info-row">
                    <span class="info-label">Lines:</span>
                    <span class="info-value">${node.lineno || 'N/A'}-${node.end_lineno || 'N/A'} (${node.loc || 'N/A'} LOC)</span>
                </div>
            </div>
        `;

        if (node.docstring) {
            html += `
                <details>
                    <summary>Documentation</summary>
                    <div class="docstring">${this.escapeHtml(node.docstring)}</div>
                </details>
            `;
        }

        if (outgoingEdges.length > 0) {
            html += `
                <details>
                    <summary>Outgoing (${outgoingEdges.length})</summary>
                    <div class="edge-list">
                        ${outgoingEdges.map(e => this.renderEdgeItem(e, e.target_id, true)).join('')}
                    </div>
                </details>
            `;
        }

        if (incomingEdges.length > 0) {
            html += `
                <details>
                    <summary>Incoming (${incomingEdges.length})</summary>
                    <div class="edge-list">
                        ${incomingEdges.map(e => this.renderEdgeItem(e, e.source_id, false)).join('')}
                    </div>
                </details>
            `;
        }

        document.getElementById('nodeInfo').innerHTML = html;
    }

    /**
     * Render an edge item for the edge list
     * @param {Object} edge
     * @param {string} connectedNodeId
     * @param {boolean} isOutgoing
     * @returns {string}
     */
    renderEdgeItem(edge, connectedNodeId, isOutgoing) {
        return `
            <div class="edge-item">
                <span class="edge-type">${this.escapeHtml(edge.type)}</span>
                <span class="edge-target">
                    ${this.escapeHtml(connectedNodeId)}
                </span>
            </div>
        `;
    }

    /**
     * Clear node details display
     */
    clearNodeDetails() {
        this.selectedNodeId = null;
        document.getElementById('nodeInfo').innerHTML = `
            <p style="color: #858585; font-size: 13px; font-style: italic;">
                Click on a node to view details
            </p>
        `;
    }

    /**
     * Clear current selection
     */
    clearSelection() {
        this.clearNodeDetails();
        this.triggerEvent('clearSelection');
    }

    /**
     * Reset all filters and view
     */
    resetView() {
        // Reset filters
        this.filters.resetFilters();

        // Update UI controls
        document.getElementById('search').value = '';
        document.getElementById('interfaceFilter').value = this.filters.selectedInterface;
        document.getElementById('showTransitiveEdges').checked = true;

        // Reset checkboxes
        document.querySelectorAll('#layerFilters input[type="checkbox"]').forEach(cb => {
            cb.checked = true;
        });
        document.querySelectorAll('#kindFilters input[type="checkbox"]').forEach(cb => {
            cb.checked = true;
        });
        document.querySelectorAll('#edgeTypeFilters input[type="checkbox"]').forEach(cb => {
            cb.checked = true;
        });

        // Trigger update
        this.triggerFilterChange();
        this.triggerEvent('fitNetwork');
    }

    /**
     * Show loading screen
     * @param {string} message
     */
    showLoading(message = 'Loading...') {
        const loading = document.getElementById('loading');
        loading.style.display = 'block';
        loading.innerHTML = `
            <div style="text-align: center; color: #cccccc; padding: 32px;">
                <div class="spinner"></div>
                <div style="margin-top: 16px;">${this.escapeHtml(message)}</div>
                <div id="progress" style="margin-top: 8px; font-size: 12px; color: #858585;">0%</div>
            </div>
        `;
    }

    /**
     * Update loading progress
     * @param {number} percentage
     * @param {number} completed
     * @param {number} total
     */
    updateProgress(percentage, completed, total) {
        const progressEl = document.getElementById('progress');
        if (progressEl) {
            progressEl.textContent = `${percentage}% (${completed}/${total})`;
        }
    }

    /**
     * Hide loading screen and show main UI
     */
    hideLoading() {
        document.getElementById('loading').style.display = 'none';
        document.getElementById('container').style.display = 'flex';
    }

    /**
     * Show file input dialog
     * @param {Function} onFileSelected - Callback when file is selected
     */
    showFileInput(onFileSelected) {
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
    }

    /**
     * Show error message
     * @param {string} message
     */
    showError(message) {
        document.getElementById('loading').innerHTML = `
            <div style="text-align: center; color: #cccccc; padding: 32px;">
                <h2 style="color: #d16969; margin-bottom: 16px;">❌ Error</h2>
                <p style="margin-bottom: 16px; font-size: 14px; color: #d4d4d4;">${this.escapeHtml(message)}</p>
                <button onclick="location.reload()" style="padding: 8px 16px; background: #0e639c; border: none; border-radius: 3px; color: white; cursor: pointer;">
                    Reload Page
                </button>
            </div>
        `;
    }

    /**
     * Escape HTML to prevent XSS
     * @param {string} str
     * @returns {string}
     */
    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}
