# Playlist Import Guide

**Convert Spotify and Deezer playlists to Navidrome-compatible M3U files**

---

## Overview

Nomarr's Playlist Import feature allows you to paste Spotify or Deezer playlist URLs and automatically convert them to M3U playlists by matching tracks against your local library. This bridges the gap between streaming services and your self-hosted music library.

**What this feature provides:**

- **Paste URL** to fetch playlist metadata from Spotify or Deezer
- **Automatic matching** using ISRC codes and fuzzy metadata matching
- **Match quality reporting** with confidence scores and tier classifications
- **M3U export** compatible with Navidrome, Plex, and other music servers
- **Unmatched track detection** to identify gaps in your library

---

## How It Works

```
User pastes URL
    ↓
Fetch playlist from API (Spotify/Deezer)
    ↓
Load library tracks from ArangoDB
    ↓
Match tracks (ISRC → Exact → Fuzzy)
    ↓
Generate M3U file
    ↓
Display results & allow download
```

**Matching Strategy:**

1. **ISRC Match (Tier: isrc, Confidence: 100%)** - Exact match using International Standard Recording Code
2. **Exact Metadata Match (Tier: exact, Confidence: 95%)** - Perfect title + artist match after normalization
3. **High Fuzzy Match (Tier: fuzzy_high, Confidence: 85%+)** - Strong similarity using fuzzy string matching
4. **Low Fuzzy Match (Tier: fuzzy_low, Confidence: 70-85%)** - Moderate similarity (may need review)
5. **No Match (Tier: none)** - Track not found in library

**Normalization:**

- Unicode NFKC normalization
- Lowercase conversion
- Removal of "feat.", "ft.", "remaster", "deluxe" suffixes
- Punctuation removal for comparison

---

## Prerequisites

1. **Nomarr installed and configured** (see [getting_started.md](getting_started.md))
2. **Library imported** with at least one library configured
3. **For Spotify playlists**: Spotify API credentials (see Configuration below)
4. **For Deezer playlists**: No additional configuration needed (public API)

---

## Configuration

### Spotify API Credentials (Required for Spotify Playlists)

To import from Spotify, you need to create a Spotify app and obtain API credentials:

**1. Create Spotify App:**

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. Log in with your Spotify account
3. Click "Create app"
4. Fill in:
   - **App Name**: "Nomarr Playlist Import" (or any name)
   - **App Description**: "Import playlists to Nomarr"
   - **Redirect URI**: `http://localhost` (not used but required)
5. Accept terms and click "Save"
6. Click "Settings" to view your credentials
7. Copy **Client ID** and **Client Secret**

**2. Add to Nomarr Config:**

Edit `config.yaml`:

```yaml
spotify_client_id: "your_client_id_here"
spotify_client_secret: "your_client_secret_here"
```

**Or use environment variables:**

```bash
export NOMARR_SPOTIFY_CLIENT_ID="your_client_id_here"
export NOMARR_SPOTIFY_CLIENT_SECRET="your_client_secret_here"
```

**3. Restart Nomarr:**

```bash
docker compose restart
```

### Deezer (No Configuration Needed)

Deezer playlists work out of the box using their public API. No credentials required.

---

## Usage

### Web UI

1. **Navigate to Playlist Import page**
   - Open Nomarr web UI at `http://localhost:8356`
   - Click "Playlist Import" in the sidebar

2. **Paste playlist URL**
   - Copy a playlist URL from Spotify or Deezer:
     - Spotify: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
     - Deezer: `https://www.deezer.com/playlist/1282483245`
     - Deezer short link: `https://deezer.page.link/abc123`
   - Paste into the URL field

3. **Select library**
   - Choose which library to match against from the dropdown

4. **Click "Convert Playlist"**
   - Nomarr fetches the playlist and matches tracks
   - Progress indicator shows while processing

5. **Review results**
   - **Match statistics**: Shows matched/unmatched counts and success percentage
   - **Results table**: Lists each track with:
     - Input track name and artist
     - Match tier badge (ISRC/Exact/High Fuzzy/Low Fuzzy/Not Found)
     - Confidence percentage

6. **Download M3U**
   - Click "Download M3U" button to save the playlist file
   - File is named `{playlist_name}.m3u`

### API

