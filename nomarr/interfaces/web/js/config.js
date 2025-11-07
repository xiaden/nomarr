/**
 * Configuration Manager
 * Handles loading and saving application configuration
 */
import { UIHelpers } from './ui.js';

class ConfigManager {
    constructor(app) {
        this.app = app;
    }

    async loadConfig() {
        try {
            const response = await fetch('/web/api/config', {
                headers: this.app.authManager.getAuthHeaders()
            });

            if (!response.ok) {
                throw new Error('Failed to load configuration');
            }

            const config = await response.json();
            this.populateConfigForm(config);
            UIHelpers.showSuccess('Configuration loaded');
        } catch (error) {
            console.error('[Config] Load error:', error);
            UIHelpers.showError('Failed to load configuration: ' + error.message);
        }
    }

    populateConfigForm(config) {
        // Tag writing settings
        document.getElementById('config-namespace').value = config.namespace || '';
        document.getElementById('config-version-tag').value = config.version_tag || '';
        document.getElementById('config-overwrite-tags').value = String(config.overwrite_tags);

        // Processing rules
        document.getElementById('config-min-duration').value = config.min_duration_s || 7;
        document.getElementById('config-allow-short').value = String(config.allow_short);

        // Worker settings
        document.getElementById('config-worker-enabled').value = String(config.worker_enabled);
        document.getElementById('config-worker-count').value = config.worker_count || 1;
        document.getElementById('config-poll-interval').value = config.poll_interval || 2;
        document.getElementById('config-cleanup-age').value = config.cleanup_age_hours || 168;

        // API settings
        document.getElementById('config-blocking-mode').value = String(config.blocking_mode);
        document.getElementById('config-blocking-timeout').value = config.blocking_timeout || 3600;

        // Cache settings
        document.getElementById('config-cache-timeout').value = config.cache_idle_timeout || 300;
        document.getElementById('config-cache-auto-evict').value = String(config.cache_auto_evict);

        // Library settings
        document.getElementById('config-library-path').value = config.library_path || '';
        document.getElementById('config-library-poll').value = config.library_scan_poll_interval || 10;
    }

    async saveAllConfig() {
        const configs = [
            // Tag writing
            { key: 'namespace', value: document.getElementById('config-namespace').value },
            { key: 'version_tag', value: document.getElementById('config-version-tag').value },
            { key: 'overwrite_tags', value: document.getElementById('config-overwrite-tags').value },

            // Processing rules
            { key: 'min_duration_s', value: document.getElementById('config-min-duration').value },
            { key: 'allow_short', value: document.getElementById('config-allow-short').value },

            // Worker settings
            { key: 'worker_enabled', value: document.getElementById('config-worker-enabled').value },
            { key: 'worker_count', value: document.getElementById('config-worker-count').value },
            { key: 'poll_interval', value: document.getElementById('config-poll-interval').value },
            { key: 'cleanup_age_hours', value: document.getElementById('config-cleanup-age').value },

            // API settings
            { key: 'blocking_mode', value: document.getElementById('config-blocking-mode').value },
            { key: 'blocking_timeout', value: document.getElementById('config-blocking-timeout').value },

            // Cache settings
            { key: 'cache_idle_timeout', value: document.getElementById('config-cache-timeout').value },
            { key: 'cache_auto_evict', value: document.getElementById('config-cache-auto-evict').value },

            // Library settings
            { key: 'library_path', value: document.getElementById('config-library-path').value },
            { key: 'library_scan_poll_interval', value: document.getElementById('config-library-poll').value },
        ];

        let successCount = 0;
        let failCount = 0;

        for (const config of configs) {
            try {
                const response = await fetch('/web/api/config', {
                    method: 'POST',
                    headers: this.app.authManager.getAuthHeaders(),
                    body: JSON.stringify(config)
                });

                if (!response.ok) {
                    const error = await response.json();
                    throw new Error(error.detail || 'Failed to save');
                }

                successCount++;
            } catch (error) {
                console.error(`[Config] Error saving ${config.key}:`, error);
                failCount++;
            }
        }

        if (failCount === 0) {
            UIHelpers.showSuccess(`All settings saved (${successCount} updated). Restart container for most changes to take effect.`);
        } else {
            UIHelpers.showError(`Saved ${successCount} settings, ${failCount} failed. Check console for details.`);
        }

        // Refresh worker status if worker_enabled changed
        if (this.app.adminManager) {
            setTimeout(() => this.app.adminManager.updateWorkerStatus(), 500);
        }
    }
}

export { ConfigManager };
