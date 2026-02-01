/**
 * viewport-controller.js - Camera control with debouncing
 * Debounces pan/zoom so expansion auto-centering doesn't fight the user.
 */

import { debounce } from '../utils/debounce.js';

/**
 * Initialize viewport control
 */
export function initViewport(graph) {
    let userInteracting = false;
    
    // Debounced callback to detect user interaction end
    const onInteractionEnd = debounce(() => {
        userInteracting = false;
        console.log('✓ User interaction ended');
    }, 500);
    
    // Track pan/zoom events
    graph.on('viewportchange', () => {
        if (!userInteracting) {
            userInteracting = true;
            console.log('✓ User interaction started');
        }
        onInteractionEnd();
    });
    
    const controller = {
        isUserInteracting() {
            return userInteracting;
        }
    };
    
    console.log('✓ Viewport controller initialized');
    return controller;
}
