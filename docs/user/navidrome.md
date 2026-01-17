# Navidrome Integration Guide

**Generate Smart Playlists for Navidrome Using Nomarr Tags**

---

## Overview

Nomarr can automatically generate smart playlists for [Navidrome](https://www.navidrome.org/) based on the tags it extracts from your music. This allows you to create dynamic playlists like "Energetic Electronic", "Mellow Acoustic", or "Danceable Pop" that update automatically as you process more music.

**What this integration provides:**
- **Automatic playlist generation** based on tag combinations
- **TOML format** compatible with Navidrome's smart playlist system
- **Regular exports** that sync with your processed tracks
- **Customizable rules** for different genres and moods

---

## How It Works

```
Nomarr Processing
    ↓
Audio Analysis (ML models)
    ↓
Tag Extraction (mood, genre, energy, etc.)
    ↓
Tag Storage (ArangoDB)
    ↓
Playlist Export (TOML files)
    ↓
Copy to Navidrome
    ↓
Smart Playlists in Navidrome
```

**Playlist format (example):**
```toml
# Energetic Electronic Music
name = "Energetic Electronic"
comment = "High-energy electronic tracks with strong beats"

[[rules]]
field = "tag"
operator = "contains"
value = "electronic"

[[rules]]
field = "tag"
operator = "contains"
value = "energetic"

[[rules]]
field = "tag"
operator = "contains"
value = "danceable"
```

---

## Prerequisites

1. **Nomarr installed and configured** (see [getting_started.md](getting_started.md))
2. **Music library processed** (at least partial processing complete)
3. **Calibration applied** (optional but recommended)
4. **Navidrome installed** and configured with your music library

**Navidrome requirements:**
- Version 0.49.0 or newer (smart playlist support)
- Access to Navidrome's playlist directory

---

## Configuration

### 1. Configure Nomarr Export Settings

Edit `config/config.yaml`:

```yaml
navidrome:
  export_dir: "/data/playlists"  # Where to write TOML files
  auto_export: true              # Export automatically after processing
  export_interval: 3600          # Export every hour (seconds)
  
  # Playlist generation rules
  playlists:
    # Mood-based playlists
    - name: "Energetic"
      comment: "High-energy tracks"
      rules:
        - tag: "energetic"
          tier: "strong"  # Only strong matches
    
    - name: "Mellow"
      comment: "Calm and relaxing"
      rules:
        - tag: "mellow"
          tier: "strong"
        - tag: "acoustic"
          tier: "moderate"
    
    # Genre-based playlists
    - name: "Electronic"
      comment: "Electronic music"
      rules:
        - tag: "electronic"
          tier: "strong"
    
    - name: "Rock"
      comment: "Rock music"
      rules:
        - tag: "rock"
          tier: "strong"
    
    # Combined playlists
    - name: "Danceable Pop"
      comment: "Danceable pop tracks"
      rules:
        - tag: "danceable"
          tier: "strong"
        - tag: "pop"
          tier: "moderate"
    
    - name: "Chill Electronic"
      comment: "Mellow electronic music"
      rules:
        - tag: "electronic"
          tier: "strong"
        - tag: "mellow"
          tier: "moderate"
```

**Rule options:**
- `tag`: Tag name (from Nomarr's tag vocabulary)
- `tier`: Tag strength (`strong`, `moderate`, `weak`)
- `operator`: How to combine rules (`and`, `or`)

### 2. Configure Navidrome Playlist Directory

**Option A: Docker volume mount (recommended)**

If both Nomarr and Navidrome run in Docker on the same host:

```yaml
# docker-compose.yml
services:
  nomarr:
    volumes:
      - navidrome-playlists:/data/playlists
  
  navidrome:
    volumes:
      - navidrome-playlists:/data/playlists:ro

volumes:
  navidrome-playlists:
```

**Option B: Copy to Navidrome directory**

If Navidrome runs elsewhere, set up periodic copy:

```bash
# Copy playlists to Navidrome
rsync -av /opt/nomarr/data/playlists/ navidrome-server:/var/lib/navidrome/playlists/
```

**Option C: Network share**

Mount shared directory on both systems:

```yaml
# docker-compose.yml (Nomarr)
services:
  nomarr:
    volumes:
      - /mnt/nas/playlists:/data/playlists
```

---

## Generating Playlists

### Automatic Export

With `auto_export: true`, Nomarr exports playlists automatically:

- After processing completes
- Every `export_interval` seconds
- After calibration updates

**Monitor exports:**
```bash
# Docker
docker exec -it nomarr nom-cli navidrome status

# Native
python -m nomarr.interfaces.cli navidrome status
```

### Manual Export

**Export all playlists now:**

```bash
# Docker
docker exec -it nomarr nom-cli navidrome export

# Native
python -m nomarr.interfaces.cli navidrome export
```

**Export specific playlist:**

```bash
docker exec -it nomarr nom-cli navidrome export --playlist "Energetic"
```

**Export with custom config:**

```bash
docker exec -it nomarr nom-cli navidrome export --config /path/to/custom_playlists.yaml
```

---

## Playlist Examples

### Simple Tag-Based

**High Energy:**
```yaml
playlists:
  - name: "High Energy"
    comment: "Tracks with high energy"
    rules:
      - tag: "energetic"
        tier: "strong"
```

### Multiple Tags (AND)

**Mellow Acoustic:**
```yaml
playlists:
  - name: "Mellow Acoustic"
    comment: "Calm acoustic tracks"
    operator: "and"  # All rules must match
    rules:
      - tag: "mellow"
        tier: "strong"
      - tag: "acoustic"
        tier: "moderate"
```

### Multiple Tags (OR)

**Rock or Metal:**
```yaml
playlists:
  - name: "Rock or Metal"
    comment: "Rock and metal tracks"
    operator: "or"  # Any rule can match
    rules:
      - tag: "rock"
        tier: "strong"
      - tag: "metal"
        tier: "strong"
```

### Complex Rules

**Upbeat Dance Music:**
```yaml
playlists:
  - name: "Upbeat Dance"
    comment: "High-energy danceable tracks"
    operator: "and"
    rules:
      - tag: "danceable"
        tier: "strong"
      - tag: "energetic"
        tier: "strong"
    exclude:
      - tag: "acoustic"  # No acoustic versions
      - tag: "slow"
```

### Tier-Based Filtering

**Only Strong Matches:**
```yaml
playlists:
  - name: "Definitely Electronic"
    comment: "Strong electronic tag only"
    rules:
      - tag: "electronic"
        tier: "strong"  # Exclude moderate/weak matches
```

**Include Moderate:**
```yaml
playlists:
  - name: "Probably Electronic"
    comment: "Strong or moderate electronic tag"
    rules:
      - tag: "electronic"
        tier: ["strong", "moderate"]
```

---

## Using Playlists in Navidrome

### 1. Reload Navidrome

After exporting playlists, Navidrome needs to scan for new files:

**Automatic:**
- Navidrome scans playlists on startup
- Periodic scans (if configured)

**Manual:**
```bash
# Trigger Navidrome rescan
# (Method depends on your Navidrome setup)

# Docker
docker exec navidrome /app/navidrome --scan

# Native
navidrome --scan
```

### 2. View Playlists

In Navidrome web UI:
1. Navigate to "Playlists"
2. Find Nomarr-generated playlists
3. Click playlist to view tracks

**Nomarr playlists are prefixed** (optional):
```yaml
# Add prefix to distinguish from manual playlists
navidrome:
  playlist_prefix: "[Auto] "
```

Result: `[Auto] Energetic`, `[Auto] Mellow`, etc.

### 3. Playlist Updates

**How updates work:**
- Nomarr regenerates TOML files on export
- Navidrome reads updated files on next scan
- Playlists reflect current tag data

**Update frequency:**
- Depends on `export_interval` setting
- Manual exports anytime with `nom-cli navidrome export`

---

## Advanced Configuration

### Custom Tag Queries

**Query by score range:**
```yaml
playlists:
  - name: "Very Electronic"
    comment: "Electronic score > 0.8"
    rules:
      - tag: "electronic"
        score_min: 0.8  # Raw model output score
```

**Query by calibrated threshold:**
```yaml
playlists:
  - name: "Electronic (Calibrated)"
    comment: "Above calibrated threshold"
    rules:
      - tag: "electronic"
        use_calibration: true  # Use calibrated thresholds
```

### Exclude Rules

**Exclude specific tags:**
```yaml
playlists:
  - name: "Electronic (No Ambient)"
    comment: "Electronic but not ambient"
    rules:
      - tag: "electronic"
        tier: "strong"
    exclude:
      - tag: "ambient"
      - tag: "drone"
```

### Minimum Track Count

**Only create playlist if enough tracks:**
```yaml
playlists:
  - name: "Energetic"
    comment: "High-energy tracks"
    min_tracks: 50  # Don't create if < 50 tracks
    rules:
      - tag: "energetic"
        tier: "strong"
```

### Custom TOML Templates

**Override default template:**
```yaml
navidrome:
  template: |
    name = "{{ playlist.name }}"
    comment = "{{ playlist.comment }}"
    
    # Custom metadata
    owner = "Nomarr Auto-Generated"
    public = false
    
    {% for rule in playlist.rules %}
    [[rules]]
    field = "tag"
    operator = "{{ rule.operator }}"
    value = "{{ rule.tag }}"
    {% endfor %}
```

---

## Tag Vocabulary Reference

**Common tags extracted by Nomarr:**

**Mood:**
- `energetic`, `mellow`, `happy`, `sad`, `aggressive`, `peaceful`

**Genre:**
- `rock`, `pop`, `electronic`, `jazz`, `classical`, `hip hop`, `metal`

**Instrumentation:**
- `acoustic`, `electric`, `vocal`, `instrumental`

**Rhythm:**
- `danceable`, `fast`, `slow`

**Production:**
- `live`, `studio`, `lo-fi`, `hi-fi`

See full vocabulary in Nomarr web UI under "Tags" page.

**Tag tiers:**
- **Strong:** High confidence (> calibrated threshold or score > 0.7)
- **Moderate:** Medium confidence (score 0.4-0.7)
- **Weak:** Low confidence (score 0.2-0.4)

---

## Troubleshooting

### Playlists Not Appearing in Navidrome

**Check export directory:**
```bash
# List exported playlists
docker exec -it nomarr ls -l /data/playlists/

# Should see .toml files
```

**Verify Navidrome can read files:**
```bash
docker exec navidrome ls -l /data/playlists/
```

**Check Navidrome logs:**
```bash
docker logs navidrome | grep -i playlist
```

**Trigger manual scan:**
```bash
docker exec navidrome /app/navidrome --scan
```

### Empty Playlists

**Check if tracks processed:**
```bash
docker exec -it nomarr nom-cli queue status
# Should show completed > 0
```

**Check tag coverage:**
```bash
docker exec -it nomarr nom-cli analytics tags
# Should show tags extracted
```

**Verify calibration applied:**
```bash
docker exec -it nomarr nom-cli calibration status
# Should show completed > 0
```

**Lower tier requirements:**
```yaml
# If "strong" yields no results, try "moderate"
playlists:
  - name: "Electronic"
    rules:
      - tag: "electronic"
        tier: "moderate"  # Lower bar
```

### Playlists Too Large

**Reduce matches:**
```yaml
# Increase tier requirement
playlists:
  - name: "Electronic"
    rules:
      - tag: "electronic"
        tier: "strong"  # Only high-confidence

# Or increase score threshold
playlists:
  - name: "Very Electronic"
    rules:
      - tag: "electronic"
        score_min: 0.8  # Higher threshold
```

### Playlists Not Updating

**Check auto-export enabled:**
```yaml
navidrome:
  auto_export: true
```

**Verify export interval:**
```yaml
navidrome:
  export_interval: 3600  # 1 hour
```

**Trigger manual export:**
```bash
docker exec -it nomarr nom-cli navidrome export
```

**Check Navidrome scan schedule:**
Navidrome must rescan to see updated playlists.

---

## Example Workflow

### 1. Process Music Library

```bash
# Scan library
docker exec -it nomarr nom-cli library scan "My Music"

# Wait for processing to complete
docker exec -it nomarr nom-cli queue status
```

### 2. Apply Calibration

```bash
# Generate calibration data
docker exec -it nomarr nom-cli calibration generate

# Apply calibration
docker exec -it nomarr nom-cli calibration apply
```

### 3. Configure Playlists

Edit `config/config.yaml`:

```yaml
navidrome:
  playlists:
    - name: "Chill"
      rules:
        - tag: "mellow"
          tier: "strong"
    
    - name: "Party"
      rules:
        - tag: "energetic"
          tier: "strong"
        - tag: "danceable"
          tier: "strong"
    
    - name: "Focus"
      rules:
        - tag: "instrumental"
          tier: "strong"
      exclude:
        - tag: "energetic"
```

### 4. Export Playlists

```bash
# Export
docker exec -it nomarr nom-cli navidrome export

# Verify files created
docker exec -it nomarr ls -l /data/playlists/
```

### 5. Load in Navidrome

```bash
# Trigger Navidrome scan
docker exec navidrome /app/navidrome --scan

# Check Navidrome UI
# Navigate to Playlists → see "Chill", "Party", "Focus"
```

### 6. Ongoing Sync

With `auto_export: true`, new tracks automatically added to playlists as they're processed.

---

## API Integration

### Export via HTTP API

```bash
# Trigger export via API
curl -X POST http://localhost:8888/api/web/navidrome/export \
  -H "Authorization: Bearer YOUR_API_KEY"

# Export specific playlist
curl -X POST http://localhost:8888/api/web/navidrome/export \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"playlist": "Energetic"}'
```

### Check Export Status

```bash
curl http://localhost:8888/api/web/navidrome/status \
  -H "Authorization: Bearer YOUR_API_KEY"
```

Response:
```json
{
  "last_export": "2025-12-05T10:30:00Z",
  "playlists_exported": 12,
  "total_tracks": 5432,
  "export_dir": "/data/playlists"
}
```

See [api_reference.md](api_reference.md) for full API documentation.

---

## Advanced Use Cases

### Dynamic Genre Playlists

Create playlists for every genre tag:

```yaml
navidrome:
  auto_genre_playlists: true
  genre_tags:
    - rock
    - pop
    - electronic
    - jazz
    - classical
    - hip hop
    - metal
```

Generates: `Rock.toml`, `Pop.toml`, `Electronic.toml`, etc.

### Mood-Based Radio Stations

Combine multiple moods:

```yaml
playlists:
  - name: "Morning Energy"
    rules:
      - tag: "happy"
        tier: "strong"
      - tag: "energetic"
        tier: "moderate"
  
  - name: "Evening Chill"
    rules:
      - tag: "mellow"
        tier: "strong"
      - tag: "peaceful"
        tier: "moderate"
```

### Decade-Based Smart Playlists

If your library has year metadata:

```yaml
playlists:
  - name: "Energetic 80s"
    rules:
      - tag: "energetic"
        tier: "strong"
    filters:
      year_min: 1980
      year_max: 1989
```

### Workout Playlists

High-energy, fast tempo:

```yaml
playlists:
  - name: "Workout"
    rules:
      - tag: "energetic"
        tier: "strong"
      - tag: "fast"
        tier: "moderate"
      - tag: "danceable"
        tier: "moderate"
    exclude:
      - tag: "mellow"
```

---

## Next Steps

**Learn more:**
- [Getting Started](getting_started.md) - Basic setup
- [API Reference](api_reference.md) - HTTP API for automation
- [Calibration Guide](../dev/calibration.md) - Tune tag thresholds

**Navidrome resources:**
- [Navidrome Documentation](https://www.navidrome.org/docs/)
- [Smart Playlists](https://www.navidrome.org/docs/usage/playlists/)

---

## FAQ

**Q: Can I edit generated playlists manually?**

A: Not recommended. Nomarr will overwrite changes on next export. For custom playlists, create separate files with different names.

**Q: How often should I export?**

A: Depends on processing frequency:
- Active processing: Every 1-2 hours
- Occasional rescans: Daily or weekly
- Static library: Once after processing completes

**Q: Can I use Nomarr tags in Navidrome's query language?**

A: Yes, if tags are written to file metadata. Currently Nomarr stores tags in its database only. File tagging is planned for future release.

**Q: Do playlists update when calibration changes?**

A: Yes, recalibration affects tag tiers, which affects playlist membership. Export after calibration to update playlists.

**Q: Can I share playlists with other Navidrome users?**

A: Yes, copy `.toml` files to other Navidrome instances. Tags are based on file paths, so music libraries must match.
