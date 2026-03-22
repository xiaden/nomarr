// Package main implements the Nomarr plugin for Navidrome.
//
// This plugin bridges Navidrome to Nomarr's ML-powered APIs:
//   - metadata.SimilarSongsByTrackProvider — Instant Mix via vector ANN search
//   - scrobbler.Scrobbler — forwards scrobble events to Nomarr for taste profiling
//   - scheduler.CallbackProvider — scheduled personal playlist generation and push
package main

import (
	"encoding/json"
	"fmt"
	"net/url"
	"strings"

	"github.com/navidrome/navidrome/plugins/pdk/go/host"
	"github.com/navidrome/navidrome/plugins/pdk/go/metadata"
	"github.com/navidrome/navidrome/plugins/pdk/go/pdk"
	"github.com/navidrome/navidrome/plugins/pdk/go/scheduler"
	"github.com/navidrome/navidrome/plugins/pdk/go/scrobbler"
)

// nomarrPlugin implements metadata.SimilarSongsByTrackProvider,
// scrobbler.Scrobbler, and scheduler.CallbackProvider.
type nomarrPlugin struct{}

func init() {
	metadata.Register(&nomarrPlugin{})
	scrobbler.Register(&nomarrPlugin{})
	scheduler.Register(&nomarrPlugin{})

	// Register playlist generation scheduler if enabled.
	ppEnabled, ok := pdk.GetConfig("pp_enabled")
	if ok && ppEnabled == "true" {
		cron, ok := pdk.GetConfig("pp_schedule_cron")
		if !ok || cron == "" {
			cron = "0 3 * * *"
		}
		if _, err := host.SchedulerScheduleRecurring(cron, "", "nomarr-playlist-gen"); err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to schedule playlist generation: %v", err))
		} else {
			pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: playlist generation scheduled with cron: %s", cron))
		}
	} else {
		pdk.Log(pdk.LogDebug, "nomarr: personal playlists not enabled")
	}
}

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

// readConfig reads the shared nomarr_url and nomarr_api_key from plugin config.
// Returns empty strings and ok=false if either value is missing.
func readConfig() (nomarrURL string, apiKey string, ok bool) {
	nomarrURL, found := pdk.GetConfig("nomarr_url")
	if !found || nomarrURL == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_url not configured")
		return "", "", false
	}
	apiKey, found = pdk.GetConfig("nomarr_api_key")
	if !found || apiKey == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_api_key not configured")
		return "", "", false
	}
	return nomarrURL, apiKey, true
}

// subsonicCallAs calls a Subsonic API endpoint on behalf of a specific user.
// It prepends /rest/ and appends ?u=<username> to the endpoint URI so the
// Subsonic server executes the call in the context of that user.
// Follows the LBZ plugin pattern.
func subsonicCallAs(endpoint string, username string) (string, error) {
	sep := "?"
	if strings.Contains(endpoint, "?") {
		sep = "&"
	}
	uri := fmt.Sprintf("/rest/%s%su=%s", endpoint, sep, url.QueryEscape(username))
	return host.SubsonicAPICall(uri)
}

// xmlDecodeEntities replaces XML character entities with their literal values.
func xmlDecodeEntities(s string) string {
	s = strings.ReplaceAll(s, "&amp;", "&")
	s = strings.ReplaceAll(s, "&lt;", "<")
	s = strings.ReplaceAll(s, "&gt;", ">")
	s = strings.ReplaceAll(s, "&quot;", "\"")
	s = strings.ReplaceAll(s, "&apos;", "'")
	return s
}

// xmlAttr extracts the value of a named attribute from an XML tag string.
// tag should be the full opening tag content (e.g., `<playlist id="123" name="My List"/>`).
// Returns the decoded value and true if found, or ("", false) otherwise.
func xmlAttr(tag string, attr string) (string, bool) {
	// Look for: attr="value" or attr='value'
	needle := attr + `="`
	idx := strings.Index(tag, needle)
	if idx >= 0 {
		start := idx + len(needle)
		end := strings.Index(tag[start:], `"`)
		if end >= 0 {
			return xmlDecodeEntities(tag[start : start+end]), true
		}
	}
	// Try single quotes
	needle = attr + "='"
	idx = strings.Index(tag, needle)
	if idx >= 0 {
		start := idx + len(needle)
		end := strings.Index(tag[start:], "'")
		if end >= 0 {
			return xmlDecodeEntities(tag[start : start+end]), true
		}
	}
	return "", false
}

