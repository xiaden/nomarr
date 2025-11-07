# Navidrome Web UI - Data Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Browser (Web UI)                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │              Navidrome Tab (index.html)                      │  │
│  ├─────────────────────────────────────────────────────────────┤  │
│  │                                                              │  │
│  │  ┌────────────────────────────────────────────────────┐     │  │
│  │  │         Tag Preview Card                           │     │  │
│  │  │  ┌──────────────────────────────────────────────┐ │     │  │
│  │  │  │ [Load Preview]                               │ │     │  │
│  │  │  │                                              │ │     │  │
│  │  │  │ Tag Key  | Type | Multi | Count | Samples   │ │     │  │
│  │  │  │ ─────────┼──────┼───────┼───────┼───────── │ │     │  │
│  │  │  │ genre    | str  |  ✓    | 1,234 | Rock...   │ │     │  │
│  │  │  │ bpm      | int  |  —    |   890 | 120, 95   │ │     │  │
│  │  │  │ mood_*   | float|  —    | 2,345 | 0.85...   │ │     │  │
│  │  │  └──────────────────────────────────────────────┘ │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                              │  │
│  │  ┌────────────────────────────────────────────────────┐     │  │
│  │  │         Config Generator Card                      │     │  │
│  │  │  ┌──────────────────────────────────────────────┐ │     │  │
│  │  │  │ [Generate Config] [Copy to Clipboard]        │ │     │  │
│  │  │  │                                              │ │     │  │
│  │  │  │ [CustomMappings]                            │ │     │  │
│  │  │  │   "nom:genre" = ["GENRE", "TXXX:GENRE"]     │ │     │  │
│  │  │  │   "nom:bpm" = ["TBPM", "BPM"]               │ │     │  │
│  │  │  │   "nom:mood_happy" = ["TXXX:mood_happy"]    │ │     │  │
│  │  │  │ ...                                          │ │     │  │
│  │  │  └──────────────────────────────────────────────┘ │     │  │
│  │  └────────────────────────────────────────────────────┘     │  │
│  │                                                              │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐  │
│  │          NavidromeManager (js/navidrome.js)                 │  │
│  └─────────────────────────────────────────────────────────────┘  │
│                              ▲   │                                 │
│                              │   │                                 │
│                          fetch() │                                 │
│                              │   ▼                                 │
└──────────────────────────────┼───┼─────────────────────────────────┘
                               │   │
                          ┌────┴───┴────┐
                          │   Session   │
                          │  Auth Token │
                          └────┬───┬────┘
                               │   │
┌──────────────────────────────┼───┼─────────────────────────────────┐
│                       FastAPI Server                                │
├──────────────────────────────┼───┼─────────────────────────────────┤
│                              │   │                                 │
│  ┌───────────────────────────┴───┴──────────────────────────────┐ │
│  │          Web API Endpoints (endpoints/web.py)                 │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │                                                               │ │
│  │  GET /web/api/navidrome/preview                              │ │
│  │  ├─ verify_session()                                         │ │
│  │  ├─ get_config()                                             │ │
│  │  └─ preview_tag_stats(db_path, namespace)                    │ │
│  │                                                               │ │
│  │  GET /web/api/navidrome/config                               │ │
│  │  ├─ verify_session()                                         │ │
│  │  ├─ get_config()                                             │ │
│  │  └─ generate_navidrome_config(db_path, namespace)            │ │
│  │                                                               │ │
│  └───────────────────────────┬───┬──────────────────────────────┘ │
│                              │   │                                 │
│  ┌───────────────────────────┴───┴──────────────────────────────┐ │
│  │   Navidrome Config Generator (services/navidrome/*.py)        │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │                                                               │ │
│  │  preview_tag_stats(db_path, namespace)                       │ │
│  │  ├─ Query library_tags for unique tag_key                    │ │
│  │  ├─ Detect type (float, int, string, array)                  │ │
│  │  ├─ Get sample values (LIMIT 3)                              │ │
│  │  ├─ Count total occurrences                                  │ │
│  │  └─ Return: {namespace, tag_count, tags: [...]}              │ │
│  │                                                               │ │
│  │  generate_navidrome_config(db_path, namespace)               │ │
│  │  ├─ Query library_tags for all tags                          │ │
│  │  ├─ Group by tag_key                                         │ │
│  │  ├─ Detect types and multi-value flags                       │ │
│  │  ├─ Generate tag aliases (ID3v2, iTunes, Vorbis)             │ │
│  │  ├─ Build TOML sections:                                     │ │
│  │  │  ├─ [CustomMappings]                                      │ │
│  │  │  ├─ [CustomMappings.Types]                                │ │
│  │  │  └─ [CustomMappings.MultiValueSeparators]                 │ │
│  │  └─ Return: {namespace, config: "TOML string"}               │ │
│  │                                                               │ │
│  └───────────────────────────┬───┬──────────────────────────────┘ │
│                              │   │                                 │
│  ┌───────────────────────────┴───┴──────────────────────────────┐ │
│  │              Database (data/db.py)                            │ │
│  ├───────────────────────────────────────────────────────────────┤ │
│  │                                                               │ │
│  │  library_tags table:                                         │ │
│  │  ┌─────────┬──────────┬────────────┬──────────────────────┐ │ │
│  │  │ file_id │ tag_key  │ tag_value  │ tag_value_array      │ │ │
│  │  ├─────────┼──────────┼────────────┼──────────────────────┤ │ │
│  │  │    1    │  genre   │   Rock     │       NULL           │ │ │
│  │  │    1    │  bpm     │    120     │       NULL           │ │ │
│  │  │    1    │ mood_*   │    0.85    │       NULL           │ │ │
│  │  │    2    │  genre   │    NULL    │  ["Jazz", "Blues"]   │ │ │
│  │  └─────────┴──────────┴────────────┴──────────────────────┘ │ │
│  │                                                               │ │
│  │  Indexes:                                                     │ │
│  │  ├─ idx_library_tags_file_id                                 │ │
│  │  ├─ idx_library_tags_key                                     │ │
│  │  └─ idx_library_tags_key_value                               │ │
│  │                                                               │ │
│  └───────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         User Workflow                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Scan Library (Library tab)                                     │
│     └─> Populates library_tags table                               │
│                                                                     │
│  2. Navigate to Navidrome tab                                      │
│                                                                     │
│  3. Click "Load Preview"                                           │
│     └─> GET /web/api/navidrome/preview                             │
│         └─> Query library_tags                                     │
│             └─> Display tag statistics table                       │
│                                                                     │
│  4. Click "Generate Config"                                        │
│     └─> GET /web/api/navidrome/config                              │
│         └─> Query library_tags                                     │
│             └─> Generate TOML                                      │
│                 └─> Display configuration                          │
│                                                                     │
│  5. Click "Copy to Clipboard"                                      │
│     └─> navigator.clipboard.writeText(toml)                        │
│         └─> Visual feedback ("Copied!")                            │
│                                                                     │
│  6. Paste into navidrome.toml                                      │
│                                                                     │
│  7. Restart Navidrome                                              │
│     └─> Tags appear in Navidrome UI                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

## Key Benefits

1. **No New Database Schema**: Uses existing library_tags table
2. **Type-Safe**: Auto-detects int, float, string, array types
3. **Multi-Value Support**: Handles tags with multiple values (e.g., genres)
4. **Format Compatibility**: Generates aliases for ID3v2, iTunes, Vorbis
5. **User-Friendly**: Preview before generating, one-click copy
6. **Real-Time**: Shows current library state (scan library first)
7. **Namespace-Aware**: Respects config.yaml namespace setting
