module.exports = {
    env: {
        browser: true,
        es2021: true
    },
    extends: 'eslint:recommended',
    parserOptions: {
        ecmaVersion: 2021,
        sourceType: 'module'
    },
    rules: {
        // Warn on console.log (keep console.error/warn)
        'no-console': ['warn', { allow: ['warn', 'error', 'info'] }],
        
        // Require semicolons
        'semi': ['error', 'always'],
        
        // Enforce consistent indentation
        'indent': ['error', 4],
        
        // Warn on unused variables
        'no-unused-vars': 'warn',
        
        // Error on undefined variables (catches typos in DOM IDs)
        'no-undef': 'error',
        
        // Warn when accessing potentially null objects
        'no-unsafe-optional-chaining': 'warn',
        
        // Allow infinite loops with break conditions (SSE streaming, etc.)
        'no-constant-condition': ['error', { checkLoops: false }]
    },
    globals: {
        // Chart.js
        Chart: 'readonly',
        
        // Global app instance
        app: 'writable'
    }
};
