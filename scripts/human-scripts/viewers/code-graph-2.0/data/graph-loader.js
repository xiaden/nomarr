/**
 * graph-loader.js - Load JSON from file or URL
 * Returns raw data, no normalization
 */

/**
 * Load graph from file
 */
export async function loadGraphFromFile(file) {
    const text = await file.text();
    const data = JSON.parse(text);
    
    return data;
}

/**
 * Load graph from URL
 */
export async function loadGraphFromURL(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Failed to load: ${response.statusText}`);
    }
    
    const data = await response.json();
    
    return data;
}
