# Navidrome Integration - Web UI Implementation

> **Note:** This document describes the legacy hand-written JavaScript UI that has been replaced by the TypeScript/React frontend in `frontend/`. The Navidrome integration features described here are being migrated to the new UI.

## Summary

Added a complete Navidrome configuration tab to the Web UI with tag preview and TOML config generation.

## Files Modified

### 1. Backend API (`nomarr/interfaces/api/endpoints/web.py`)

Added two new endpoints:

- **`GET /web/api/navidrome/preview`**
  - Returns tag statistics from library_tags table
  - Response: `{namespace, tag_count, tags: [{tag_key, field_name, type, is_multivalue, sample_values, total_count}]}`
  - Uses session authentication

- **`GET /web/api/navidrome/config`**
  - Generates TOML configuration for Navidrome
  - Response: `{namespace, config: "TOML string"}`
  - Uses session authentication

### 2. Frontend UI (LEGACY - Removed)

**The legacy hand-written HTML/JS UI described below has been removed and replaced with the TypeScript/React frontend in `frontend/`.**

Previous implementation details (for historical reference):

- Added "Navidrome" tab to navigation (between Library and Analytics)
- Added tab content with two main cards:
  - **Tag Preview Card**: Shows all tags available in library with statistics
  - **Config Generator Card**: Generates and displays navidrome.toml configuration

### 3. JavaScript Manager (LEGACY - Removed)

Created NavidromeManager class with methods:

- `loadNavidromePreview()`: Fetches and displays tag statistics in a table
- `generateNavidromeConfig()`: Fetches and displays TOML configuration
- `copyNavidromeConfig()`: Copies TOML to clipboard with visual feedback
- `renderPreview()`: Renders tag preview table
- `renderConfig()`: Renders TOML configuration with usage instructions

### 4. Main App (`nomarr/interfaces/web/app.js`)

- Imported NavidromeManager
- Added navidromeManager instance
- Added convenience methods for inline onclick handlers:
  - `loadNavidromePreview()`
  - `generateNavidromeConfig()`
  - `copyNavidromeConfig()`

### 5. Styles (`nomarr/interfaces/web/styles.css`)

Added CSS for:
- `.info-banner`: Styled info boxes
- `.badge-*`: Type badges for float/int/string/array tags
- `.sample-values`: Monospace font for sample values
- `.config-output`: Styled TOML output container
- `.btn-success`: Green success button state
- `.loading-text`, `.error-text`, `.info-text`: Status text styles

## User Workflow

1. Navigate to **Navidrome** tab in Web UI
2. Click **"Load Preview"** to see available tags in library
   - Shows tag key, field name, type, multi-value flag, count, and sample values
   - Empty library shows helpful message to scan first
3. Click **"Generate Config"** to create navidrome.toml configuration
   - Displays complete TOML configuration
   - Shows namespace and usage instructions
4. Click **"Copy to Clipboard"** to copy TOML
   - Visual feedback ("Copied!" button text for 2 seconds)
5. Paste into `navidrome.toml` and restart Navidrome

## Features

- **Type Detection**: Auto-detects float, int, string, or array types
- **Multi-Value Support**: Flags tags that can have multiple values
- **Tag Aliases**: Generates aliases for ID3v2, iTunes, and Vorbis formats
- **Sample Values**: Shows 3 sample values per tag (truncated for display)
- **Error Handling**: Shows helpful messages for empty libraries or errors
- **Real-Time Feedback**: Loading states, success/error notifications
- **Copy to Clipboard**: One-click copy with visual confirmation

## Integration with Existing System

- Uses same session authentication as other web endpoints
- Follows existing UI patterns (cards, buttons, tables)
- Uses UIHelpers for success/error notifications
- Leverages existing library_tags table (no new database changes)
- Respects namespace configuration from config.yaml

## Testing Checklist

- [ ] Start library scan (Library tab)
- [ ] Switch to Navidrome tab
- [ ] Click "Load Preview" → verify tag table displays
- [ ] Verify tag types are color-coded (float=blue, int=yellow, string=purple, array=green)
- [ ] Verify sample values show correctly
- [ ] Click "Generate Config" → verify TOML appears
- [ ] Click "Copy to Clipboard" → verify button shows "Copied!"
- [ ] Paste into text editor → verify valid TOML
- [ ] Test with empty library → verify helpful message appears

## Notes

- Preview requires library_tags to be populated (run library scan first)
- Config generation uses namespace from config.yaml (default: "nom")
- All tag keys are prefixed with namespace (e.g., "nom:genre", "nom:mood_happy")
- Multi-value tags are automatically detected and configured correctly
- TOML output includes usage instructions for Navidrome setup
