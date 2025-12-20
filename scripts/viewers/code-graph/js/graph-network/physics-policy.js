/**
 * Physics cooling policy for vis-network
 * 
 * Manages physics behavior with a "warm to cool" approach:
 * - After load/update, physics starts "warm" (low damping) so nodes spread out
 * - Over time, increase damping to make the graph settle without jitter
 * - User interactions "reheat" physics briefly, then cooling resumes
 * - Fallback hard stop if graph never settles
 * 
 * Physics Toggle Semantics:
 * - When OFF: Physics is completely disabled. No cooling, no reheating, no movement.
 * - When ON: Full cooling cycle applies (warm → cooling → settled). Interactions reheat.
 * 
 * This is option (a) "Off means fully off" - clean and predictable.
 */

/**
 * Physics cooling states
 */
const CoolingState = {
    IDLE: 'idle',           // Physics disabled, no cooling needed
    WARM: 'warm',           // Initial spread-out phase (low damping)
    COOLING: 'cooling',     // Gradually increasing damping
    SETTLED: 'settled',     // Graph has settled (high damping)
    REHEATING: 'reheating'  // Brief reheat after interaction
};

/**
 * Physics cooling configuration
 */
const COOLING_CONFIG = {
    // Warm phase (initial spread)
    warmDuration: 1000,      // 1s warm phase for nodes to spread
    warmDamping: 0.7,        // Medium-high damping for active spreading
    warmMinVelocity: 0.1,    // Higher threshold = keeps moving longer
    
    // Anchor settle delay (wait after anchors applied)
    anchorSettleDelay: 5000, // 5s for anchors to stabilize before disabling physics
    
    // Reheat on interaction
    reheatDuration: 1000,    // 1s brief movement after drag/zoom
    reheatDamping: 0.8,      // Medium damping for local reflow
    
    // Hard stop fallback
    maxRuntime: 10000,       // 10s max before force-disable
    
    // Stabilization - disabled to prevent jumping
    stabilizationIterations: 0,  // Disable stabilization (causes jumping)
    stabilizationDelay: 0       // No delay needed
};

/**
 * Physics policy manager
 */
export class PhysicsPolicy {
    constructor(context) {
        this.context = context;
        this.state = CoolingState.IDLE;
        this.timers = [];
        this.startTime = null;
        this.userPhysicsEnabled = false;
        this.anchorNodeIds = [];  // Track which nodes are anchored
        this.waitingForBuildComplete = false;  // Track if we're waiting for graph build
    }
    
    /**
     * Start cooling cycle after graph load/update
     * @param {boolean} userPhysicsEnabled - Whether user has physics toggle enabled
     */
    startCooling(userPhysicsEnabled = false) {
        this.userPhysicsEnabled = userPhysicsEnabled;
        
        // If user disabled physics, skip cooling entirely
        if (!userPhysicsEnabled) {
            this.cancel();
            this.context.network.setOptions({ physics: { enabled: false } });
            return;
        }
        
        // Cancel any existing cooling cycle and release anchors for new layout
        this.cancel();
        this.releaseAnchors();
        
        this.state = CoolingState.WARM;
        this.startTime = Date.now();
        this.waitingForBuildComplete = true;  // Don't anchor until build completes
        
        // Enable physics with warm settings
        this._applyPhysicsConfig(COOLING_CONFIG.warmDamping, COOLING_CONFIG.warmMinVelocity);
        
        // Fallback hard stop
        this.timers.push(setTimeout(() => {
            if (this.state !== CoolingState.IDLE) {
                this._forceSettle();
            }
        }, COOLING_CONFIG.maxRuntime));
    }
    
    /**
     * Reheat physics briefly after user interaction
     */
    reheat() {
        // Only reheat if physics is enabled by user and we're not idle
        if (!this.userPhysicsEnabled || this.state === CoolingState.IDLE) {
            return;
        }
        
        // Release anchors so nodes can move during interaction
        this.releaseAnchors();
        
        // Cancel existing timers
        this._clearTimers();
        this.waitingForBuildComplete = false;  // Reheat is instant, not waiting for build
        
        this.state = CoolingState.REHEATING;
        this._applyPhysicsConfig(COOLING_CONFIG.reheatDamping, COOLING_CONFIG.warmMinVelocity);
        
        // After reheat, apply anchors and settle (skip gradual cooling)
        this.timers.push(setTimeout(() => {
            if (this.state === CoolingState.REHEATING) {
                this.state = CoolingState.SETTLED;
                // Apply anchor nodes to stop drift/rotation
                this._applyAnchorNodes();
                
                // Wait for anchors to stabilize, then disable physics
                this.timers.push(setTimeout(() => {
                    if (this.state === CoolingState.SETTLED && this.userPhysicsEnabled) {
                        this.context.network.setOptions({ physics: { enabled: false } });
                    }
                }, COOLING_CONFIG.anchorSettleDelay));
            }
        }, COOLING_CONFIG.reheatDuration));
    }
    
    /**
     * Cancel all cooling timers and reset
     */
    cancel() {
        this._clearTimers();
        this.state = CoolingState.IDLE;
        this.startTime = null;
    }
    
