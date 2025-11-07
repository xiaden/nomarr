// Authentication Module
import { UIHelpers } from './ui.js';

export class AuthManager {
    constructor(app) {
        this.app = app;
        this.sessionToken = null;
        this.isAuthenticated = false;
    }
    
    init() {
        // Check for existing session
        this.sessionToken = localStorage.getItem('nomarr_session_token');
        if (this.sessionToken) {
            this.isAuthenticated = true;
            return true;
        }
        return false;
    }
    
    showLoginUI() {
        document.getElementById('login-screen').style.display = 'flex';
        document.getElementById('main-screen').style.display = 'none';
        
        // Setup login form
        const loginForm = document.getElementById('login-form');
        loginForm.onsubmit = (e) => {
            e.preventDefault();
            this.handleLogin();
        };
    }
    
    showMainUI() {
        document.getElementById('login-screen').style.display = 'none';
        document.getElementById('main-screen').style.display = 'block';
    }
    
    async handleLogin() {
        const password = document.getElementById('password').value;
        const errorDiv = document.getElementById('login-error');
        const submitBtn = document.querySelector('#login-form button[type="submit"]');
        
        errorDiv.textContent = '';
        submitBtn.disabled = true;
        submitBtn.textContent = 'Logging in...';
        
        try {
            const response = await fetch('/web/auth/login', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ password })
            });
            
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Login failed');
            }
            
            const data = await response.json();
            this.sessionToken = data.session_token;
            localStorage.setItem('nomarr_session_token', this.sessionToken);
            this.isAuthenticated = true;
            
            console.log('[Auth] Login successful');
            this.app.onLoginSuccess();
            
        } catch (error) {
            console.error('[Auth] Login failed:', error);
            errorDiv.textContent = error.message;
            submitBtn.disabled = false;
            submitBtn.textContent = 'Login';
            document.getElementById('password').value = '';
        }
    }
    
    async handleLogout() {
        console.log('[Auth] Logging out...');
        
        try {
            await fetch('/web/auth/logout', {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${this.sessionToken}` }
            });
        } catch (error) {
            console.error('[Auth] Logout error:', error);
        }
        
        // Clear local state
        this.sessionToken = null;
        this.isAuthenticated = false;
        localStorage.removeItem('nomarr_session_token');
        
        // Disconnect SSE
        this.app.sseManager.disconnect();
        
        // Show login screen
        this.showLoginUI();
        UIHelpers.showMessage('Logged out successfully', 'success');
    }
    
    getAuthHeaders() {
        return {
            'Authorization': `Bearer ${this.sessionToken}`,
            'Content-Type': 'application/json'
        };
    }
    
    handleSessionExpired() {
        console.warn('[Auth] Session expired or invalid, forcing logout');
        
        // Clear local state immediately
        this.sessionToken = null;
        this.isAuthenticated = false;
        localStorage.removeItem('nomarr_session_token');
        
        // Disconnect SSE
        if (this.app.sseManager) {
            this.app.sseManager.disconnect();
        }
        
        // Show login screen
        this.showLoginUI();
        
        // Show error message
        const errorDiv = document.getElementById('login-error');
        if (errorDiv) {
            errorDiv.textContent = 'Your session has expired. Please log in again.';
        }
    }
}
