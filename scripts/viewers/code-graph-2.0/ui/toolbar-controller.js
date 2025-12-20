/**
 * toolbar-controller.js - Toolbar buttons and stats
 * Reset / Fit / Show All, Toggle modes.
 */

/**
 * Initialize toolbar with callbacks
 */
export function initToolbar({ onUpload, onReset, onFit, onShowAll }) {
    const btnUpload = document.getElementById('btn-upload');
    const btnReset = document.getElementById('btn-reset');
    const btnFit = document.getElementById('btn-fit');
    const btnShowAll = document.getElementById('btn-show-all');
    const fileInput = document.getElementById('file-input');
    
    // Wire buttons
    if (btnUpload && fileInput) {
        btnUpload.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', (e) => {
            const file = e.target.files[0];
            if (file && onUpload) onUpload(file);
        });
    }
    
    if (btnReset && onReset) {
        btnReset.addEventListener('click', onReset);
    }
    
    if (btnFit && onFit) {
        btnFit.addEventListener('click', onFit);
    }
    
    if (btnShowAll && onShowAll) {
        btnShowAll.addEventListener('click', onShowAll);
    }
    
    const controller = {
        updateStats(stats) {
            const statsEl = document.getElementById('stats');
            if (statsEl) {
                statsEl.textContent = `Visible: ${stats.visible} / Total: ${stats.total}`;
            }
        }
    };
    
    console.log('✓ Toolbar controller initialized');
    return controller;
}
