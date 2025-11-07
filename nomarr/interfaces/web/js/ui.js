// UI Helper Functions
export class UIHelpers {
    static showMessage(text, type = 'info', duration = 5000) {
        const messagesDiv = document.getElementById('messages');
        const message = document.createElement('div');
        message.className = `message ${type}`;
        message.innerHTML = `<span>${text}</span><button onclick="this.parentElement.remove()">×</button>`;
        messagesDiv.appendChild(message);
        
        if (duration > 0) {
            setTimeout(() => message.remove(), duration);
        }
        
        return message;
    }
    
    static showError(text, duration = 8000) {
        return UIHelpers.showMessage(text, 'error', duration);
    }
    
    static showSuccess(text, duration = 5000) {
        return UIHelpers.showMessage(text, 'success', duration);
    }
    
    static formatDuration(seconds) {
        if (seconds === null || seconds === undefined) return 'Unknown';
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = Math.floor(seconds % 60);
        
        if (hours > 0) {
            return `${hours}h ${minutes}m ${secs}s`;
        } else if (minutes > 0) {
            return `${minutes}m ${secs}s`;
        } else {
            return `${secs}s`;
        }
    }
    
    static formatFileSize(bytes) {
        if (bytes === null || bytes === undefined) return 'Unknown';
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unitIndex = 0;
        
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        
        return `${size.toFixed(2)} ${units[unitIndex]}`;
    }
    
    static formatTimestamp(timestamp) {
        // Handle null, undefined, 0, or empty string
        if (!timestamp || timestamp === 0) return 'Never';
        const date = new Date(timestamp);
        // Handle invalid dates
        if (isNaN(date.getTime())) return 'Never';
        return date.toLocaleString();
    }
    
    static escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}
