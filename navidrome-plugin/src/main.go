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

// generatePlaylistsRequest is the JSON body sent to Nomarr's generate-playlists endpoint.
type generatePlaylistsRequest struct {
	UserID string `json:"user_id"`
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
		backbone = "effnet-discogs"
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

// generateAndPushPlaylists calls Nomarr's generate-playlists API and pushes
// each resulting playlist into Navidrome via the Subsonic createPlaylist API.
func generateAndPushPlaylists() {
	nomarrURL, apiKey, ok := readConfig()
	if !ok {
		return
	}

	ppUserID, ok := pdk.GetConfig("pp_user_id")
	if !ok || ppUserID == "" {
		pdk.Log(pdk.LogWarn, "nomarr: pp_user_id not configured, skipping playlist generation")
		return
	}

	// Request playlist generation from Nomarr.
	reqBody := generatePlaylistsRequest{UserID: ppUserID}
	bodyBytes, err := json.Marshal(reqBody)
	if err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to marshal generate-playlists request: %v", err))
		return
	}

	endpoint := strings.TrimRight(nomarrURL, "/") + "/api/v1/navidrome/generate-playlists"

	pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: requesting playlist generation for user %s", ppUserID))

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
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: generate-playlists HTTP request failed: %v", err))
		return
	}

	if resp.StatusCode != 200 {
		pdk.Log(pdk.LogWarn, fmt.Sprintf("nomarr: generate-playlists API returned status %d: %s", resp.StatusCode, string(resp.Body)))
		return
	}

	var genResp generatePlaylistsResponse
	if err := json.Unmarshal(resp.Body, &genResp); err != nil {
		pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to parse generate-playlists response: %v", err))
		return
	}

	pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: received %d playlists from Nomarr", len(genResp.Playlists)))

	// Push each playlist into Navidrome via Subsonic createPlaylist API.
	for _, pl := range genResp.Playlists {
		uri := "createPlaylist?name=" + url.QueryEscape(pl.PlaylistName)
		for _, songID := range pl.TrackNdIDs {
			uri += "&songId=" + url.QueryEscape(songID)
		}

		if _, err := host.SubsonicAPICall(uri); err != nil {
			pdk.Log(pdk.LogError, fmt.Sprintf("nomarr: failed to push playlist %q: %v", pl.PlaylistName, err))
			continue
		}

		pdk.Log(pdk.LogInfo, fmt.Sprintf("nomarr: pushed playlist %q (%s, %d tracks)", pl.PlaylistName, pl.PlaylistType, pl.TrackCount))
	}
}

func main() {}
