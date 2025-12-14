/**
 * Module for loading and processing graph data
 */

export class GraphLoader {
    constructor() {
        this.graphData = null;
        this.interfaceNodes = [];
        this.nodeConnectionMap = new Map(); // Maps node id -> set of interface ids it's connected to
        this.edgeTypes = new Set();
    }

    /**
     * Load graph data from file or URL
     * @param {string|null} jsonUrl - Optional URL to fetch JSON from
     * @returns {Promise<boolean>} - Success status
     */
    async loadGraph(jsonUrl = null) {
        if (jsonUrl) {
            try {
                // Add cache-busting timestamp to prevent stale data
                const cacheBustedUrl = `${jsonUrl}?t=${Date.now()}`;
                const response = await fetch(cacheBustedUrl, {
                    cache: 'no-store'
                });
                if (!response.ok) {
                    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
                }
                this.graphData = await response.json();
                this.validateGraphData();
                await this.processGraphData();
                return true;
            } catch (error) {
                console.error('Failed to load graph from URL:', error);
                return false;
            }
        }
        return false;
    }

    /**
     * Load graph from file input
     * @param {File} file - File object from input
     * @returns {Promise<void>}
     */
    async loadFromFile(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = async (e) => {
                try {
                    this.graphData = JSON.parse(e.target.result);
                    this.validateGraphData();
                    await this.processGraphData();
                    resolve();
                } catch (error) {
                    reject(new Error('Error parsing JSON: ' + error.message));
                }
            };
            reader.onerror = () => reject(new Error('Error reading file'));
            reader.readAsText(file);
        });
    }

    /**
     * Validate graph data structure
     * @throws {Error} if data is invalid
     */
    validateGraphData() {
        if (!this.graphData) {
            throw new Error('No graph data loaded');
        }
        if (!Array.isArray(this.graphData.nodes)) {
            throw new Error('Invalid graph data: missing or invalid "nodes" array');
        }
        if (!Array.isArray(this.graphData.edges)) {
            throw new Error('Invalid graph data: missing or invalid "edges" array');
        }

        // Validate required node fields
        const requiredNodeFields = ['id', 'name', 'kind', 'layer', 'file'];
        for (const node of this.graphData.nodes) {
            for (const field of requiredNodeFields) {
                if (!(field in node)) {
                    throw new Error(`Node missing required field "${field}": ${JSON.stringify(node)}`);
                }
            }
        }

        // Validate required edge fields
        const requiredEdgeFields = ['source_id', 'target_id', 'type'];
        for (const edge of this.graphData.edges) {
            for (const field of requiredEdgeFields) {
                if (!(field in edge)) {
                    throw new Error(`Edge missing required field "${field}": ${JSON.stringify(edge)}`);
                }
            }
        }
    }

    /**
     * Process graph data: extract metadata and build connection map
     */
    async processGraphData() {
        // Extract edge types
        this.edgeTypes.clear();
        this.graphData.edges.forEach(edge => this.edgeTypes.add(edge.type));
        
        // Find interface entrypoints
        this.interfaceNodes = this.findInterfaceNodes();
        
        // Build connection map asynchronously
        await this.buildConnectionMapAsync();
    }

    /**
     * Find interface entrypoint nodes (FastAPI routes and CLI commands)
     * @returns {Array} Sorted array of interface nodes
     */
    findInterfaceNodes() {
        return this.graphData.nodes
            .filter(n => {
                if (n.layer !== 'interfaces') return false;
                if (n.kind !== 'function' && n.kind !== 'method') return false;
                // FastAPI routes in *_if.py files
                if (n.file.includes('_if.py')) return true;
                // CLI commands
                if (n.kind === 'function' && n.name.startsWith('cmd_')) return true;
                if (n.name === 'main' && n.file.includes('cli')) return true;
                return false;
            })
            .sort((a, b) => a.id.localeCompare(b.id));
    }

    /**
     * Build map of which interfaces each node is reachable from
     * Uses BFS from each interface, processes in chunks to avoid UI freezing
     * Only follows reachable edge types (CALLS, IMPORTS, etc.) - not structural edges like CONTAINS
     * @param {Function} progressCallback - Optional callback(percentage, completed, total)
     */
    async buildConnectionMapAsync(progressCallback = null) {
        // Only follow edges that represent actual usage/calls, not structural containment
        const REACHABLE_EDGE_TYPES = new Set([
            'CALLS', 'CALLS_FUNCTION', 'CALLS_METHOD', 'CALLS_CLASS',
            'CALLS_ATTRIBUTE', 'CALLS_DEPENDENCY', 'CALLS_THREAD_TARGET',
            'USES_TYPE', 'IMPORTS'
        ]);
        
        // Build edge lookup for faster access
        const edgesBySource = new Map();
        this.graphData.edges.forEach(edge => {
            // Only include edges that represent reachability
            if (REACHABLE_EDGE_TYPES.has(edge.type)) {
                if (!edgesBySource.has(edge.source_id)) {
                    edgesBySource.set(edge.source_id, []);
                }
                edgesBySource.get(edge.source_id).push(edge.target_id);
            }
        });
        
        this.nodeConnectionMap.clear();
        const totalInterfaces = this.interfaceNodes.length;
        let completed = 0;
        
        // Process interfaces in chunks to avoid freezing
        for (const interfaceNode of this.interfaceNodes) {
            // Do BFS for this interface
            const reachable = new Set();
            const queue = [interfaceNode.id];
            const visited = new Set();
            
            while (queue.length > 0) {
                const currentId = queue.shift();
                if (visited.has(currentId)) continue;
                visited.add(currentId);
                reachable.add(currentId);
                
                // Find all outgoing edges from this node
                const targets = edgesBySource.get(currentId) || [];
                targets.forEach(targetId => {
                    if (!visited.has(targetId)) {
                        queue.push(targetId);
                    }
                });
            }
            
            // Store which interface each node is connected to
            reachable.forEach(nodeId => {
                if (!this.nodeConnectionMap.has(nodeId)) {
                    this.nodeConnectionMap.set(nodeId, new Set());
                }
                this.nodeConnectionMap.get(nodeId).add(interfaceNode.id);
            });
            
            // Update progress
            completed++;
            if (progressCallback && (completed % 5 === 0 || completed === totalInterfaces)) {
                const progress = Math.round((completed / totalInterfaces) * 100);
                progressCallback(progress, completed, totalInterfaces);
                // Yield to browser to prevent freezing
                await new Promise(resolve => setTimeout(resolve, 0));
            }
        }
    }

    /**
     * Get all unique layers in the graph
     * @returns {Array<string>}
     */
    getLayers() {
        return [...new Set(this.graphData.nodes.map(n => n.layer))].sort();
    }

    /**
     * Get all unique node kinds in the graph
     * @returns {Array<string>}
     */
    getKinds() {
        return [...new Set(this.graphData.nodes.map(n => n.kind))].sort();
    }

    /**
     * Get all edge types
     * @returns {Array<string>}
     */
    getEdgeTypes() {
        return [...this.edgeTypes].sort();
    }

    /**
     * Get node by id
     * @param {string} nodeId
     * @returns {Object|null}
     */
    getNodeById(nodeId) {
        return this.graphData.nodes.find(n => n.id === nodeId) || null;
    }

    /**
     * Get edges originating from a node
     * @param {string} nodeId
     * @returns {Array}
     */
    getOutgoingEdges(nodeId) {
        return this.graphData.edges.filter(e => e.source_id === nodeId);
    }

    /**
     * Get edges targeting a node
     * @param {string} nodeId
     * @returns {Array}
     */
    getIncomingEdges(nodeId) {
        return this.graphData.edges.filter(e => e.target_id === nodeId);
    }
}