See [API Reference](api_reference.md#playlist-import-endpoints) for programmatic usage.

---

## Supported URL Formats

### Spotify

- **Web URL**: `https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M`
- **URI**: `spotify:playlist:37i9dQZF1DXcBWIGoYBM5M`

### Deezer

- **Web URL**: `https://www.deezer.com/playlist/1282483245`
- **Short link**: `https://deezer.page.link/abc123` (auto-resolves to full URL)

---

## Match Quality

### Understanding Confidence Scores

- **100% (ISRC)**: Perfect match via ISRC code - safe to include
- **95% (Exact)**: Perfect metadata match - safe to include
- **85%+ (High Fuzzy)**: Strong similarity - usually correct
- **70-85% (Low Fuzzy)**: Moderate similarity - review recommended
- **Not Found**: Track not in library

### Tips for Better Matching

1. **Ensure metadata quality**: Accurate tags improve fuzzy matching
2. **Check ISRC tags**: ISRC codes provide perfect matching when present
3. **Review low confidence matches**: Manual verification recommended for 70-85% confidence
4. **Import missing tracks**: Use unmatched tracks list to identify library gaps

---

## M3U File Format

Generated M3U files follow the extended M3U format:

```m3u
#EXTM3U
#EXTINF:234,Artist Name - Track Title
/path/to/music/library/Artist/Album/Track.mp3
#EXTINF:187,Another Artist - Another Track
/path/to/music/library/Another Artist/Album/Track.mp3
```

**Compatible with:**

- Navidrome
- Plex
- VLC Media Player
- Most music servers and players supporting M3U

---

## Troubleshooting

### Spotify Playlists Not Working

**Problem**: "Spotify credentials not configured" warning

**Solution**:

1. Verify credentials are in `config.yaml`:

   ```yaml
   spotify_client_id: "your_client_id"
   spotify_client_secret: "your_client_secret"
   ```

2. Restart Nomarr: `docker compose restart`
3. Check logs for authentication errors: `docker logs nomarr`

**Problem**: "Failed to convert playlist" error

**Possible causes**:

- Invalid client ID or secret
- Playlist is private and not accessible
- Network connectivity issues

**Solution**:

1. Verify credentials are correct in Spotify Developer Dashboard
2. Ensure playlist is public or accessible with your Spotify account
3. Check network connectivity to `api.spotify.com`

### Low Match Rates

**Problem**: Many tracks not matched or low confidence

**Solutions**:

1. **Check metadata quality**:
   - Ensure library files have accurate artist/title tags
   - Run metadata cleanup if needed

2. **Check ISRC availability**:
   - ISRC tags provide best matching
   - Consider tools like MusicBrainz Picard for ISRC tagging

3. **Library gaps**:
   - Use unmatched tracks list to identify missing albums
   - Import missing tracks to improve match rate

### Deezer Short Links Not Resolving

**Problem**: Deezer short links (deezer.page.link) fail to convert

**Solution**:

- Ensure Nomarr can access external URLs
- Try using the full Deezer URL instead:
  1. Open short link in browser
  2. Copy full URL from address bar
  3. Use that URL in Nomarr

---

## Limitations

1. **Spotify API Rate Limits**: Spotify enforces rate limits on API calls. Large playlists may take time to fetch.
2. **Fuzzy Matching Accuracy**: Metadata variations can cause false positives or negatives. Review low confidence matches.
3. **Path Format**: Generated M3U files use absolute paths from your Nomarr library. Ensure your music server uses the same path mounting.
4. **Public Playlists Only**: Private playlists require additional OAuth implementation (not currently supported).

---

## Example Workflow

### Converting a Spotify Playlist

1. **Find playlist on Spotify**:
   - Example: "This Is The Beatles" playlist
   - URL: `https://open.spotify.com/playlist/37i9dQZF1DZ06evO3nMr04`

2. **Convert in Nomarr**:
   - Navigate to Playlist Import page
   - Paste URL
   - Select library: "Main Music Library"
   - Click "Convert Playlist"

3. **Review results**:
   - Matched: 42 tracks (95%)
   - Unmatched: 2 tracks (5%)
   - Average confidence: 96%

4. **Download M3U**:
   - Click "Download M3U"
   - Save as `this_is_the_beatles.m3u`

5. **Import to Navidrome**:
   - Copy M3U to Navidrome's playlist directory
   - Scan playlists in Navidrome
   - Playlist appears with 42 matched tracks

---

## See Also

- [API Reference](api_reference.md#playlist-import-endpoints) - Programmatic playlist conversion
- [Navidrome Integration](navidrome.md) - Smart playlists using Nomarr tags
- [Getting Started](getting_started.md) - Initial setup and configuration