// findExistingPlaylists queries the Subsonic getPlaylists API for a given user
// and returns a map of playlist name → playlist ID. This is used to determine
// whether to update an existing playlist or create a new one.
//
// On any failure (API error, parse error), returns an empty map with a warning
// log — callers degrade gracefully by creating all playlists as new.
//
// NOTE: TinyGo/WASM cannot use encoding/xml, so we parse with string operations.
func findExistingPlaylists(username string) map[string]string {
	result := make(map[string]string)

	resp, err := subsonicCallAs("getPlaylists", username)
	if err != nil {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: getPlaylists failed for user %s: %v", username, err))
		return result
	}

	// Find all <playlist ...> tags and extract id + name attributes.
	// Handles both self-closing (<playlist .../>) and open (<playlist ...>...</playlist>) forms.
	remaining := resp
	for {
		idx := strings.Index(remaining, "<playlist ")
		if idx < 0 {
			break
		}
		remaining = remaining[idx:]

		// Find the end of the opening tag (either /> or >)
		endSelfClose := strings.Index(remaining, "/>")
		endOpen := strings.Index(remaining, ">")

		var tag string
		if endSelfClose >= 0 && (endOpen < 0 || endSelfClose <= endOpen) {
			// Self-closing tag: <playlist ... />
			tag = remaining[:endSelfClose+2]
			remaining = remaining[endSelfClose+2:]
		} else if endOpen >= 0 {
			// Open tag: <playlist ...>
			tag = remaining[:endOpen+1]
			remaining = remaining[endOpen+1:]
		} else {
			break
		}

		id, hasID := xmlAttr(tag, "id")
		name, hasName := xmlAttr(tag, "name")
		if hasID && hasName {
			result[name] = id
		}
	}

	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: found %d existing playlists for user %s", len(result), username))
	return result
}

// ---------------------------------------------------------------------------
// Similar-tracks types
// ---------------------------------------------------------------------------

// nomarrRequest is the JSON body sent to Nomarr's similar-tracks endpoint.
type nomarrRequest struct {
	SongID     string `json:"song_id"`
	Count      int32  `json:"count"`
	BackboneID string `json:"backbone_id"`
}

// nomarrSong is a single song in Nomarr's API response.
type nomarrSong struct {
	ID     string  `json:"id"`
	Name   string  `json:"name"`
	Artist string  `json:"artist"`
	Album  string  `json:"album"`
	Score  float64 `json:"score"`
}

// nomarrResponse is the JSON response from Nomarr's similar-tracks endpoint.
type nomarrResponse struct {
	Songs []nomarrSong `json:"songs"`
}

// ---------------------------------------------------------------------------
// Scrobble types (Nomarr API payload)
// ---------------------------------------------------------------------------

// scrobbleTrack represents a single track in a scrobble event sent to Nomarr.
type scrobbleTrack struct {
	ID       string  `json:"id"`
	Title    string  `json:"title"`
	Duration float64 `json:"duration"`
}

// scrobbleRequest is the JSON body sent to Nomarr's scrobble endpoint.
type scrobbleRequest struct {
	Username  string        `json:"username"`
	Track     scrobbleTrack `json:"track"`
	Timestamp int64         `json:"timestamp"`
}

// ---------------------------------------------------------------------------
// Playlist generation types
// ---------------------------------------------------------------------------

// userConfig represents a single user entry from the plugin's "users" config array.
type userConfig struct {
	Username     string   `json:"username"`
	EnabledTypes []string `json:"enabled_types,omitempty"`
	MaxSongs     *int     `json:"max_songs,omitempty"`
	MinSongs     *int     `json:"min_songs,omitempty"`
	MaxGenrePlaylists *int     `json:"max_genre_playlists,omitempty"`
}

// generatePlaylistsRequest is the JSON body sent to Nomarr's generate-playlists endpoint.
type generatePlaylistsRequest struct {
	UserID       string   `json:"user_id"`
	EnabledTypes []string `json:"enabled_types,omitempty"`
	MaxSongs     *int     `json:"max_songs,omitempty"`
	MinSongs     *int     `json:"min_songs,omitempty"`
	MaxGenrePlaylists *int     `json:"max_genre_playlists,omitempty"`
}

// playlistResult is a single generated playlist in Nomarr's response.
type playlistResult struct {
	PlaylistType string   `json:"playlist_type"`
	PlaylistName string   `json:"playlist_name"`
	TrackNdIDs   []string `json:"track_nd_ids"`
	TrackCount   int      `json:"track_count"`
}