    /**
     * Update user physics preference
     */
    setUserPhysicsEnabled(enabled) {
        this.userPhysicsEnabled = enabled;
        
        if (!enabled) {
            // User disabled physics - cancel cooling and disable
            this.cancel();
            this.context.network.setOptions({ physics: { enabled: false } });
        } else {
            // User enabled physics - start cooling if we have a graph
            if (this.context.nodes && this.context.nodes.getIds().length > 0) {
                this.startCooling(true);
            }
        }
    }
    
    /**
     * Notify that graph building is complete
     * Triggers transition from warmup to anchored settle
     */
    notifyBuildComplete() {
        if (!this.waitingForBuildComplete || this.state !== CoolingState.WARM) {
            return;  // Not waiting or already past warm phase
        }
        
        this.waitingForBuildComplete = false;
        this.state = CoolingState.SETTLED;
        
        // Apply anchor nodes to stop drift/rotation
        this._applyAnchorNodes();
        
        // Wait for anchors to stabilize, then disable physics
        this.timers.push(setTimeout(() => {
            if (this.state === CoolingState.SETTLED && this.userPhysicsEnabled) {
                this.context.network.setOptions({ physics: { enabled: false } });
            }
        }, COOLING_CONFIG.anchorSettleDelay));
    }
    

    /**
     * Force settle the graph (fallback hard stop)
     * @private
     */
    _forceSettle() {
        this.state = CoolingState.SETTLED;
        // Force stop physics if it's taking too long
        this.context.network.setOptions({ physics: { enabled: false } });
    }
    
    /**
     * Apply physics configuration to network
     * @private
     */
    _applyPhysicsConfig(damping, minVelocity) {
        if (!this.context.network) return;
        
        this.context.network.setOptions({
            physics: {
                enabled: true,
                forceAtlas2Based: {
                    damping: damping
                },
                minVelocity: minVelocity
            }
        });
    }
    
    /**
     * Clear all active timers
     * @private
     */
    _clearTimers() {
        this.timers.forEach(timer => clearTimeout(timer));
        this.timers = [];
    }
    
    /**
     * Apply anchor nodes to stop drift/rotation
     * Selects 1-2 high-degree nodes and fixes their positions
     * @private
     */
    _applyAnchorNodes() {
        if (!this.context.nodes || !this.context.edges) return;
        
        const nodes = this.context.nodes.get();
        const edges = this.context.edges.get();
        
        if (nodes.length < 2) return; // Need at least 2 nodes for anchoring
        
        // Build degree map (count connections per node)
        const degreeMap = new Map();
        nodes.forEach(node => degreeMap.set(node.id, 0));
        
        edges.forEach(edge => {
            degreeMap.set(edge.from, (degreeMap.get(edge.from) || 0) + 1);
            degreeMap.set(edge.to, (degreeMap.get(edge.to) || 0) + 1);
        });
        
        // Sort nodes by degree (descending)
        const sortedNodes = [...nodes].sort((a, b) => 
            (degreeMap.get(b.id) || 0) - (degreeMap.get(a.id) || 0)
        );
        
        // Select anchorA = highest degree node
        const anchorA = sortedNodes[0];
        
        // Select anchorB = high-degree node far from anchorA
        // Build adjacency for distance calculation
        const adjacency = new Map();
        nodes.forEach(node => adjacency.set(node.id, new Set()));
        edges.forEach(edge => {
            adjacency.get(edge.from).add(edge.to);
            adjacency.get(edge.to).add(edge.from);
        });
        
        // BFS to find distance from anchorA
        const distances = new Map();
        const queue = [anchorA.id];
        distances.set(anchorA.id, 0);
        
        while (queue.length > 0) {
            const current = queue.shift();
            const dist = distances.get(current);
            
            for (const neighbor of adjacency.get(current) || []) {
                if (!distances.has(neighbor)) {
                    distances.set(neighbor, dist + 1);
                    queue.push(neighbor);
                }
            }
        }
        
        // From top 10 degree nodes (excluding anchorA), pick the one farthest from anchorA
        const candidates = sortedNodes.slice(1, 11); // Top 2-11 by degree
        let anchorB = candidates[0];
        let maxDist = 0;
        
        for (const node of candidates) {
            const dist = distances.get(node.id) || 0;
            if (dist > maxDist) {
                maxDist = dist;
                anchorB = node;
            }
        }
        
        // Get current positions from network (they've been laid out by physics)
        const positions = this.context.network.getPositions([anchorA.id, anchorB.id]);
        
        // Fix both anchor nodes at their current positions
        this.anchorNodeIds = [anchorA.id, anchorB.id];
        
        this.context.nodes.update([
            {
                id: anchorA.id,
                fixed: { x: true, y: true },
                x: positions[anchorA.id].x,
                y: positions[anchorA.id].y
            },
            {
                id: anchorB.id,
                fixed: { x: true, y: true },
                x: positions[anchorB.id].x,
                y: positions[anchorB.id].y
            }
        ]);
    }
    
    /**
     * Release anchor nodes (make them movable again)
     * Call this before reheating or re-layout
     */
    releaseAnchors() {
        if (this.anchorNodeIds.length === 0) return;
        
        this.context.nodes.update(
            this.anchorNodeIds.map(id => ({
                id: id,
                fixed: false
            }))
        );
        
        this.anchorNodeIds = [];
    }
}
