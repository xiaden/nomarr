# Navidrome Integration Guide

## Overview

Navidrome is a self-hosted music streaming server that can read custom tags from your music files and use them in Smart Playlists. This document explains how to integrate Nomarr's auto-tagging with Navidrome's custom tag and Smart Playlist features.

## Key Concepts

### 1. Custom Tags in Navidrome

Navidrome only imports a [predefined set of tags](https://github.com/navidrome/navidrome/blob/master/resources/mappings.yaml) by default. However, it supports **custom tags** that can be configured in `navidrome.toml`:

```toml
# Tag naming in Navidrome uses underscores (dots not allowed in TOML keys)
Tags.my_custom_tag.Aliases = ["nom:my-custom-tag", "----:com.apple.iTunes:nom:my-custom-tag", "NOM_MY_CUSTOM_TAG"]
Tags.my_custom_tag.Type = "string"  # or "int", "float", "date", "uuid"
Tags.my_custom_tag.MaxLength = 50
Tags.my_custom_tag.Album = false  # Set true if tag applies to albums
Tags.my_custom_tag.Split = ["; ", " / "]  # Delimiters for multi-value tags
```

**Critical**: The `Aliases` array must include **all three** tag format variations based on how Nomarr writes tags:
- **ID3v2.3/MP3 TXXX**: `nom:tag-name` (namespace:key format)
- **M4A/iTunes freeform**: `----:com.apple.iTunes:nom:tag-name` (full iTunes atom path)
- **FLAC/OGG/Opus Vorbis**: `NOM_TAG_NAME` (uppercase, colons and hyphens converted to underscores)

Navidrome will match any alias when scanning files.

**Important**: After adding custom tags, you must run a **full scan** (not quick scan) for changes to take effect.

### 2. Smart Playlists

Navidrome Smart Playlists are JSON files (`.nsp` extension) that define dynamic playlist rules. They can filter/sort by:
- Standard fields (title, album, artist, year, rating, playcount, etc.)
- User interaction fields (loved, lastplayed, dateloved)
- **Custom tags** (any tag configured in navidrome.toml)

## Integration Strategy

### Phase 1: Configure Navidrome to Read Essentia Tags

Since Nomarr writes tags under the `essentia:` namespace, configure Navidrome to import them:

**navidrome.toml** (in your Navidrome `/data` volume):

**Note**: Tag aliases must match how Nomarr writes tags to different file formats:
- **MP3 (ID3v2 TXXX)**: `nom:mood-strict` (namespace:key with hyphens)
- **M4A (iTunes freeform)**: `----:com.apple.iTunes:nom:mood-strict` (iTunes prefix + namespace:key)
- **FLAC/OGG/Opus (Vorbis)**: `NOM_MOOD_STRICT` (uppercase, colons/hyphens → underscores)

```toml
# Mood tags (multi-value)
Tags.mood_strict.Aliases = ["nom:mood-strict", "----:com.apple.iTunes:nom:mood-strict", "NOM_MOOD_STRICT"]
Tags.mood_strict.Split = ["; "]  # Multi-value separator

Tags.mood_regular.Aliases = ["nom:mood-regular", "----:com.apple.iTunes:nom:mood-regular", "NOM_MOOD_REGULAR"]
Tags.mood_regular.Split = ["; "]

Tags.mood_loose.Aliases = ["nom:mood-loose", "----:com.apple.iTunes:nom:mood-loose", "NOM_MOOD_LOOSE"]
Tags.mood_loose.Split = ["; "]

# Regression values (0.0-1.0 scores)
Tags.approachability.Aliases = ["nom:approachability_regression", "----:com.apple.iTunes:nom:approachability_regression", "NOM_APPROACHABILITY_REGRESSION"]
Tags.approachability.Type = "float"

Tags.engagement.Aliases = ["nom:engagement_regression", "----:com.apple.iTunes:nom:engagement_regression", "NOM_ENGAGEMENT_REGRESSION"]
Tags.engagement.Type = "float"

# Classification tags
Tags.danceability.Aliases = ["nom:danceability", "----:com.apple.iTunes:nom:danceability", "NOM_DANCEABILITY"]

Tags.gender.Aliases = ["nom:gender", "----:com.apple.iTunes:nom:gender", "NOM_GENDER"]

Tags.timbre.Aliases = ["nom:timbre", "----:com.apple.iTunes:nom:timbre", "NOM_TIMBRE"]

Tags.tonal_atonal.Aliases = ["nom:tonal_atonal", "----:com.apple.iTunes:nom:tonal_atonal", "NOM_TONAL_ATONAL"]

Tags.acoustic_electronic.Aliases = ["nom:nsynth_acoustic_electronic", "----:com.apple.iTunes:nom:nsynth_acoustic_electronic", "NOM_NSYNTH_ACOUSTIC_ELECTRONIC"]

Tags.bright_dark.Aliases = ["nom:nsynth_bright_dark", "----:com.apple.iTunes:nom:nsynth_bright_dark", "NOM_NSYNTH_BRIGHT_DARK"]

# NOTE: These are example tags from common models. Your actual tags depend on which
# models you have installed. Use 'nom-cli navidrome config' to generate a complete
# config based on your library's actual tags.
```

After updating `navidrome.toml`, run a **full library scan** in Navidrome.

### Phase 2: Create Smart Playlists

Smart playlists are stored as `.nsp` files in your music library or `PlaylistsPath` directory.

#### Example: Chill Acoustic Playlist

**chill_acoustic.nsp**:
```json
{
  "name": "Chill Acoustic",
  "comment": "Relaxing acoustic tracks",
  "all": [
    { "contains": { "mood_strict": "relaxed" } },
    { "contains": { "acoustic_electronic": "acoustic" } }
  ],
  "sort": "-rating,title",
  "limit": 100
}
```

#### Example: High Energy Party Mix

**party_mix.nsp**:
```json
{
  "name": "Party Mix",
  "comment": "High-energy dance tracks",
  "all": [
    { "any": [
      { "contains": { "mood_strict": "happy" } },
      { "contains": { "mood_strict": "energetic" } }
    ]},
    { "contains": { "danceability": "danceable" } },
    { "gt": { "engagement": 0.7 } }
  ],
  "sort": "-engagement,random",
  "limit": 50
}
```

#### Example: Mellow Electronic

**mellow_electronic.nsp**:
```json
{
  "name": "Mellow Electronic",
  "comment": "Calm electronic tracks",
  "all": [
    { "contains": { "mood_regular": "calm" } },
    { "contains": { "acoustic_electronic": "electronic" } },
    { "lt": { "engagement": 0.5 } }
  ],
  "sort": "approachability,-rating",
  "limit": 75
}
```

## Smart Playlist Syntax Reference

### Available Operators

| Operator | Description | Example |
|----------|-------------|---------|
| `is` | Exact match | `{ "is": { "gender": "male" } }` |
| `isNot` | Not equal | `{ "isNot": { "timbre": "dark" } }` |
| `contains` | String contains | `{ "contains": { "mood_strict": "happy" } }` |
| `notContains` | String doesn't contain | `{ "notContains": { "mood_loose": "sad" } }` |
| `startsWith` | String starts with | `{ "startsWith": { "timbre": "bright" } }` |
| `endsWith` | String ends with | N/A for our tags |
| `gt` | Greater than (numbers) | `{ "gt": { "engagement": 0.7 } }` |
| `lt` | Less than (numbers) | `{ "lt": { "approachability": 0.3 } }` |
| `inTheRange` | Range (inclusive) | `{ "inTheRange": { "engagement": [0.5, 0.8] } }` |

### Logical Operators

- **`all`**: AND condition (all rules must match)
- **`any`**: OR condition (at least one rule must match)

### Sorting

```json
{
  "sort": "field1,-field2,field3",  // + = ascending (default), - = descending
  "order": "desc",  // Global order (reverses all fields)
  "limit": 100
}
```

Examples:
- `"sort": "approachability"` - Sort by approachability (ascending)
- `"sort": "-engagement,title"` - Sort by engagement (descending), then title (ascending)
- `"sort": "random"` - Random order

### Multi-Value Tag Matching

For tags like `mood_strict` (which can have multiple values: "happy; energetic"):

```json
// Matches tracks with "happy" anywhere in mood_strict
{ "contains": { "mood_strict": "happy" } }

// Matches tracks that are both happy AND energetic
{ "all": [
  { "contains": { "mood_strict": "happy" } },
  { "contains": { "mood_strict": "energetic" } }
]}

// Matches tracks that are happy OR energetic
{ "any": [
  { "contains": { "mood_strict": "happy" } },
  { "contains": { "mood_strict": "energetic" } }
]}
```

## Workflow

### For Nomarr (This Project)

1. **Tag your music** with Nomarr (via API, CLI, or Web UI)
   ```bash
   curl -X POST http://autotag:8356/api/v1/tag \
     -H "Authorization: Bearer <API_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"path": "/music/Album/Track.mp3"}'
   ```

2. Tags are written to files under `nom:` namespace:
   - `nom:mood-strict` = "happy; energetic"
   - `nom:danceability` = "danceable"
   - `nom:engagement_regression` = "0.823"

### For Navidrome

1. **Configure custom tags** in `navidrome.toml` (see Phase 1 above)

2. **Run full library scan** in Navidrome UI (Settings → Library → Full Scan)

3. **Create `.nsp` files** in your music library or `PlaylistsPath`:
   ```bash
   # Place .nsp files anywhere in your music library
   /music/Playlists/chill_acoustic.nsp
   /music/Playlists/party_mix.nsp
   ```

4. **Trigger playlist import** (happens during library scan or on playlist access)

5. **Playlists auto-update** when accessed (minimum 5s delay between refreshes)

## Advanced: Playlist Templates for Nomarr

Nomarr could provide **template `.nsp` files** that users can drop into their Navidrome library:

**templates/moods/**:
- `happy_energetic.nsp` - High-energy positive tracks
- `sad_melancholic.nsp` - Emotional, introspective tracks
- `relaxed_calm.nsp` - Low-energy chill tracks
- `aggressive_intense.nsp` - Heavy, intense tracks

**templates/styles/**:
- `bright_electronic.nsp` - Bright electronic music
- `dark_acoustic.nsp` - Dark acoustic tracks
- `highly_danceable.nsp` - Top dance tracks

**templates/advanced/**:
- `approachable_but_engaging.nsp` - Easy-listening but interesting
- `challenging_listen.nsp` - Complex, less approachable tracks

Users can then customize these templates for their library.

## Notes and Limitations

### Important Notes

1. **Case insensitive**: Tag names are case-insensitive in Navidrome
2. **Multi-value separator**: Use `"; "` (semicolon-space) for multi-value tags
3. **Full scan required**: After changing `navidrome.toml`, run a full scan (not quick scan)
4. **Playlist ownership**: Default owner is first admin user
5. **Auto-refresh**: Playlists refresh when accessed (5s minimum delay)
6. **File location**: `.nsp` files can be anywhere in music library or `PlaylistsPath`
7. **Tag name format**: Navidrome field names use underscores (`mood_strict`), aliases match file format (see above)
8. **Dynamic tags**: Actual tags depend on your installed models - use library scan or `nom-cli navidrome config` to generate accurate config
9. **Three alias formats required**: ID3v2 TXXX (`nom:`), iTunes freeform (`----:com.apple.iTunes:nom:`), and Vorbis (`NOM_`) for cross-format compatibility

### Special Characters

- Underscores (`_`) in tag names work fine
- Special characters in `contains`/`endsWith` might have edge cases
- Use exact tag names from Nomarr output

### Performance

- Smart Playlists are read-only (can't manually add/remove tracks)
- Large libraries: Use `limit` to prevent giant playlists
- Random sorting (`"sort": "random"`) is supported but can be slow

## References

- [Navidrome Custom Tags Docs](https://www.navidrome.org/docs/usage/customtags/)
- [Navidrome Smart Playlists Docs](https://www.navidrome.org/docs/usage/smartplaylists/)
- [Navidrome Default Tag Mappings](https://github.com/navidrome/navidrome/blob/master/resources/mappings.yaml)
- [Feishin](https://github.com/jeffvli/feishin/) - Desktop client with Smart Playlist editor

## Future Enhancements

### Nomarr Could Provide

1. **`.nsp` Generator**: CLI/API to generate Smart Playlists from templates
2. **Preview Tool**: Show which tracks would be included in a playlist
3. **Batch Templates**: Auto-generate 10-20 common playlists
4. **Web UI Builder**: Visual playlist builder that exports `.nsp` files
5. **Tag Statistics**: Show distribution of moods/styles to help create playlists