// generatePlaylistsResponse is the JSON response from Nomarr's generate-playlists endpoint.
type generatePlaylistsResponse struct {
	Playlists []playlistResult `json:"playlists"`
}

// ---------------------------------------------------------------------------
// SimilarSongsByTrackProvider implementation
// ---------------------------------------------------------------------------

// GetSimilarSongsByTrack returns tracks similar to the given track by querying
// Nomarr's similarity API. On any error, it returns an empty response so
// Navidrome can fall back to other agents (Last.fm, ListenBrainz, etc.).
func (p *nomarrPlugin) GetSimilarSongsByTrack(req metadata.SimilarSongsByTrackRequest) (*metadata.SimilarSongsResponse, error) {
	empty := &metadata.SimilarSongsResponse{}

	// Read shared config.
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return empty, nil
	}

	backbone, found := pdk.GetConfig("backbone_id")
	if !found || backbone == "" {
		backbone = "effnet"
	}

	// Build the request to Nomarr's similarity endpoint.
	count := req.Count
	if count <= 0 {
		count = 50
	}

	reqBody := nomarrRequest{
		SongID:     req.ID,
		Count:      count,
		BackboneID: backbone,
	}
	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal request: %v", err))
		return empty, nil
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/similar-tracks"

	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: querying %s for song %s (count=%d, backbone=%s)", endpoint, req.ID, count, backbone))

	// Send HTTP POST via Navidrome host service.
	resp, err := host.HTTPSend(host.HTTPRequest{
		Method: "POST",
		URL:    endpoint,
		Headers: map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    apiKey,
		},
		Body:      bodyBytes,
		TimeoutMs: 30000,
	})
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: HTTP request failed: %v", err))
		return empty, nil
	}

	// Check HTTP status.
	if resp.StatusCode != 200 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: API returned status %d: %s", resp.StatusCode, string(resp.Body)))
		return empty, nil
	}

	// Parse Nomarr response.
	var nomarrResp nomarrResponse
	if err := json.Unmarshal(resp.Body, &nomarrResp); err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse response: %v", err))
		return empty, nil
	}

	// Map Nomarr songs to Navidrome SongRef.
	songs := make([]metadata.SongRef, 0, len(nomarrResp.Songs))
	for _, s := range nomarrResp.Songs {
		songs = append(songs, metadata.SongRef{
			ID:     s.ID,
			Name:   s.Name,
			Artist: s.Artist,
			Album:  s.Album,
		})
	}

	pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: found %d similar tracks for song %s", len(songs), req.ID))

	return &metadata.SimilarSongsResponse{Songs: songs}, nil
}

// ---------------------------------------------------------------------------
// Scrobbler implementation
// ---------------------------------------------------------------------------

// IsAuthorized always returns true — Nomarr accepts all scrobbles from
// configured users. Auth is handled via the API key, not per-user.
func (p *nomarrPlugin) IsAuthorized(_ scrobbler.IsAuthorizedRequest) (bool, error) {
	_, _, ok := readConfig()
	if !ok {
		return false, nil
	}
	return true, nil
}

// NowPlaying is a no-op. Nomarr only needs completed scrobbles, not
// now-playing notifications.
func (p *nomarrPlugin) NowPlaying(_ scrobbler.NowPlayingRequest) error {
	return nil
}

// Scrobble forwards a scrobble event to Nomarr's ingestion API.
// Best-effort: on any error, logs and returns nil so the scrobble pipeline
// in Navidrome is never blocked.
func (p *nomarrPlugin) Scrobble(req scrobbler.ScrobbleRequest) error {
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return nil
	}

	body := scrobbleRequest{
		Username: req.Username,
		Track: scrobbleTrack{
			ID:       req.Track.ID,
			Title:    req.Track.Title,
			Duration: float64(req.Track.Duration),
		},
		Timestamp: req.Timestamp,
	}
	bodyBytes, err := json.Marshal(body)
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal scrobble request: %v", err))
		return nil
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/scrobble"

	pdk.Log(pdk.LogDebug, fmt.Sprintf("nomarr: scrobbling track %s for user %s", req.Track.ID, req.Username))

	resp, err := host.HTTPSend(host.HTTPRequest{
		Method: "POST",
		URL:    endpoint,
		Headers: map[string]string{
			"Content-Type": "application/json",
			"X-API-Key":    apiKey,
		},
		Body:      bodyBytes,
		TimeoutMs: 10000,
	})
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: scrobble HTTP request failed: %v", err))
		return nil
	}

	if resp.StatusCode != 204 && resp.StatusCode != 200 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: scrobble API returned status %d: %s", resp.StatusCode, string(resp.Body)))
	}

	return nil
}

