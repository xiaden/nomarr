/**
 * Graph update operations
 */

export async function clearGraph(context) {
    if (!context.nodes || !context.edges) return;
    
    // Cancel any ongoing physics cooling
    if (context.physicsPolicy) {
        context.physicsPolicy.cancel();
    }
    
    // Clear edges first
    context.edges.clear();
    context.allEdges = [];
    
    // Remove nodes in batches for smooth animation
    const nodeIds = context.nodes.getIds();
    const batchSize = 50;
    const delay = 5;
    
    for (let i = 0; i < nodeIds.length; i += batchSize) {
        const batch = nodeIds.slice(i, i + batchSize);
        context.nodes.remove(batch);
        await new Promise(resolve => setTimeout(resolve, delay));
    }
    
    // Reset state
    context.selectedNodeId = null;
    context.pathHighlight = null;
}

export async function updateGraph(context, nodes, edges, shouldCancel = null, userPhysicsPreference = false) {
    // Detect if this is initial load or filter change
    const currentNodeIds = new Set(context.nodes.getIds());
    const newNodeIds = new Set(nodes.map(n => n.id));
    const isInitialLoad = currentNodeIds.size === 0;
    
    // Store all edges for visibility management
    context.allEdges = edges;
    
    if (isInitialLoad) {
        // Initial load: clear and animate everything in
        context.nodes.clear();
        context.edges.clear();
        context.selectedNodeId = null;
        
        if (nodes.length > 0) {
            // Add nodes one at a time with smooth animation
            const batchSize = 1;
            const delayPerBatch = 20;
            const totalBatches = nodes.length;
            
            // Add ALL edges first
            context.edges.add(edges);
            context.updateEdgeVisibility();
            
            // Sort nodes by edge count (most connected first)
            const edgeCount = new Map();
            edges.forEach(edge => {
                edgeCount.set(edge.from, (edgeCount.get(edge.from) || 0) + 1);
                edgeCount.set(edge.to, (edgeCount.get(edge.to) || 0) + 1);
            });
            const sortedNodes = [...nodes].sort((a, b) => 
                (edgeCount.get(b.id) || 0) - (edgeCount.get(a.id) || 0)
            );
            
            // Start physics cooling cycle
            if (context.physicsPolicy) {
                context.physicsPolicy.startCooling(userPhysicsPreference);
            }
            
            // Build edge lookup for positioning
            const nodeConnections = new Map();
            edges.forEach(edge => {
                if (!nodeConnections.has(edge.from)) nodeConnections.set(edge.from, []);
                if (!nodeConnections.has(edge.to)) nodeConnections.set(edge.to, []);
                nodeConnections.get(edge.from).push(edge.to);
                nodeConnections.get(edge.to).push(edge.from);
            });
            
            // Add nodes gradually
            for (let i = 0; i < sortedNodes.length; i += batchSize) {
                // Check for cancellation
                if (shouldCancel && shouldCancel()) {
                    context.nodes.clear();
                    context.edges.clear();
                    return { cancelled: true };
                }
                
                const batch = sortedNodes.slice(i, i + batchSize);
                
                // Position each node near its connected neighbors
                batch.forEach(node => {
                    const connectedIds = nodeConnections.get(node.id) || [];
                    const positions = [];
                    
                    connectedIds.forEach(connectedId => {
                        try {
                            const pos = context.network.getPosition(connectedId);
                            if (pos && pos.x !== undefined && pos.y !== undefined) {
                                positions.push(pos);
                            }
                        } catch (e) {
                            // Node not yet placed
                        }
                    });
                    
                    if (positions.length > 0) {
                        const avgX = positions.reduce((sum, p) => sum + p.x, 0) / positions.length;
                        const avgY = positions.reduce((sum, p) => sum + p.y, 0) / positions.length;
                        const offsetAngle = Math.random() * Math.PI * 2;
                        const offsetDist = 100;
                        node.x = avgX + Math.cos(offsetAngle) * offsetDist;
                        node.y = avgY + Math.sin(offsetAngle) * offsetDist;
                    }
                });
                
                context.nodes.add(batch);
                
                const progress = Math.min(100, Math.round(((i + 1) / totalBatches) * 100));
                context.triggerEvent('loadProgress', { current: i + 1, total: totalBatches, progress });
                
                await new Promise(resolve => setTimeout(resolve, delayPerBatch));
            }
            
            context.triggerEvent('loadProgress', { current: totalBatches, total: totalBatches, progress: 100 });
            
            // Notify physics policy that initial build is complete
            if (context.physicsPolicy) {
                context.physicsPolicy.notifyBuildComplete();
            }
        }
    } else {
        // Filter change: incrementally add/remove
        const nodesToAdd = nodes.filter(n => !currentNodeIds.has(n.id));
        const nodesToRemove = Array.from(currentNodeIds).filter(id => !newNodeIds.has(id));
        
        // Update edges
        context.edges.clear();
        context.edges.add(edges);
        context.updateEdgeVisibility();
        
        // Remove nodes in batches
        if (nodesToRemove.length > 0) {
            const removeBatchSize = 10;
            const removeDelay = 10;
            
            for (let i = 0; i < nodesToRemove.length; i += removeBatchSize) {
                const batch = nodesToRemove.slice(i, i + removeBatchSize);
                context.nodes.remove(batch);
                await new Promise(resolve => setTimeout(resolve, removeDelay));
            }
        }
        
        // Add new nodes
        if (nodesToAdd.length > 0) {
            const addDelay = 20;
            
            // Sort new nodes by edge count
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
            
            // Start physics cooling cycle for new nodes
            if (context.physicsPolicy) {
                context.physicsPolicy.startCooling(userPhysicsPreference);
            }
            
            for (let i = 0; i < sortedNewNodes.length; i++) {
                // Check for cancellation
                if (shouldCancel && shouldCancel()) {
                    return { cancelled: true };
                }
                
                const node = sortedNewNodes[i];
                const connectedIds = nodeConnections.get(node.id) || [];
                const positions = [];
                
                connectedIds.forEach(connectedId => {
                    try {
                        const pos = context.network.getPosition(connectedId);
                        if (pos && pos.x !== undefined && pos.y !== undefined) {
                            positions.push(pos);
                        }
                    } catch (e) {
                        // Node not yet placed
                    }
                });
                
                if (positions.length > 0) {
                    const avgX = positions.reduce((sum, p) => sum + p.x, 0) / positions.length;
                    const avgY = positions.reduce((sum, p) => sum + p.y, 0) / positions.length;
                    const offsetAngle = Math.random() * Math.PI * 2;
                    const offsetDist = 100;
                    node.x = avgX + Math.cos(offsetAngle) * offsetDist;
                    node.y = avgY + Math.sin(offsetAngle) * offsetDist;
                }
                
                context.nodes.add(node);
                await new Promise(resolve => setTimeout(resolve, addDelay));
            }
            
            // Notify physics policy that incremental build is complete
            if (context.physicsPolicy) {
                context.physicsPolicy.notifyBuildComplete();
            }
        }
    }
    
    return { cancelled: false };
}
