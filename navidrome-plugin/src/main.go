// Package main implements the Nomarr plugin for Navidrome.
//
// This plugin bridges Navidrome's Instant Mix feature to Nomarr's ML-powered
// audio similarity API. When a user clicks Instant Mix on a track in Navidrome,
// this plugin queries Nomarr for sonically similar tracks using vector ANN search
// over ML-derived audio embeddings.
package main

import (
	"encoding/json"
	"fmt"
	"strings"

	"github.com/navidrome/navidrome/plugins/pdk/go/host"
	"github.com/navidrome/navidrome/plugins/pdk/go/metadata"
	"github.com/navidrome/navidrome/plugins/pdk/go/pdk"
)

// nomarrPlugin implements metadata.SimilarSongsByTrackProvider.
type nomarrPlugin struct{}

func init() {
	metadata.Register(&nomarrPlugin{})
}

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

// GetSimilarSongsByTrack returns tracks similar to the given track by querying
// Nomarr's similarity API. On any error, it returns an empty response so
// Navidrome can fall back to other agents (Last.fm, ListenBrainz, etc.).
func (p *nomarrPlugin) GetSimilarSongsByTrack(req metadata.SimilarSongsByTrackRequest) (*metadata.SimilarSongsResponse, error) {
	empty := &metadata.SimilarSongsResponse{}

	// Read plugin configuration.
	nomarrURL, ok := pdk.GetConfig("nomarr_url")
	if !ok || nomarrURL == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_url not configured")
		return empty, nil
	}
	apiKey, ok := pdk.GetConfig("nomarr_api_key")
	if !ok || apiKey == "" {
		pdk.Log(pdk.LogWarn, "nomarr: nomarr_api_key not configured")
		return empty, nil
	}
	backbone, ok := pdk.GetConfig("backbone_id")
	if !ok || backbone == "" {
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

func main() {}