// ---------------------------------------------------------------------------
// Scheduler callback implementation
// ---------------------------------------------------------------------------

// OnCallback handles scheduled task callbacks. Dispatches by schedule ID.
func (p *nomarrPlugin) OnCallback(req scheduler.SchedulerCallbackRequest) error {
	if req.ScheduleID == "nomarr-playlist-gen" {
		generateAndPushPlaylists()
	} else {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: unknown schedule callback: %s", req.ScheduleID))
	}
	return nil
}

// ---------------------------------------------------------------------------
// Playlist generation
// ---------------------------------------------------------------------------

// generateAndPushPlaylists calls Nomarr's generate-playlists API for each
// configured user and pushes the resulting playlists into Navidrome via the
// Subsonic createPlaylist API. Users are read from the "users" config key as a
// JSON array of userConfig objects. If a user fails at any step, the error is
// logged and iteration continues with the next user (error isolation).
func generateAndPushPlaylists() {
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return
	}

	// Read and parse the users config array.
	usersJSON, ok := pdk.GetConfig("users")
	if !ok || usersJSON == "" {
		pdk.Log(pdk.LogWarn, "nomarr: no users configured, skipping playlist generation")
		return
	}

	var users []userConfig
	if err := json.Unmarshal([]byte(usersJSON), &users); err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse users config: %v", err))
		return
	}

	if len(users) == 0 {
		pdk.Log(pdk.LogWarn, "nomarr: users array is empty, skipping playlist generation")
		return
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/generate-playlists"

	for _, user := range users {
		if user.Username == "" {
			pdk.Log(pdk.LogWarn, "nomarr: skipping user entry with empty username")
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: requesting playlist generation for user %s", user.Username))

		// Build per-user request — only include optional fields when set.
		reqBody := generatePlaylistsRequest{
			UserID:       user.Username,
			EnabledTypes: user.EnabledTypes,
			MaxSongs:     user.MaxSongs,
			MinSongs:     user.MinSongs,
			MaxGenrePlaylists: user.MaxGenrePlaylists,
		}

		bodyBytes, err := json.Marshal(reqBody)
		if err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal request for user %s: %v", user.Username, err))
			continue
		}

		resp, err := host.HTTPSend(host.HTTPRequest{
			Method: "POST",
			URL:    endpoint,
			Headers: map[string]string{
				"Content-Type": "application/json",
				"X-API-Key":    apiKey,
			},
			Body:      bodyBytes,
			TimeoutMs: 120000,
		})
		if err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: generate-playlists HTTP request failed for user %s: %v", user.Username, err))
			continue
		}

		if resp.StatusCode != 200 {
			pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: generate-playlists API returned status %d for user %s: %s", resp.StatusCode, user.Username, string(resp.Body)))
			continue
		}

		var genResp generatePlaylistsResponse
		if err := json.Unmarshal(resp.Body, &genResp); err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse generate-playlists response for user %s: %v", user.Username, err))
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: received %d playlists for user %s", len(genResp.Playlists), user.Username))

		// Fetch existing playlists to determine create vs. update.
		existingPlaylists := findExistingPlaylists(user.Username)

		// Push each playlist into Navidrome via Subsonic createPlaylist API.
		for _, pl := range genResp.Playlists {
			var uri string
			var action string

			if playlistID, exists := existingPlaylists[pl.PlaylistName]; exists {
				// Playlist exists — update it by ID.
				uri = "createPlaylist?playlistId=" + url.QueryEscape(playlistID)
				action = "update"
			} else {
				// New playlist — create by name.
				uri = "createPlaylist?name=" + url.QueryEscape(pl.PlaylistName)
				action = "create"
			}

			for _, songID := range pl.TrackNdIDs {
				uri += "&songId=" + url.QueryEscape(songID)
			}

			if _, err := subsonicCallAs(uri, user.Username); err != nil {
				pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to %s playlist %q for user %s: %v", action, pl.PlaylistName, user.Username, err))
				continue
			}

			pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: %s playlist %q (%s, %d tracks) for user %s", action, pl.PlaylistName, pl.PlaylistType, pl.TrackCount, user.Username))
		}
	}
}

func main() {}
